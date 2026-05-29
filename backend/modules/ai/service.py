"""High-level AI service.

Composes :class:`OpenAIClient` + :class:`ConversationMemory` +
:class:`QualificationTracker` + repository inserts into one cohesive
``respond_turn`` / ``finalize_call`` API.

Two consumers:

* :mod:`modules.ai.router` — HTTP endpoints (``/api/v1/ai/converse`` etc).
* :mod:`modules.ai.orchestrator` — the live STT → LLM → TTS loop.

Both go through this service so prompt rendering, persistence, and
qualification updates can't drift between batch and real-time paths.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Iterator

from sqlalchemy.orm import Session

from common.logging import get_logger
from database.session import SessionLocal
from modules.ai.exceptions import AIError
from modules.ai.memory import CallMemorySnapshot, ConversationMemory
from modules.ai.openai_client import OpenAIClient, StreamChunk, build_messages
from modules.ai.prompts import render_system_prompt
from modules.ai.qualification import (
    QualificationFramework,
    QualificationState,
    QualificationTracker,
)
from modules.ai.repository import (
    AICallRepository,
    AICallSummaryRepository,
    AITranscriptRepository,
)
from modules.ai.schema import (
    ChatMessage,
    ChatTurnResult,
    ChatTurnStats,
    MessageRole,
    QualificationSnapshot,
)
from config.settings import settings

log = get_logger("ai.service")


@contextmanager
def _db_scope() -> Iterator[Session]:
    """Local DB session for orchestrator paths that don't have FastAPI's DI."""

    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    """What :meth:`AIService.respond_turn` returns to its caller."""

    reply: str
    stats: ChatTurnStats
    qualification: QualificationSnapshot
    history_length: int




class AIService:
    """Composes LLM client + memory + qualification + persistence."""

    def __init__(
        self,
        *,
        openai: OpenAIClient,
        memory: ConversationMemory,
    ) -> None:
        self._openai = openai
        self._memory = memory

   

    @property
    def memory(self) -> ConversationMemory:
        return self._memory

    @property
    def openai(self) -> OpenAIClient:
        return self._openai



    async def start_call(
        self,
        *,
        call_id: str,
        persona: str | None = None,
        framework: QualificationFramework | str | None = None,
        organization_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        extra_context: dict | None = None,
    ) -> CallMemorySnapshot:
        """Initialise (or resume) a call: write Redis meta + the DB row."""

        fw = self._normalise_framework(framework)
        meta = {
            "persona": persona or settings.AI_DEFAULT_PERSONA,
            "framework": fw.value,
            "extra_context": extra_context or {},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "organization_id": str(organization_id) if organization_id else None,
            "created_by": str(created_by) if created_by else None,
        }
        await self._memory.set_meta(call_id, meta)

        await asyncio.to_thread(
            self._upsert_call_row,
            call_id=call_id,
            organization_id=organization_id,
            created_by=created_by,
            persona=meta["persona"],
            framework=fw.value,
            extra=extra_context,
        )

        snapshot = await self._memory.snapshot(call_id, framework=fw)
        log.info(
            "ai.call.started",
            call_id=call_id,
            persona=meta["persona"],
            framework=fw.value,
        )
        return snapshot

    def _upsert_call_row(
        self,
        *,
        call_id: str,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
        persona: str,
        framework: str,
        extra: dict | None,
    ) -> None:
        with _db_scope() as db:
            AICallRepository.upsert_active(
                db,
                call_id=call_id,
                organization_id=organization_id,
                created_by=created_by,
                persona=persona,
                framework=framework,
                extra=extra,
            )



    async def respond_turn(
        self,
        *,
        call_id: str,
        user_input: str,
        persona: str | None = None,
        framework: QualificationFramework | str | None = None,
        extra_context: dict | None = None,
        organization_id: uuid.UUID | None = None,
        persist_transcript: bool = True,
    ) -> TurnResult:
        """One full turn: load context → call GPT-4o → persist → return."""

        t_turn = time.perf_counter()
        snapshot = await self._memory.snapshot(
            call_id, framework=framework
        )

        meta = snapshot.meta or {}
        effective_persona = persona or meta.get("persona") or settings.AI_DEFAULT_PERSONA
        effective_framework = self._normalise_framework(
            framework or meta.get("framework")
        )
        merged_ctx = {**(meta.get("extra_context") or {}), **(extra_context or {})}

        # 1. Update qualification from the user turn _before_ the LLM call,
        #    so the assistant's reply can take the new state into account
        #    (we re-render the system prompt every turn anyway).
        qual = snapshot.qualification
        qual.framework = effective_framework
        qual.ingest_user_turn(user_input)
        await self._memory.save_qualification(call_id, qual)

        # 2. Render system prompt + call OpenAI.
        system = render_system_prompt(
            persona=effective_persona,
            framework=effective_framework,
            extra_context=merged_ctx,
        )
        messages = build_messages(
            system=system,
            history=snapshot.history,
            user_input=user_input,
        )

        try:
            result: ChatTurnResult = await self._openai.stream_collected(
                messages,
                user=call_id,
            )
        except AIError:
            # Persist the user turn anyway so we don't lose it on retry.
            await self._memory.record_user_turn(call_id, user_input)
            raise

        reply_text = result.text or self._fallback_reply()
        stats = result.stats

        # 3. Append both messages to memory.
        await self._memory.record_user_turn(call_id, user_input)
        await self._memory.record_assistant_turn(
            call_id,
            reply_text,
            tokens=stats.completion_tokens,
            metadata={
                "latency_ms": stats.latency_ms,
                "model": stats.model,
                "finish_reason": stats.finish_reason,
            },
        )

        # 4. Persist transcript rows. Done in a thread because SQLAlchemy
        #    is sync — we don't want to block the asyncio loop.
        if persist_transcript:
            await asyncio.to_thread(
                self._persist_turn_rows,
                call_id=call_id,
                organization_id=organization_id,
                user_text=user_input,
                assistant_text=reply_text,
                stats=stats,
            )

        history = await self._memory.get_history(call_id)
        snapshot_after = qual.snapshot()

        log.info(
            "ai.turn.done",
            call_id=call_id,
            latency_ms=stats.latency_ms,
            ttft_ms=stats.ttft_ms,
            prompt_tokens=stats.prompt_tokens,
            completion_tokens=stats.completion_tokens,
            finish_reason=stats.finish_reason,
            qualification_status=snapshot_after.status,
            qualification_score=snapshot_after.score,
            total_turn_ms=int((time.perf_counter() - t_turn) * 1000),
        )

        return TurnResult(
            reply=reply_text,
            stats=stats,
            qualification=snapshot_after,
            history_length=len(history),
        )

    def _persist_turn_rows(
        self,
        *,
        call_id: str,
        organization_id: uuid.UUID | None,
        user_text: str,
        assistant_text: str,
        stats: ChatTurnStats,
    ) -> None:
        with _db_scope() as db:
            AITranscriptRepository.append(
                db,
                call_id=call_id,
                organization_id=organization_id,
                role=MessageRole.USER.value,
                content=user_text,
            )
            AITranscriptRepository.append(
                db,
                call_id=call_id,
                organization_id=organization_id,
                role=MessageRole.ASSISTANT.value,
                content=assistant_text,
                model=stats.model,
                latency_ms=stats.latency_ms,
                ttft_ms=stats.ttft_ms,
                prompt_tokens=stats.prompt_tokens,
                completion_tokens=stats.completion_tokens,
                total_tokens=stats.total_tokens,
                finish_reason=stats.finish_reason,
            )

    # ------------------------------------------------------------------
    # Streaming surface (used by the orchestrator + future SSE endpoint)
    # ------------------------------------------------------------------

    async def stream_turn(
        self,
        *,
        call_id: str,
        user_input: str,
        persona: str | None = None,
        framework: QualificationFramework | str | None = None,
        extra_context: dict | None = None,
        organization_id: uuid.UUID | None = None,
        persist_transcript: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        """Yield :class:`StreamChunk` chunks; persist when the stream ends.

        Caller owns the lifecycle of the iterator — if they cancel it the
        background persistence still runs for what's been emitted so far.
        """

        snapshot = await self._memory.snapshot(call_id, framework=framework)
        meta = snapshot.meta or {}
        effective_persona = persona or meta.get("persona") or settings.AI_DEFAULT_PERSONA
        effective_framework = self._normalise_framework(
            framework or meta.get("framework")
        )
        merged_ctx = {**(meta.get("extra_context") or {}), **(extra_context or {})}

        qual = snapshot.qualification
        qual.framework = effective_framework
        qual.ingest_user_turn(user_input)
        await self._memory.save_qualification(call_id, qual)

        system = render_system_prompt(
            persona=effective_persona,
            framework=effective_framework,
            extra_context=merged_ctx,
        )
        messages = build_messages(
            system=system,
            history=snapshot.history,
            user_input=user_input,
        )

        # We collect inside the loop so we can persist even if the caller
        # iterates lazily and drops out early.
        collected: list[str] = []
        first_token_ms: int = -1
        t0 = time.perf_counter()
        finish_reason: str | None = None
        try:
            async for chunk in self._openai.stream(messages, user=call_id):
                if chunk.delta and first_token_ms < 0:
                    first_token_ms = int((time.perf_counter() - t0) * 1000)
                if chunk.is_final:
                    finish_reason = chunk.finish_reason
                else:
                    collected.append(chunk.delta)
                yield chunk
        finally:
            text = "".join(collected).strip()
            if text:
                total_ms = int((time.perf_counter() - t0) * 1000)
                stats = ChatTurnStats(
                    latency_ms=total_ms,
                    ttft_ms=max(first_token_ms, 0),
                    model=self._openai.model,
                    finish_reason=finish_reason or "stop",
                )
                # Persist outside the stream so the caller already got
                # the last chunk before we touch Redis/Postgres.
                await self._memory.record_user_turn(call_id, user_input)
                await self._memory.record_assistant_turn(
                    call_id,
                    text,
                    metadata={
                        "latency_ms": total_ms,
                        "ttft_ms": stats.ttft_ms,
                        "finish_reason": finish_reason,
                    },
                )
                if persist_transcript:
                    await asyncio.to_thread(
                        self._persist_turn_rows,
                        call_id=call_id,
                        organization_id=organization_id,
                        user_text=user_input,
                        assistant_text=text,
                        stats=stats,
                    )
                log.info(
                    "ai.stream_turn.done",
                    call_id=call_id,
                    latency_ms=total_ms,
                    ttft_ms=stats.ttft_ms,
                    finish_reason=finish_reason,
                )

    # ------------------------------------------------------------------
    # Read APIs
    # ------------------------------------------------------------------

    async def get_qualification(
        self,
        call_id: str,
        *,
        framework: QualificationFramework | str | None = None,
    ) -> QualificationSnapshot:
        state = await self._memory.get_qualification(call_id, framework=framework)
        return state.snapshot()

    async def get_transcript(
        self, call_id: str
    ) -> list[ChatMessage]:
        return await self._memory.get_history(call_id)

    # ------------------------------------------------------------------
    # End-of-call summarisation
    # ------------------------------------------------------------------

    async def finalize_call(
        self,
        *,
        call_id: str,
        organization_id: uuid.UUID | None = None,
        duration_ms: int | None = None,
        summarise: bool = True,
        clear_memory: bool = True,
    ) -> dict:
        """Generate the LLM call summary, write everything to Postgres,
        and (optionally) drop the Redis keys."""

        snapshot = await self._memory.snapshot(call_id)
        qual = snapshot.qualification

        summary_text: str | None = None
        if summarise and snapshot.history:
            try:
                summary_text = await self._summarise(snapshot.history, qual)
            except AIError as exc:
                log.warning(
                    "ai.summary.failed",
                    call_id=call_id,
                    error=exc.message,
                )
                summary_text = None

        await asyncio.to_thread(
            self._persist_finalization,
            call_id=call_id,
            organization_id=organization_id,
            summary=summary_text,
            qual=qual,
            duration_ms=duration_ms,
        )

        if clear_memory:
            await self._memory.clear_history(call_id)

        log.info(
            "ai.call.finalized",
            call_id=call_id,
            qualification_status=qual.status(),
            qualification_score=qual.score(),
            duration_ms=duration_ms,
            summary_len=len(summary_text or ""),
        )
        return {
            "summary": summary_text,
            "qualification": qual.snapshot().model_dump(),
        }

    def _persist_finalization(
        self,
        *,
        call_id: str,
        organization_id: uuid.UUID | None,
        summary: str | None,
        qual: QualificationState,
        duration_ms: int | None,
    ) -> None:
        with _db_scope() as db:
            totals = AITranscriptRepository.aggregate(db, call_id)
            AICallSummaryRepository.upsert(
                db,
                call_id=call_id,
                organization_id=organization_id,
                summary=summary,
                qualification=qual.snapshot().model_dump(mode="json"),
                qualification_status=qual.status(),
                qualification_score=qual.score(),
                totals=totals,
                duration_ms=duration_ms,
            )
            AICallRepository.mark_status(db, call_id, status="completed")

    async def _summarise(
        self,
        history: list[ChatMessage],
        qual: QualificationState,
    ) -> str:
        """Ask GPT-4o for a short structured call summary."""

        transcript_lines = []
        for m in history:
            who = "Lead" if m.role == MessageRole.USER else "Agent"
            transcript_lines.append(f"{who}: {m.content}")
        transcript = "\n".join(transcript_lines)[:8000]

        fields_summary = "\n".join(
            f"- {k}: {v or '—'}" for k, v in qual.fields.items()
        )

        system = (
            "You are an internal call analyst. Given a transcript and a "
            "qualification snapshot, produce a concise summary in <= 5 short "
            "bullet points covering: lead intent, qualification status, key "
            "objections, next step, and any risks. Do NOT use markdown — "
            "this is dropped into a CRM note. Plain text only."
        )
        user = (
            f"Qualification framework: {qual.framework.value}\n"
            f"Status: {qual.status()} ({qual.score()}/100)\n"
            f"Fields:\n{fields_summary}\n"
            f"\nTranscript:\n{transcript}"
        )

        result = await self._openai.complete(
            [
                ChatMessage(role=MessageRole.SYSTEM, content=system),
                ChatMessage(role=MessageRole.USER, content=user),
            ],
            temperature=0.2,
            max_tokens=400,
        )
        return result.text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_framework(
        framework: QualificationFramework | str | None,
    ) -> QualificationFramework:
        if framework is None:
            return QualificationFramework(settings.AI_QUALIFICATION_FRAMEWORK)
        if isinstance(framework, QualificationFramework):
            return framework
        return QualificationFramework(framework)

    @staticmethod
    def _fallback_reply() -> str:
        """Said by the agent when the LLM returns an empty completion.

        Keeps a live call from going silent. The orchestrator can detect
        this exact string and decide whether to bail out of the loop.
        """

        return "Sorry, could you repeat that?"
