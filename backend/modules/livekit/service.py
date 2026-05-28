"""LiveKit server SDK wrapper.

This is the single place that talks to the LiveKit control plane. It is
fully async and treats the SDK client as a long-lived resource that is
created once per process and shared across requests.

Responsibilities
----------------
* Lifecycle: lazy construction and graceful shutdown of the underlying
  ``livekit.api.LiveKitAPI`` client.
* Rooms: create / list / get / delete.
* Tokens: mint short-lived JWTs with explicit ``VideoGrants``.
* Error translation: raw SDK errors are converted into module-specific
  exceptions so callers (router, transport) get a stable contract.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from livekit import api as lkapi

from common.logging import get_logger
from config.settings import settings
from modules.livekit.exceptions import (
    LiveKitConfigError,
    LiveKitError,
    RoomAlreadyExistsError,
    RoomNotFoundError,
    TokenGenerationError,
)
from modules.livekit.schema import (
    CreateRoomRequest,
    RoomResponse,
    TokenRequest,
    TokenResponse,
)

log = get_logger("livekit.service")


class LiveKitService:
    """Async wrapper around the LiveKit server SDK.

    Instances are intended to be created once per process (see
    ``dependencies.get_livekit_service``) and reused across requests.
    The underlying gRPC/HTTP client is lazily constructed on first use.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self._url = url or settings.LIVEKIT_URL
        self._api_key = api_key or settings.LIVEKIT_API_KEY
        self._api_secret = api_secret or settings.LIVEKIT_API_SECRET

        if not (self._url and self._api_key and self._api_secret):
            raise LiveKitConfigError(
                "LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set",
            )

        self._client: lkapi.LiveKitAPI | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    @property
    def url(self) -> str:
        return self._url

    async def _get_client(self) -> lkapi.LiveKitAPI:
        if self._client is not None:
            return self._client

        async with self._lock:
            if self._client is None:
                # The LiveKit server SDK accepts the HTTP(S) variant of the URL.
                http_url = self._url.replace("ws://", "http://").replace(
                    "wss://", "https://"
                )
                self._client = lkapi.LiveKitAPI(
                    url=http_url,
                    api_key=self._api_key,
                    api_secret=self._api_secret,
                )
                log.info("livekit.client.initialised", url=http_url)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # pragma: no cover - defensive
                log.exception("livekit.client.close_failed")
            finally:
                self._client = None
                log.info("livekit.client.closed")

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    async def create_room(self, data: CreateRoomRequest) -> RoomResponse:
        client = await self._get_client()

        req = lkapi.CreateRoomRequest(
            name=data.name,
            empty_timeout=(
                data.empty_timeout
                if data.empty_timeout is not None
                else settings.LIVEKIT_DEFAULT_EMPTY_TIMEOUT
            ),
            max_participants=(
                data.max_participants
                if data.max_participants is not None
                else settings.LIVEKIT_DEFAULT_MAX_PARTICIPANTS
            ),
            metadata=data.metadata or "",
        )

        try:
            room = await client.room.create_room(req)
        except Exception as exc:  # SDK exposes TwirpError + others
            message = str(exc).lower()
            if "already" in message and "exists" in message:
                log.warning("livekit.room.exists", name=data.name)
                raise RoomAlreadyExistsError(
                    f"Room '{data.name}' already exists"
                ) from exc
            log.exception("livekit.room.create_failed", name=data.name)
            raise LiveKitError(f"failed to create room: {exc}") from exc

        log.info("livekit.room.created", name=room.name, sid=room.sid)
        return _room_to_response(room)

    async def list_rooms(self, names: list[str] | None = None) -> list[RoomResponse]:
        client = await self._get_client()
        req = lkapi.ListRoomsRequest(names=names or [])
        try:
            resp = await client.room.list_rooms(req)
        except Exception as exc:
            log.exception("livekit.room.list_failed")
            raise LiveKitError(f"failed to list rooms: {exc}") from exc
        return [_room_to_response(r) for r in resp.rooms]

    async def get_room(self, name: str) -> RoomResponse:
        rooms = await self.list_rooms(names=[name])
        if not rooms:
            raise RoomNotFoundError(f"Room '{name}' not found")
        return rooms[0]

    async def delete_room(self, name: str) -> None:
        client = await self._get_client()
        try:
            await client.room.delete_room(lkapi.DeleteRoomRequest(room=name))
        except Exception as exc:
            message = str(exc).lower()
            if "not found" in message or "does not exist" in message:
                raise RoomNotFoundError(f"Room '{name}' not found") from exc
            log.exception("livekit.room.delete_failed", name=name)
            raise LiveKitError(f"failed to delete room: {exc}") from exc
        log.info("livekit.room.deleted", name=name)

    # ------------------------------------------------------------------
    # Tokens
    # ------------------------------------------------------------------

    def generate_token(self, data: TokenRequest) -> TokenResponse:
        """Mint a JWT for a participant to join a specific room.

        This is synchronous because token signing is CPU-only.
        """

        try:
            ttl_minutes = data.ttl_minutes or settings.LIVEKIT_TOKEN_TTL_MINUTES
            ttl = timedelta(minutes=ttl_minutes)
            expires_at = datetime.now(timezone.utc) + ttl

            grants = lkapi.VideoGrants(
                room_join=True,
                room=data.room,
                can_publish=data.can_publish,
                can_subscribe=data.can_subscribe,
                can_publish_data=data.can_publish_data,
            )

            token = (
                lkapi.AccessToken(self._api_key, self._api_secret)
                .with_identity(data.identity)
                .with_name(data.name or data.identity)
                .with_grants(grants)
                .with_ttl(ttl)
            )
            if data.metadata:
                token = token.with_metadata(data.metadata)

            jwt = token.to_jwt()
        except Exception as exc:
            log.exception(
                "livekit.token.failed",
                room=data.room,
                identity=data.identity,
            )
            raise TokenGenerationError(f"failed to generate token: {exc}") from exc

        log.info(
            "livekit.token.minted",
            room=data.room,
            identity=data.identity,
            ttl_minutes=ttl_minutes,
        )
        return TokenResponse(
            token=jwt,
            url=self._url,
            room=data.room,
            identity=data.identity,
            expires_at=expires_at,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _room_to_response(room) -> RoomResponse:
    return RoomResponse(
        sid=getattr(room, "sid", None) or None,
        name=room.name,
        empty_timeout=int(getattr(room, "empty_timeout", 0) or 0),
        max_participants=int(getattr(room, "max_participants", 0) or 0),
        creation_time=int(getattr(room, "creation_time", 0) or 0) or None,
        num_participants=int(getattr(room, "num_participants", 0) or 0),
        metadata=getattr(room, "metadata", None) or None,
    )


@asynccontextmanager
async def livekit_service_scope() -> AsyncIterator[LiveKitService]:
    """Convenience scope for scripts / workers that need a one-shot service."""

    svc = LiveKitService()
    try:
        yield svc
    finally:
        await svc.aclose()
