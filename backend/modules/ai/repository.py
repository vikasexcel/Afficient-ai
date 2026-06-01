"""Data-access layer for AI calls, transcripts and summaries.

The repository deliberately keeps a synchronous SQLAlchemy ``Session``
interface (matches the rest of the codebase). Async callers wrap the
inserts in ``asyncio.to_thread`` from the orchestrator so the LiveKit
event loop is never blocked.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.ai.model import AICall, AICallSummary, AITranscriptEntry


class AICallRepository:
    """CRUD for the ``ai_calls`` table."""

    @staticmethod
    def upsert_active(
        db: Session,
        *,
        call_id: str,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
        persona: str | None,
        framework: str | None,
        extra: dict[str, Any] | None = None,
        playbook_id: uuid.UUID | None = None,
        playbook_version: int | None = None,
    ) -> AICall:
        row = (
            db.query(AICall).filter(AICall.call_id == call_id).one_or_none()
        )
        if row is None:
            row = AICall(
                call_id=call_id,
                organization_id=organization_id,
                created_by=created_by,
                persona=persona,
                framework=framework,
                playbook_id=playbook_id,
                playbook_version=playbook_version,
                status="active",
                extra=extra,
            )
            db.add(row)
            db.flush()
            return row
        row.persona = persona or row.persona
        row.framework = framework or row.framework
        if playbook_id is not None:
            row.playbook_id = playbook_id
        if playbook_version is not None:
            row.playbook_version = playbook_version
        if extra is not None:
            merged = dict(row.extra or {})
            merged.update(extra)
            row.extra = merged
        db.flush()
        return row

    @staticmethod
    def get(db: Session, call_id: str) -> AICall | None:
        return (
            db.query(AICall).filter(AICall.call_id == call_id).one_or_none()
        )

    @staticmethod
    def list_recent(
        db: Session,
        *,
        organization_id: uuid.UUID | None,
        limit: int = 50,
    ) -> Sequence[AICall]:
        q = db.query(AICall)
        if organization_id is not None:
            q = q.filter(AICall.organization_id == organization_id)
        return (
            q.order_by(AICall.updated_at.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )

    @staticmethod
    def mark_status(db: Session, call_id: str, status: str) -> AICall | None:
        row = AICallRepository.get(db, call_id)
        if row is None:
            return None
        row.status = status
        db.flush()
        return row


class AITranscriptRepository:
    """Append-only writes to ``ai_transcript_entries``."""

    @staticmethod
    def next_turn_index(db: Session, call_id: str) -> int:
        stmt = select(func.coalesce(func.max(AITranscriptEntry.turn_index), -1)).where(
            AITranscriptEntry.call_id == call_id
        )
        return int(db.execute(stmt).scalar_one()) + 1

    @staticmethod
    def append(
        db: Session,
        *,
        call_id: str,
        organization_id: uuid.UUID | None,
        role: str,
        content: str,
        model: str | None = None,
        latency_ms: int | None = None,
        ttft_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        finish_reason: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AITranscriptEntry:
        idx = AITranscriptRepository.next_turn_index(db, call_id)
        row = AITranscriptEntry(
            call_id=call_id,
            organization_id=organization_id,
            turn_index=idx,
            role=role,
            content=content,
            model=model,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
            extra=extra,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def list_for_call(
        db: Session, call_id: str
    ) -> Sequence[AITranscriptEntry]:
        return (
            db.query(AITranscriptEntry)
            .filter(AITranscriptEntry.call_id == call_id)
            .order_by(AITranscriptEntry.turn_index.asc())
            .all()
        )

    @staticmethod
    def aggregate(db: Session, call_id: str) -> dict[str, int]:
        """Sum token counts + count turns for a call."""

        stmt = select(
            func.count(AITranscriptEntry.id),
            func.coalesce(func.sum(AITranscriptEntry.prompt_tokens), 0),
            func.coalesce(func.sum(AITranscriptEntry.completion_tokens), 0),
            func.coalesce(func.sum(AITranscriptEntry.total_tokens), 0),
        ).where(AITranscriptEntry.call_id == call_id)
        turns, prompt, completion, total = db.execute(stmt).one()
        return {
            "total_turns": int(turns or 0),
            "total_prompt_tokens": int(prompt or 0),
            "total_completion_tokens": int(completion or 0),
            "total_tokens": int(total or 0),
        }


class AICallSummaryRepository:
    """Upserts to ``ai_call_summaries``."""

    @staticmethod
    def upsert(
        db: Session,
        *,
        call_id: str,
        organization_id: uuid.UUID | None,
        summary: str | None,
        qualification: dict[str, Any] | None,
        qualification_status: str | None,
        qualification_score: int | None,
        totals: dict[str, int],
        duration_ms: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> AICallSummary:
        row = (
            db.query(AICallSummary)
            .filter(AICallSummary.call_id == call_id)
            .one_or_none()
        )
        if row is None:
            row = AICallSummary(
                call_id=call_id,
                organization_id=organization_id,
                summary=summary,
                qualification=qualification,
                qualification_status=qualification_status,
                qualification_score=qualification_score,
                total_turns=totals.get("total_turns", 0),
                total_prompt_tokens=totals.get("total_prompt_tokens", 0),
                total_completion_tokens=totals.get("total_completion_tokens", 0),
                total_tokens=totals.get("total_tokens", 0),
                duration_ms=duration_ms,
                extra=extra,
            )
            db.add(row)
            db.flush()
            return row

        row.summary = summary if summary is not None else row.summary
        row.qualification = qualification if qualification is not None else row.qualification
        row.qualification_status = qualification_status or row.qualification_status
        row.qualification_score = (
            qualification_score if qualification_score is not None else row.qualification_score
        )
        row.total_turns = totals.get("total_turns", row.total_turns)
        row.total_prompt_tokens = totals.get(
            "total_prompt_tokens", row.total_prompt_tokens
        )
        row.total_completion_tokens = totals.get(
            "total_completion_tokens", row.total_completion_tokens
        )
        row.total_tokens = totals.get("total_tokens", row.total_tokens)
        if duration_ms is not None:
            row.duration_ms = duration_ms
        if extra is not None:
            merged = dict(row.extra or {})
            merged.update(extra)
            row.extra = merged
        db.flush()
        return row

    @staticmethod
    def get(db: Session, call_id: str) -> AICallSummary | None:
        return (
            db.query(AICallSummary)
            .filter(AICallSummary.call_id == call_id)
            .one_or_none()
        )

    @staticmethod
    def map_for_call_ids(
        db: Session, call_ids: Sequence[str]
    ) -> dict[str, AICallSummary]:
        """Bulk-fetch summaries for a batch of call ids (avoids N+1)."""

        if not call_ids:
            return {}
        rows = (
            db.query(AICallSummary)
            .filter(AICallSummary.call_id.in_(list(call_ids)))
            .all()
        )
        return {r.call_id: r for r in rows}
