"""Data-access layer for LiveKit sessions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from modules.livekit.model import LiveKitSession


class LiveKitSessionRepository:
    @staticmethod
    def create(db: Session, session: LiveKitSession) -> LiveKitSession:
        db.add(session)
        db.flush()
        return session

    @staticmethod
    def get_by_room(db: Session, room_name: str) -> LiveKitSession | None:
        return (
            db.query(LiveKitSession)
            .filter(LiveKitSession.room_name == room_name)
            .one_or_none()
        )

    @staticmethod
    def mark_status(
        db: Session,
        session: LiveKitSession,
        status: str,
        *,
        livekit_sid: str | None = None,
    ) -> LiveKitSession:
        session.status = status
        if livekit_sid is not None:
            session.livekit_sid = livekit_sid
        db.flush()
        return session

    @staticmethod
    def delete(db: Session, session: LiveKitSession) -> None:
        db.delete(session)
        db.flush()
