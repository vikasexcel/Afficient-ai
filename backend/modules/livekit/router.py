"""HTTP API for LiveKit rooms and tokens."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from common.logging import get_logger
from common.security.authorization import requires
from common.security.roles import Role
from database.dependencies import get_db
from modules.livekit.dependencies import get_livekit_service
from modules.livekit.exceptions import LiveKitError
from modules.livekit.model import LiveKitSession
from modules.livekit.repository import LiveKitSessionRepository
from modules.livekit.schema import (
    CreateRoomRequest,
    DeleteRoomResponse,
    RoomListResponse,
    RoomResponse,
    SessionResponse,
    TokenRequest,
    TokenResponse,
)
from modules.livekit.service import LiveKitService

log = get_logger("livekit.router")

router = APIRouter(
    prefix="/livekit",
    tags=["livekit"],
)


def _to_http(exc: LiveKitError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------


@router.post("/rooms", response_model=RoomResponse, status_code=201)
async def create_room(
    data: CreateRoomRequest,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: LiveKitService = Depends(get_livekit_service),
):
    try:
        room = await svc.create_room(data)
    except LiveKitError as exc:
        raise _to_http(exc) from exc

    existing = LiveKitSessionRepository.get_by_room(db, room.name)
    if existing is None:
        session = LiveKitSession(
            organization_id=tenant["organization_id"],
            created_by=tenant["user_id"],
            room_name=room.name,
            livekit_sid=room.sid,
            status="active",
            extra={"metadata": data.metadata} if data.metadata else None,
        )
        LiveKitSessionRepository.create(db, session)
    else:
        LiveKitSessionRepository.mark_status(
            db, existing, status="active", livekit_sid=room.sid,
        )
    db.commit()

    return room


@router.get("/rooms", response_model=RoomListResponse)
async def list_rooms(
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: LiveKitService = Depends(get_livekit_service),
):
    try:
        rooms = await svc.list_rooms()
    except LiveKitError as exc:
        raise _to_http(exc) from exc
    return RoomListResponse(rooms=rooms)


@router.get("/rooms/{name}", response_model=RoomResponse)
async def get_room(
    name: str,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
    svc: LiveKitService = Depends(get_livekit_service),
):
    try:
        return await svc.get_room(name)
    except LiveKitError as exc:
        raise _to_http(exc) from exc


@router.delete("/rooms/{name}", response_model=DeleteRoomResponse)
async def delete_room(
    name: str,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN)),
    svc: LiveKitService = Depends(get_livekit_service),
):
    try:
        await svc.delete_room(name)
    except LiveKitError as exc:
        raise _to_http(exc) from exc

    session = LiveKitSessionRepository.get_by_room(db, name)
    if session is not None:
        LiveKitSessionRepository.mark_status(db, session, status="deleted")
        db.commit()

    return DeleteRoomResponse(name=name, deleted=True)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


@router.post("/tokens", response_model=TokenResponse)
async def issue_token(
    data: TokenRequest,
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT, Role.MEMBER)),
    svc: LiveKitService = Depends(get_livekit_service),
):
    try:
        return svc.generate_token(data)
    except LiveKitError as exc:
        raise _to_http(exc) from exc


# ---------------------------------------------------------------------------
# Sessions (local view)
# ---------------------------------------------------------------------------


@router.get("/sessions/{room_name}", response_model=SessionResponse)
async def get_session(
    room_name: str,
    db: Session = Depends(get_db),
    tenant=Depends(requires(Role.OWNER, Role.ADMIN, Role.AGENT)),
):
    session = LiveKitSessionRepository.get_by_room(db, room_name)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionResponse(
        id=str(session.id),
        room_name=session.room_name,
        livekit_sid=session.livekit_sid,
        status=session.status,
        created_by=str(session.created_by) if session.created_by else None,
        metadata=session.extra,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
