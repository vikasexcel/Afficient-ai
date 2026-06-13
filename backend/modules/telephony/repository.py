"""Data-access layer for ``telephony_calls`` + ``telephony_events``.

Sync SQLAlchemy ``Session`` interface — async callers wrap inserts in
``asyncio.to_thread`` to keep the asyncio loop unblocked. Mirrors the
pattern used by :mod:`modules.ai.repository`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import desc
from sqlalchemy.orm import Session

from modules.telephony.model import (
    CALL_STATUS_QUEUED,
    TelephonyCall,
    TelephonyEvent,
)


class TelephonyCallRepository:
    """CRUD for the ``telephony_calls`` table."""

    @staticmethod
    def create(
        db: Session,
        *,
        organization_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
        room_name: str,
        from_number: str,
        to_number: str,
        direction: str = "outbound",
        lead_id: uuid.UUID | None = None,
        lead_name: str | None = None,
        lead_phone: str | None = None,
        campaign_id: uuid.UUID | None = None,
        playbook_id: uuid.UUID | None = None,
        extra: dict[str, Any] | None = None,
        parent_call_id: uuid.UUID | None = None,
        retry_count: int = 0,
    ) -> TelephonyCall:
        row = TelephonyCall(
            organization_id=organization_id,
            created_by=created_by,
            room_name=room_name,
            direction=direction,
            status=CALL_STATUS_QUEUED,
            from_number=from_number,
            to_number=to_number,
            lead_id=lead_id,
            lead_name=lead_name,
            lead_phone=lead_phone,
            campaign_id=campaign_id,
            playbook_id=playbook_id,
            extra=extra,
            parent_call_id=parent_call_id,
            retry_count=retry_count,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def get(db: Session, call_id: uuid.UUID) -> TelephonyCall | None:
        return (
            db.query(TelephonyCall)
            .filter(TelephonyCall.id == call_id)
            .one_or_none()
        )

    @staticmethod
    def get_by_sid(db: Session, call_sid: str) -> TelephonyCall | None:
        return (
            db.query(TelephonyCall)
            .filter(TelephonyCall.call_sid == call_sid)
            .one_or_none()
        )

    @staticmethod
    def get_by_room(db: Session, room_name: str) -> TelephonyCall | None:
        return (
            db.query(TelephonyCall)
            .filter(TelephonyCall.room_name == room_name)
            .one_or_none()
        )

    @staticmethod
    def set_sid(
        db: Session, row: TelephonyCall, call_sid: str
    ) -> TelephonyCall:
        row.call_sid = call_sid
        db.flush()
        return row

    @staticmethod
    def update_status(
        db: Session,
        row: TelephonyCall,
        *,
        status: str,
        initiated_at: datetime | None = None,
        ringing_at: datetime | None = None,
        answered_at: datetime | None = None,
        ended_at: datetime | None = None,
        duration_seconds: int | None = None,
        price: float | None = None,
        price_unit: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        extra_merge: dict[str, Any] | None = None,
    ) -> TelephonyCall:
        row.status = status
        if initiated_at is not None and row.initiated_at is None:
            row.initiated_at = initiated_at
        if ringing_at is not None and row.ringing_at is None:
            row.ringing_at = ringing_at
        if answered_at is not None and row.answered_at is None:
            row.answered_at = answered_at
        if ended_at is not None:
            row.ended_at = ended_at
        if duration_seconds is not None:
            row.duration_seconds = duration_seconds
        if price is not None:
            row.price = price
        if price_unit is not None:
            row.price_unit = price_unit
        if error_code is not None:
            row.error_code = error_code
        if error_message is not None:
            row.error_message = error_message
        if extra_merge:
            merged = dict(row.extra or {})
            merged.update(extra_merge)
            row.extra = merged
        db.flush()
        return row

    @staticmethod
    def update_amd(
        db: Session,
        row: TelephonyCall,
        *,
        amd_result: str | None = None,
        amd_confidence: float | None = None,
        voicemail_detected_at: datetime | None = None,
        voicemail_dropped: bool | None = None,
        voicemail_dropped_at: datetime | None = None,
        voicemail_recording_url: str | None = None,
    ) -> TelephonyCall:
        """Patch AMD / voicemail-drop columns on a call row.

        Each field is applied only when provided so repeated webhooks (e.g. a
        late status callback after the voice webhook already dropped a
        voicemail) never clobber earlier state.
        """

        if amd_result is not None:
            row.amd_result = amd_result
        if amd_confidence is not None:
            row.amd_confidence = amd_confidence
        if voicemail_detected_at is not None and row.voicemail_detected_at is None:
            row.voicemail_detected_at = voicemail_detected_at
        if voicemail_dropped is not None:
            row.voicemail_dropped = voicemail_dropped
        if voicemail_dropped_at is not None and row.voicemail_dropped_at is None:
            row.voicemail_dropped_at = voicemail_dropped_at
        if voicemail_recording_url is not None:
            row.voicemail_recording_url = voicemail_recording_url
        db.flush()
        return row

    @staticmethod
    def voicemail_metrics(db: Session, campaign_id: uuid.UUID) -> dict:
        """Aggregate AMD / voicemail-drop counters for one campaign.

        Sourced from ``telephony_calls`` (the canonical call record). A
        "voicemail retry" is a child call (``parent_call_id`` set) whose parent
        was classified as voicemail.
        """

        from sqlalchemy import func, select
        from sqlalchemy.orm import aliased

        human = int(
            db.execute(
                select(func.count())
                .select_from(TelephonyCall)
                .where(
                    TelephonyCall.campaign_id == campaign_id,
                    TelephonyCall.amd_result == "human",
                )
            ).scalar_one()
        )
        detected = int(
            db.execute(
                select(func.count())
                .select_from(TelephonyCall)
                .where(
                    TelephonyCall.campaign_id == campaign_id,
                    TelephonyCall.amd_result == "voicemail",
                )
            ).scalar_one()
        )
        dropped = int(
            db.execute(
                select(func.count())
                .select_from(TelephonyCall)
                .where(
                    TelephonyCall.campaign_id == campaign_id,
                    TelephonyCall.voicemail_dropped.is_(True),
                )
            ).scalar_one()
        )

        parent = aliased(TelephonyCall)
        retry_count = int(
            db.execute(
                select(func.count())
                .select_from(TelephonyCall)
                .join(parent, TelephonyCall.parent_call_id == parent.id)
                .where(
                    TelephonyCall.campaign_id == campaign_id,
                    parent.amd_result == "voicemail",
                )
            ).scalar_one()
        )

        success_rate = round(dropped / detected, 3) if detected else 0.0
        return {
            "human_answered": human,
            "voicemail_detected": detected,
            "voicemail_dropped": dropped,
            "voicemail_retry_count": retry_count,
            "voicemail_success_rate": success_rate,
        }

    @staticmethod
    def update_recording(
        db: Session,
        row: TelephonyCall,
        *,
        recording_sid: str,
        recording_url: str,
        recording_duration_seconds: int | None = None,
        recording_uploaded_at: datetime | None = None,
    ) -> TelephonyCall:
        """Persist S3 recording metadata on the call row."""
        row.recording_sid = recording_sid
        row.recording_url = recording_url
        if recording_duration_seconds is not None:
            row.recording_duration_seconds = recording_duration_seconds
        row.recording_uploaded_at = recording_uploaded_at or datetime.utcnow()
        db.flush()
        return row

    @staticmethod
    def delete(db: Session, row: TelephonyCall) -> None:
        """Delete a call row and its associated audit events.

        ``telephony_events`` and the self-referential ``parent_call_id``
        both point back at this row, so we clear those references first to
        avoid FK violations:

        * Events are part of this call's history → deleted with it.
        * Retry children point at this row via ``parent_call_id`` → we null
          the link so the children survive as standalone records.
        """

        db.query(TelephonyEvent).filter(
            TelephonyEvent.telephony_call_id == row.id
        ).delete(synchronize_session=False)

        db.query(TelephonyCall).filter(
            TelephonyCall.parent_call_id == row.id
        ).update(
            {TelephonyCall.parent_call_id: None},
            synchronize_session=False,
        )

        db.delete(row)
        db.flush()

    @staticmethod
    def list_recent(
        db: Session,
        *,
        organization_id: uuid.UUID | None,
        limit: int = 50,
        status: str | None = None,
        answered_by: str | None = None,
    ) -> Sequence[TelephonyCall]:
        q = db.query(TelephonyCall)
        if organization_id is not None:
            q = q.filter(TelephonyCall.organization_id == organization_id)
        if status:
            q = q.filter(TelephonyCall.status == status)
        if answered_by:
            q = q.filter(TelephonyCall.amd_result == answered_by.strip().lower())
        return (
            q.order_by(desc(TelephonyCall.created_at))
            .limit(max(1, min(limit, 200)))
            .all()
        )


class TelephonyEventRepository:
    """Append-only writes to ``telephony_events``."""

    @staticmethod
    def append(
        db: Session,
        *,
        event_type: str,
        organization_id: uuid.UUID | None = None,
        call_sid: str | None = None,
        telephony_call_id: uuid.UUID | None = None,
        source: str = "twilio",
        payload: dict[str, Any] | None = None,
    ) -> TelephonyEvent:
        row = TelephonyEvent(
            organization_id=organization_id,
            call_sid=call_sid,
            telephony_call_id=telephony_call_id,
            event_type=event_type,
            source=source,
            payload=payload,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def list_for_sid(
        db: Session, call_sid: str
    ) -> Sequence[TelephonyEvent]:
        return (
            db.query(TelephonyEvent)
            .filter(TelephonyEvent.call_sid == call_sid)
            .order_by(TelephonyEvent.created_at.asc())
            .all()
        )

    @staticmethod
    def list_for_call(
        db: Session, telephony_call_id: uuid.UUID
    ) -> Sequence[TelephonyEvent]:
        return (
            db.query(TelephonyEvent)
            .filter(TelephonyEvent.telephony_call_id == telephony_call_id)
            .order_by(TelephonyEvent.created_at.asc())
            .all()
        )
