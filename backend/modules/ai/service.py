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
from modules.playbook.branches import evaluate_branches, parse_branch_rules
from modules.playbook.runtime import PlaybookRuntimeConfig
from modules.playbook.service import PlaybookService
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
    branches_fired: list[str] | None = None
    branch_end_call: bool = False
    branch_end_call_message: str | None = None




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
        playbook_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        extra_context: dict | None = None,
    ) -> CallMemorySnapshot:
        """Initialise (or resume) a call: write Redis meta + the DB row."""

        playbook_runtime: PlaybookRuntimeConfig | None = None
        if playbook_id and organization_id:
            log.info(
                "ai.PLAYBOOK_SELECTED",
                call_id=call_id,
                playbook_id=str(playbook_id),
            )
            from modules.playbook.exceptions import PlaybookError

            try:
                playbook_runtime = await asyncio.to_thread(
                    self._load_playbook,
                    organization_id=organization_id,
                    playbook_id=playbook_id,
                )
            except PlaybookError as exc:
                raise AIError(exc.message, status_code=exc.status_code) from exc

        agent_name: str | None = None
        if playbook_runtime:
            from modules.playbook.call_apply import playbook_application_summary
            from modules.playbook.company import resolve_agent_name

            persona = playbook_runtime.persona_name
            framework = playbook_runtime.framework
            agent_name = resolve_agent_name(playbook_runtime)
            summary = playbook_application_summary(playbook_runtime)
            log.info(
                "ai.PLAYBOOK_LOADED",
                call_id=call_id,
                **summary,
            )
            log.info(
                "ai.AGENT_NAME_LOADED",
                call_id=call_id,
                playbook_id=str(playbook_runtime.playbook_id),
                agent_name=agent_name,
            )

        fw = self._normalise_framework(framework)
        meta = {
            "persona": persona or settings.AI_DEFAULT_PERSONA,
            "framework": fw.value,
            "extra_context": extra_context or {},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "organization_id": str(organization_id) if organization_id else None,
            "created_by": str(created_by) if created_by else None,
        }
        if playbook_runtime:
            meta.update(playbook_runtime.to_meta())
            from modules.playbook.call_apply import playbook_application_summary

            log.info(
                "ai.PLAYBOOK_APPLIED",
                call_id=call_id,
                **summary,
            )
            log.info(
                "ai.AGENT_NAME_APPLIED",
                call_id=call_id,
                playbook_id=str(playbook_runtime.playbook_id),
                agent_name=agent_name,
            )
            resolved_voice = (
                playbook_runtime.voice_id or settings.ELEVENLABS_VOICE_ID or None
            )
            log.info(
                "ai.VOICE_APPLIED",
                call_id=call_id,
                playbook_id=str(playbook_runtime.playbook_id),
                playbook_name=summary["playbook_name"],
                voice_id=resolved_voice,
                voice_name=playbook_runtime.voice_name,
                provider=playbook_runtime.voice_provider or "elevenlabs",
                source="playbook" if playbook_runtime.voice_id else "env_default",
            )

        await self._memory.set_meta(call_id, meta)

        if playbook_runtime and not await self._has_qualification(call_id):
            qual = QualificationTracker.empty_from_playbook(playbook_runtime, fw)
            await self._memory.save_qualification(call_id, qual)

        await asyncio.to_thread(
            self._upsert_call_row,
            call_id=call_id,
            organization_id=organization_id,
            created_by=created_by,
            persona=meta["persona"],
            framework=fw.value,
            extra=extra_context,
            playbook_id=playbook_runtime.playbook_id if playbook_runtime else playbook_id,
            playbook_version=playbook_runtime.version if playbook_runtime else None,
        )

        snapshot = await self._memory.snapshot(call_id, framework=fw)
        log.info(
            "ai.call.started",
            call_id=call_id,
            persona=meta["persona"],
            framework=fw.value,
            playbook_id=str(playbook_runtime.playbook_id) if playbook_runtime else None,
        )
        log.info(
            "ai.CALL_STARTED_WITH_AGENT",
            call_id=call_id,
            playbook_id=(
                str(playbook_runtime.playbook_id) if playbook_runtime else None
            ),
            agent_name=agent_name or "AI Assistant",
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
        playbook_id: uuid.UUID | None = None,
        playbook_version: int | None = None,
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
                playbook_id=playbook_id,
                playbook_version=playbook_version,
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
        playbook = PlaybookRuntimeConfig.from_meta(meta)
        effective_persona = persona or meta.get("persona") or settings.AI_DEFAULT_PERSONA
        effective_framework = self._normalise_framework(
            framework or meta.get("framework")
        )
        merged_ctx = {**(meta.get("extra_context") or {}), **(extra_context or {})}
        if playbook and playbook.default_context:
            merged_ctx = {**playbook.default_context, **merged_ctx}

        # 1. Update qualification from the user turn _before_ the LLM call,
        qual = snapshot.qualification
        if playbook and not qual.field_configs:
            qual = QualificationTracker.empty_from_playbook(
                playbook, effective_framework
            )
        qual.framework = effective_framework
        newly_set = qual.ingest_user_turn(user_input)
        await self._memory.save_qualification(call_id, qual)

        effective_persona, merged_ctx, branch_out = await self._apply_playbook_branches(
            call_id=call_id,
            meta=meta,
            playbook=playbook,
            qual=qual,
            newly_set_fields=[f for f in newly_set if f != "__disqualified__"],
            effective_persona=effective_persona,
            merged_ctx=merged_ctx,
        )

        from modules.playbook.objections import (
            match_objection,
            objection_turn_instruction,
            parse_objections,
        )

        objection_rules = (
            parse_objections(playbook.objections) if playbook else []
        )
        obj_match = (
            match_objection(user_input, objection_rules)
            if objection_rules
            else None
        )
        if obj_match:
            snippet = user_input[:200]
            rule = obj_match.rule
            log.info(
                "ai.OBJECTION_DETECTED",
                call_id=call_id,
                objection_type=rule.objection_type,
                transcript_snippet=snippet,
            )
            log.info(
                "ai.OBJECTION_TYPE_MATCHED",
                call_id=call_id,
                objection_type=rule.objection_type,
                score=obj_match.score,
                strategy=obj_match.strategy,
                transcript_snippet=snippet,
            )
            instruction = objection_turn_instruction(obj_match)
            existing_block = merged_ctx.get("dynamic_block")
            merged_ctx["dynamic_block"] = (
                f"{existing_block}\n\n{instruction}"
                if existing_block
                else instruction
            )
            log.info(
                "ai.OBJECTION_RESPONSE_USED",
                call_id=call_id,
                objection_type=rule.objection_type,
                transcript_snippet=snippet,
            )

        if branch_out.end_call:
            reply_text = branch_out.end_call_message or (
                "Thanks for your time. Goodbye."
            )
            await self._memory.record_user_turn(call_id, user_input)
            await self._memory.record_assistant_turn(call_id, reply_text)
            if persist_transcript:
                await asyncio.to_thread(
                    self._persist_turn_rows,
                    call_id=call_id,
                    organization_id=organization_id,
                    user_text=user_input,
                    assistant_text=reply_text,
                    stats=ChatTurnStats(),
                )
            snapshot_after = qual.snapshot()
            return TurnResult(
                reply=reply_text,
                stats=ChatTurnStats(),
                qualification=snapshot_after,
                history_length=len(await self._memory.get_history(call_id)),
                branches_fired=branch_out.fired_branch_ids,
                branch_end_call=True,
                branch_end_call_message=branch_out.end_call_message,
            )

        # 2. Render system prompt + call OpenAI.
        system = render_system_prompt(
            persona=effective_persona,
            framework=effective_framework,
            extra_context=merged_ctx,
            playbook=playbook,
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
            branches_fired=branch_out.fired_branch_ids or None,
        )

    async def _apply_playbook_branches(
        self,
        *,
        call_id: str,
        meta: dict,
        playbook: PlaybookRuntimeConfig | None,
        qual: QualificationState,
        newly_set_fields: list[str],
        effective_persona: str,
        merged_ctx: dict,
    ):
        """Evaluate branch rules and persist persona/context updates to Redis."""

        from modules.playbook.branches import BranchEvaluationResult

        empty = BranchEvaluationResult()
        if not playbook or not playbook.branches:
            return effective_persona, merged_ctx, empty

        rules = parse_branch_rules(playbook.branches)
        fired_before = list(meta.get("branches_fired") or [])
        branch_out = evaluate_branches(
            rules,
            qual,
            newly_set_fields=newly_set_fields,
            branches_fired=fired_before,
        )
        if not branch_out.fired_branch_ids:
            return effective_persona, merged_ctx, branch_out

        if branch_out.switch_persona:
            effective_persona = branch_out.switch_persona
            meta["persona"] = effective_persona
        if branch_out.objective:
            merged_ctx["objective"] = branch_out.objective
            meta.setdefault("extra_context", {})
            meta["extra_context"]["objective"] = branch_out.objective
        if branch_out.merge_context:
            merged_ctx.update(branch_out.merge_context)
        if branch_out.dynamic_block:
            merged_ctx["dynamic_block"] = branch_out.dynamic_block

        meta["branches_fired"] = fired_before + branch_out.fired_branch_ids
        await self._memory.set_meta(call_id, meta)

        log.info(
            "ai.branches.fired",
            call_id=call_id,
            branches=branch_out.fired_branch_ids,
            persona=effective_persona,
        )
        return effective_persona, merged_ctx, branch_out

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
        playbook = PlaybookRuntimeConfig.from_meta(meta)
        effective_persona = persona or meta.get("persona") or settings.AI_DEFAULT_PERSONA
        effective_framework = self._normalise_framework(
            framework or meta.get("framework")
        )
        merged_ctx = {**(meta.get("extra_context") or {}), **(extra_context or {})}
        if playbook and playbook.default_context:
            merged_ctx = {**playbook.default_context, **merged_ctx}

        qual = snapshot.qualification
        if playbook and not qual.field_configs:
            qual = QualificationTracker.empty_from_playbook(
                playbook, effective_framework
            )
        qual.framework = effective_framework
        newly_set = qual.ingest_user_turn(user_input)
        await self._memory.save_qualification(call_id, qual)

        effective_persona, merged_ctx, branch_out = await self._apply_playbook_branches(
            call_id=call_id,
            meta=meta,
            playbook=playbook,
            qual=qual,
            newly_set_fields=[f for f in newly_set if f != "__disqualified__"],
            effective_persona=effective_persona,
            merged_ctx=merged_ctx,
        )

        system = render_system_prompt(
            persona=effective_persona,
            framework=effective_framework,
            extra_context=merged_ctx,
            playbook=playbook,
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
        meeting_status: str | None = None,
    ) -> dict:
        """Generate the LLM call summary, write everything to Postgres,
        and (optionally) drop the Redis keys.

        ``meeting_status`` is a PLACEHOLDER signal (``unknown`` /
        ``not_booked`` / ``booked``) recorded on the summary row and
        prepended to the summary text — no scheduling is performed here.
        """

        snapshot = await self._memory.snapshot(call_id)
        qual = snapshot.qualification

        # Fall back to the status stashed in Redis meta by the
        # orchestrator if the caller didn't pass one explicitly.
        if meeting_status is None:
            meeting_status = (snapshot.meta or {}).get("meeting_status")

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

        if meeting_status:
            prefix = f"[MEETING_STATUS] {meeting_status}"
            summary_text = (
                f"{prefix}\n{summary_text}" if summary_text else prefix
            )

        await asyncio.to_thread(
            self._persist_finalization,
            call_id=call_id,
            organization_id=organization_id,
            summary=summary_text,
            qual=qual,
            duration_ms=duration_ms,
            meeting_status=meeting_status,
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
            meeting_status=meeting_status,
        )
        return {
            "summary": summary_text,
            "qualification": qual.snapshot().model_dump(),
            "meeting_status": meeting_status,
        }

    def _persist_finalization(
        self,
        *,
        call_id: str,
        organization_id: uuid.UUID | None,
        summary: str | None,
        qual: QualificationState,
        duration_ms: int | None,
        meeting_status: str | None = None,
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
                extra=(
                    {"meeting_status": meeting_status}
                    if meeting_status
                    else None
                ),
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
        try:
            return QualificationFramework(framework)
        except ValueError:
            return QualificationFramework.CUSTOM

    @staticmethod
    def _load_playbook(
        *,
        organization_id: uuid.UUID,
        playbook_id: uuid.UUID,
    ) -> PlaybookRuntimeConfig:
        with _db_scope() as db:
            return PlaybookService.resolve_for_call(
                db,
                organization_id=organization_id,
                playbook_id=playbook_id,
            )

    async def _has_qualification(self, call_id: str) -> bool:
        return await self._memory.has_qualification(call_id)

    @staticmethod
    def _fallback_reply() -> str:
        """Said by the agent when the LLM returns an empty completion.

        Keeps a live call from going silent. The orchestrator can detect
        this exact string and decide whether to bail out of the loop.
        """

        return "Sorry, could you repeat that?"
