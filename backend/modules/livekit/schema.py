"""Pydantic request / response schemas for the LiveKit module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------


class CreateRoomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    empty_timeout: int | None = Field(
        default=None,
        ge=0,
        description="Seconds before an empty room is closed.",
    )
    max_participants: int | None = Field(
        default=None,
        ge=1,
        le=1000,
    )
    metadata: str | None = Field(default=None, max_length=8192)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class RoomResponse(BaseModel):
    sid: str | None = None
    name: str
    empty_timeout: int
    max_participants: int
    creation_time: int | None = None
    num_participants: int = 0
    metadata: str | None = None


class RoomListResponse(BaseModel):
    rooms: list[RoomResponse]


class DeleteRoomResponse(BaseModel):
    name: str
    deleted: bool = True


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


class TokenRequest(BaseModel):
    room: str = Field(min_length=1, max_length=128)
    identity: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=128)
    metadata: str | None = Field(default=None, max_length=8192)
    ttl_minutes: int | None = Field(default=None, ge=1, le=60 * 24)
    can_publish: bool = True
    can_subscribe: bool = True
    can_publish_data: bool = True


class TokenResponse(BaseModel):
    token: str
    url: str
    room: str
    identity: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# Session tracking
# ---------------------------------------------------------------------------


class SessionResponse(BaseModel):
    id: str
    room_name: str
    livekit_sid: str | None = None
    status: str
    created_by: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
