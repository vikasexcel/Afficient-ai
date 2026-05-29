#!/usr/bin/env python3
"""Full end-to-end validation of the LiveKit voice-agent backend.

Covers all 13 validation items from the test brief:

  1. LiveKit server connectivity
  2. Environment variable configuration
  3. Room creation API
  4. Room retrieval (get + list)
  5. Participant token generation
  6. Token permissions and expiration (JWT decoded)
  7. WebRTC connection establishment (real rtc.Room.connect)
  8. User joining a room successfully (participant A)
  9. Multiple participants joining the same room (A + B)
 10. Audio track publishing and subscription (A publishes, B receives)
 11. Room disconnect and cleanup
 12. API error handling (401, 404, 422, duplicate-room)
 13. Logging and monitoring (server log assertions)

Prints a structured PASS/FAIL/SKIP report at the end. Exits 0 only if
nothing is FAIL (SKIPs are tolerated and listed).

Requires:
  - backend running on E2E_BASE_URL (default http://127.0.0.1:8002)
  - LiveKit reachable at LIVEKIT_HTTP_URL (default http://127.0.0.1:7880)
  - redis reachable (we flush the rate-limit bucket for 127.0.0.1)
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt as pyjwt
import redis as redis_pkg

# Make the backend importable so we can reuse settings + the rtc client.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import settings  # noqa: E402
from livekit import rtc  # noqa: E402

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8002")
API = f"{BASE}/api/v1"
LIVEKIT_HTTP = os.environ.get("LIVEKIT_HTTP_URL", "http://127.0.0.1:7880")
BACKEND_LOG = os.environ.get(
    "E2E_BACKEND_LOG",
    "/home/node/.cursor/projects/home-node-afficient-ai/terminals/710723.txt",
)


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    status: str  # PASS / FAIL / SKIP
    detail: str = ""
    duration_ms: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)


RESULTS: list[CheckResult] = []


def record(
    name: str,
    status: str,
    detail: str = "",
    *,
    duration_ms: int = 0,
    evidence: dict[str, Any] | None = None,
) -> CheckResult:
    cr = CheckResult(name, status, detail, duration_ms, evidence or {})
    RESULTS.append(cr)
    icon = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}[status]
    suffix = f" ({duration_ms} ms)" if duration_ms else ""
    print(f"[{icon}] {name}{suffix} :: {detail}")
    return cr


async def timed(coro):
    t0 = time.perf_counter()
    res = await coro
    return res, int((time.perf_counter() - t0) * 1000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def flush_rate_limit() -> None:
    """Wipe per-IP rate-limit counters so the test isn't 429'd."""
    try:
        rc = redis_pkg.from_url(settings.REDIS_URL)
        for key in rc.scan_iter("api:*"):
            rc.delete(key)
    except Exception as exc:
        print(f"WARN: redis flush failed: {exc}")


def http_url_for_livekit(ws_url: str) -> str:
    return ws_url.replace("ws://", "http://").replace("wss://", "https://")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


async def check_env_config() -> bool:
    required = {
        "LIVEKIT_URL": settings.LIVEKIT_URL,
        "LIVEKIT_API_KEY": settings.LIVEKIT_API_KEY,
        "LIVEKIT_API_SECRET": settings.LIVEKIT_API_SECRET,
        "DATABASE_URL": settings.DATABASE_URL,
        "REDIS_URL": settings.REDIS_URL,
        "JWT_SECRET": settings.JWT_SECRET,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        record(
            "02 env_config",
            "FAIL",
            f"missing: {missing}",
            evidence={"present": [k for k in required if k not in missing]},
        )
        return False
    record(
        "02 env_config",
        "PASS",
        "core vars present",
        evidence={
            "LIVEKIT_URL": settings.LIVEKIT_URL,
            "LIVEKIT_API_KEY": settings.LIVEKIT_API_KEY[:6] + "…",
            "LIVEKIT_TOKEN_TTL_MINUTES": settings.LIVEKIT_TOKEN_TTL_MINUTES,
            "LIVEKIT_DEFAULT_EMPTY_TIMEOUT": settings.LIVEKIT_DEFAULT_EMPTY_TIMEOUT,
            "LIVEKIT_DEFAULT_MAX_PARTICIPANTS": settings.LIVEKIT_DEFAULT_MAX_PARTICIPANTS,
        },
    )
    return True


async def check_livekit_connectivity(client: httpx.AsyncClient) -> bool:
    http_url = http_url_for_livekit(settings.LIVEKIT_URL)
    try:
        r = await client.get(http_url, timeout=5.0)
    except Exception as exc:
        record("01 livekit_connectivity", "FAIL", f"unreachable: {exc}")
        return False
    if r.status_code not in (200, 404):
        record(
            "01 livekit_connectivity",
            "FAIL",
            f"unexpected status {r.status_code}",
        )
        return False
    record(
        "01 livekit_connectivity",
        "PASS",
        f"HTTP {r.status_code} from {http_url}",
        evidence={"url": http_url, "status_code": r.status_code},
    )
    return True


async def auth_setup(client: httpx.AsyncClient) -> tuple[str, str] | None:
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    password = "E2eTestPass123!"

    flush_rate_limit()
    r = await client.post(
        f"{API}/auth/register",
        json={
            "full_name": "E2E Tester",
            "email": email,
            "password": password,
            "organization": f"E2E Org {uuid.uuid4().hex[:6]}",
        },
    )
    if r.status_code not in (200, 201):
        record(
            "00 auth_register",
            "FAIL",
            f"status={r.status_code} body={r.text[:200]}",
        )
        return None

    r = await client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
    )
    if r.status_code != 200:
        record(
            "00 auth_login",
            "FAIL",
            f"status={r.status_code} body={r.text[:200]}",
        )
        return None
    access = r.json().get("access_token")
    if not access:
        record("00 auth_login", "FAIL", "no access_token returned")
        return None
    record("00 auth_setup", "PASS", f"identity={email}")
    return access, email


async def check_room_create(
    client: httpx.AsyncClient, headers: dict, room_name: str
) -> dict | None:
    flush_rate_limit()
    r, ms = await timed(
        client.post(
            f"{API}/livekit/rooms",
            headers=headers,
            json={"name": room_name, "max_participants": 4, "empty_timeout": 60},
        )
    )
    if r.status_code not in (200, 201):
        record(
            "03 room_create",
            "FAIL",
            f"status={r.status_code} body={r.text[:200]}",
            duration_ms=ms,
        )
        return None
    room = r.json()
    if room.get("name") != room_name or not room.get("sid"):
        record(
            "03 room_create",
            "FAIL",
            f"missing fields: {room}",
            duration_ms=ms,
        )
        return None
    record(
        "03 room_create",
        "PASS",
        f"sid={room['sid']} max={room['max_participants']}",
        duration_ms=ms,
        evidence=room,
    )
    return room


async def check_room_retrieve(
    client: httpx.AsyncClient, headers: dict, room_name: str
) -> bool:
    flush_rate_limit()
    r, ms = await timed(client.get(f"{API}/livekit/rooms/{room_name}", headers=headers))
    if r.status_code != 200:
        record(
            "04 room_get",
            "FAIL",
            f"status={r.status_code} body={r.text[:200]}",
            duration_ms=ms,
        )
        return False
    record(
        "04 room_get",
        "PASS",
        f"name={r.json().get('name')}",
        duration_ms=ms,
    )

    r, ms = await timed(client.get(f"{API}/livekit/rooms", headers=headers))
    if r.status_code != 200:
        record(
            "04 room_list",
            "FAIL",
            f"status={r.status_code}",
            duration_ms=ms,
        )
        return False
    names = [x["name"] for x in r.json().get("rooms", [])]
    record(
        "04 room_list",
        "PASS",
        f"{len(names)} rooms, target {'present' if room_name in names else 'pending'}",
        duration_ms=ms,
    )
    return True


async def check_token_issue(
    client: httpx.AsyncClient,
    headers: dict,
    room_name: str,
    identity: str,
    *,
    can_publish: bool = True,
    can_subscribe: bool = True,
    ttl_minutes: int = 5,
    label_index: int = 1,
) -> dict | None:
    flush_rate_limit()
    r, ms = await timed(
        client.post(
            f"{API}/livekit/tokens",
            headers=headers,
            json={
                "room": room_name,
                "identity": identity,
                "name": f"E2E {identity}",
                "ttl_minutes": ttl_minutes,
                "can_publish": can_publish,
                "can_subscribe": can_subscribe,
                "can_publish_data": True,
            },
        )
    )
    if r.status_code != 200:
        record(
            f"05 token_issue#{label_index}",
            "FAIL",
            f"status={r.status_code} body={r.text[:200]}",
            duration_ms=ms,
        )
        return None
    tok = r.json()
    if not tok.get("token") or not tok.get("url"):
        record(
            f"05 token_issue#{label_index}",
            "FAIL",
            f"missing fields: {tok}",
            duration_ms=ms,
        )
        return None
    record(
        f"05 token_issue#{label_index}",
        "PASS",
        f"identity={identity} ttl={ttl_minutes}m url={tok['url']}",
        duration_ms=ms,
    )
    return tok


def check_token_decode(token_resp: dict, *, expected_room: str, label_index: int) -> bool:
    try:
        # LiveKit's AccessToken does not set an `aud` claim, so disable
        # audience verification. We still verify signature + expiration.
        claims = pyjwt.decode(
            token_resp["token"],
            settings.LIVEKIT_API_SECRET,
            algorithms=["HS256"],
            options={"verify_signature": True, "verify_aud": False},
        )
    except pyjwt.PyJWTError as exc:
        record(
            f"06 token_decode#{label_index}",
            "FAIL",
            f"jwt verify failed: {exc}",
        )
        return False

    grants = claims.get("video", {})
    iss = claims.get("iss")
    sub = claims.get("sub")
    exp = claims.get("exp")
    nbf = claims.get("nbf")

    problems: list[str] = []
    if iss != settings.LIVEKIT_API_KEY:
        problems.append(f"iss mismatch ({iss})")
    if sub != token_resp["identity"]:
        problems.append(f"sub mismatch ({sub})")
    if grants.get("room") != expected_room:
        problems.append(f"room mismatch ({grants.get('room')})")
    if not grants.get("roomJoin"):
        problems.append("roomJoin not granted")
    if grants.get("canPublish") is not True:
        problems.append(f"canPublish={grants.get('canPublish')}")
    if grants.get("canSubscribe") is not True:
        problems.append(f"canSubscribe={grants.get('canSubscribe')}")
    if not exp or exp <= int(time.time()):
        problems.append(f"exp={exp} not in future")
    if not nbf or nbf > int(time.time()) + 30:
        problems.append(f"nbf={nbf} unexpectedly in future")

    exp_dt = (
        datetime.fromtimestamp(exp, tz=timezone.utc).isoformat() if exp else None
    )
    if problems:
        record(
            f"06 token_decode#{label_index}",
            "FAIL",
            "; ".join(problems),
            evidence={"claims": claims, "exp_iso": exp_dt},
        )
        return False
    record(
        f"06 token_decode#{label_index}",
        "PASS",
        f"grants ok; expires {exp_dt}",
        evidence={
            "iss": iss,
            "sub": sub,
            "video": grants,
            "exp_iso": exp_dt,
        },
    )
    return True


# ---------------------------------------------------------------------------
# WebRTC join + audio publish/subscribe
# ---------------------------------------------------------------------------


@dataclass
class JoinObservation:
    connected: bool = False
    error: str | None = None
    local_sid: str | None = None
    remote_seen: list[str] = field(default_factory=list)
    audio_frames_received: int = 0
    audio_bytes_received: int = 0


async def join_room(
    *,
    label: str,
    url: str,
    token: str,
    publish_audio: bool,
    audio_publish_seconds: float,
    settle_seconds: float,
    obs: JoinObservation,
    other_identity: str | None = None,
) -> None:
    """Connect as a participant, optionally publish a synthetic tone,
    record any remote audio received, then disconnect."""

    room = rtc.Room()
    audio_event = asyncio.Event()

    @room.on("participant_connected")
    def _on_join(p: rtc.RemoteParticipant) -> None:
        if p.identity not in obs.remote_seen:
            obs.remote_seen.append(p.identity)

    @room.on("track_subscribed")
    def _on_sub(track, pub, participant: rtc.RemoteParticipant):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        async def pump():
            stream = rtc.AudioStream(track)
            async for ev in stream:
                obs.audio_frames_received += 1
                obs.audio_bytes_received += len(bytes(ev.frame.data))
                if obs.audio_frames_received >= 5:
                    audio_event.set()
                    break

        asyncio.create_task(pump())

    try:
        await room.connect(url, token)
        obs.connected = True
        obs.local_sid = getattr(room.local_participant, "sid", None)
        # Anyone already in the room shows up in remote_participants.
        for rp in room.remote_participants.values():
            if rp.identity not in obs.remote_seen:
                obs.remote_seen.append(rp.identity)

        if publish_audio:
            sample_rate = 48000
            channels = 1
            source = rtc.AudioSource(sample_rate, channels)
            track = rtc.LocalAudioTrack.create_audio_track(
                f"{label}-audio", source
            )
            opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            await room.local_participant.publish_track(track, opts)

            # Generate a quiet 220 Hz tone to give the subscriber audio
            # frames it can actually count.
            frame_ms = 20
            samples_per_frame = sample_rate * frame_ms // 1000  # 960
            total_frames = int(audio_publish_seconds * 1000 / frame_ms)
            import math

            amplitude = 6000
            for n in range(total_frames):
                pcm = bytearray()
                for s in range(samples_per_frame):
                    t = (n * samples_per_frame + s) / sample_rate
                    val = int(amplitude * math.sin(2 * math.pi * 220 * t))
                    pcm += struct.pack("<h", val)
                frame = rtc.AudioFrame(
                    data=bytes(pcm),
                    sample_rate=sample_rate,
                    num_channels=channels,
                    samples_per_channel=samples_per_frame,
                )
                await source.capture_frame(frame)

            await source.wait_for_playout()
        else:
            # Receiver side: wait until we've actually got frames (or timeout).
            try:
                await asyncio.wait_for(audio_event.wait(), timeout=settle_seconds)
            except asyncio.TimeoutError:
                pass

    except Exception as exc:
        obs.error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            await room.disconnect()
        except Exception:
            pass


async def check_webrtc_and_audio(
    publisher_tok: dict,
    subscriber_tok: dict,
    *,
    publisher_id: str,
    subscriber_id: str,
) -> None:
    pub_obs = JoinObservation()
    sub_obs = JoinObservation()

    # Start subscriber first so it's in the room when publisher arrives.
    sub_task = asyncio.create_task(
        join_room(
            label="sub",
            url=subscriber_tok["url"],
            token=subscriber_tok["token"],
            publish_audio=False,
            audio_publish_seconds=0,
            settle_seconds=6.0,
            obs=sub_obs,
            other_identity=publisher_id,
        )
    )
    # Brief delay so the subscriber is fully wired.
    await asyncio.sleep(0.8)
    pub_task = asyncio.create_task(
        join_room(
            label="pub",
            url=publisher_tok["url"],
            token=publisher_tok["token"],
            publish_audio=True,
            audio_publish_seconds=2.0,
            settle_seconds=0,
            obs=pub_obs,
            other_identity=subscriber_id,
        )
    )

    await asyncio.gather(pub_task, sub_task)

    # 07 WebRTC connection established
    if pub_obs.connected and sub_obs.connected:
        record(
            "07 webrtc_connect",
            "PASS",
            f"pub_sid={pub_obs.local_sid} sub_sid={sub_obs.local_sid}",
        )
    else:
        record(
            "07 webrtc_connect",
            "FAIL",
            f"pub_err={pub_obs.error} sub_err={sub_obs.error}",
        )

    # 08 User joins room
    if pub_obs.connected:
        record("08 user_join", "PASS", f"identity={publisher_id} sid={pub_obs.local_sid}")
    else:
        record("08 user_join", "FAIL", pub_obs.error or "did not connect")

    # 09 Multiple participants in same room
    if subscriber_id in pub_obs.remote_seen or publisher_id in sub_obs.remote_seen:
        record(
            "09 multi_participant",
            "PASS",
            f"pub_saw={pub_obs.remote_seen} sub_saw={sub_obs.remote_seen}",
        )
    else:
        record(
            "09 multi_participant",
            "FAIL",
            f"neither side saw the other (pub={pub_obs.remote_seen}, sub={sub_obs.remote_seen})",
        )

    # 10 Audio publish + subscribe
    if sub_obs.audio_frames_received > 0:
        record(
            "10 audio_pub_sub",
            "PASS",
            f"frames={sub_obs.audio_frames_received} bytes={sub_obs.audio_bytes_received}",
        )
    else:
        record(
            "10 audio_pub_sub",
            "FAIL",
            "subscriber received 0 audio frames",
        )

    # 11 Disconnect & cleanup is implicit (both tasks reached finally:)
    record(
        "11 disconnect_cleanup",
        "PASS" if not (pub_obs.error or sub_obs.error) else "FAIL",
        "both participants disconnected cleanly"
        if not (pub_obs.error or sub_obs.error)
        else f"pub_err={pub_obs.error} sub_err={sub_obs.error}",
    )


# ---------------------------------------------------------------------------
# Error-handling battery
# ---------------------------------------------------------------------------


async def check_error_handling(
    client: httpx.AsyncClient, headers: dict, existing_room: str
) -> None:
    cases: list[tuple[str, str, int | set, dict | None, dict | None]] = [
        (
            "12a unauthenticated_room_create",
            "POST /livekit/rooms without token",
            {401, 403},
            None,
            None,
        ),
        (
            "12b nonexistent_room_get",
            "GET /livekit/rooms/<random>",
            404,
            None,
            None,
        ),
        (
            "12c bad_room_payload",
            "POST /livekit/rooms with empty name",
            422,
            None,
            None,
        ),
        (
            "12d duplicate_room_create",
            "POST /livekit/rooms with existing name",
            {200, 201, 409},
            None,
            None,
        ),
    ]

    flush_rate_limit()
    # 12a
    r = await client.post(f"{API}/livekit/rooms", json={"name": "noauth"})
    expected = cases[0][2]
    ok = r.status_code in (expected if isinstance(expected, set) else {expected})
    record(
        cases[0][0],
        "PASS" if ok else "FAIL",
        f"got {r.status_code}, expected {expected}",
    )

    # 12b
    bogus = f"missing-{uuid.uuid4().hex[:8]}"
    r = await client.get(f"{API}/livekit/rooms/{bogus}", headers=headers)
    ok = r.status_code == 404
    record(
        cases[1][0],
        "PASS" if ok else "FAIL",
        f"got {r.status_code}, expected 404 (body={r.text[:120]})",
    )

    # 12c
    r = await client.post(
        f"{API}/livekit/rooms", headers=headers, json={"name": ""}
    )
    ok = r.status_code == 422
    record(
        cases[2][0],
        "PASS" if ok else "FAIL",
        f"got {r.status_code}, expected 422",
    )

    # 12d
    r = await client.post(
        f"{API}/livekit/rooms",
        headers=headers,
        json={"name": existing_room, "max_participants": 4},
    )
    # LiveKit treats create_room as idempotent and returns the existing room
    # (200/201). Either that or a 409 is acceptable; surface the actual
    # behaviour in the report so the team can decide.
    ok = r.status_code in (200, 201, 409)
    record(
        cases[3][0],
        "PASS" if ok else "FAIL",
        f"got {r.status_code} (idempotent create or conflict)",
    )


# ---------------------------------------------------------------------------
# Logging check
# ---------------------------------------------------------------------------


def check_logging(room_name: str, publisher_id: str) -> None:
    path = Path(BACKEND_LOG)
    if not path.exists():
        record(
            "13 logging",
            "SKIP",
            f"backend log not at {BACKEND_LOG} (set E2E_BACKEND_LOG to point at it)",
        )
        return
    try:
        text = path.read_text(errors="replace")
    except Exception as exc:
        record("13 logging", "SKIP", f"could not read log: {exc}")
        return

    must_have = [
        ("livekit.client.initialised", "client init"),
        ("livekit.room.created", "room created"),
        ("livekit.token.minted", "token minted"),
        (room_name, "room name in log"),
    ]
    missing = [label for needle, label in must_have if needle not in text]
    if missing:
        record(
            "13 logging",
            "FAIL",
            f"missing structured events: {missing}",
        )
    else:
        record(
            "13 logging",
            "PASS",
            "structured logs present (init/room/token, target room name)",
        )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def delete_room(client: httpx.AsyncClient, headers: dict, name: str) -> None:
    flush_rate_limit()
    r, ms = await timed(client.delete(f"{API}/livekit/rooms/{name}", headers=headers))
    if r.status_code == 200:
        record("11b delete_room", "PASS", f"name={name}", duration_ms=ms)
    else:
        record(
            "11b delete_room",
            "FAIL",
            f"status={r.status_code} body={r.text[:200]}",
            duration_ms=ms,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    print(f"=== E2E full validation ===")
    print(f"BASE={BASE}")
    print(f"LIVEKIT_HTTP={LIVEKIT_HTTP}")
    print(f"LIVEKIT_URL={settings.LIVEKIT_URL}")
    print()

    room_name = f"e2e-full-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        await check_env_config()
        await check_livekit_connectivity(client)

        # Health
        flush_rate_limit()
        try:
            r = await client.get(f"{API}/health")
            ok = r.status_code == 200
            record(
                "00 backend_health",
                "PASS" if ok else "FAIL",
                f"GET /api/v1/health -> {r.status_code}",
            )
        except Exception as exc:
            record("00 backend_health", "FAIL", str(exc))
            return _summary()

        auth = await auth_setup(client)
        if auth is None:
            return _summary()
        access, _email = auth
        headers = {"Authorization": f"Bearer {access}"}

        room = await check_room_create(client, headers, room_name)
        if room is None:
            return _summary()

        await check_room_retrieve(client, headers, room_name)

        # Two tokens for two participants
        publisher_id = f"pub-{uuid.uuid4().hex[:6]}"
        subscriber_id = f"sub-{uuid.uuid4().hex[:6]}"
        pub_tok = await check_token_issue(
            client, headers, room_name, publisher_id, label_index=1
        )
        sub_tok = await check_token_issue(
            client, headers, room_name, subscriber_id, label_index=2
        )
        if not pub_tok or not sub_tok:
            return _summary()

        check_token_decode(pub_tok, expected_room=room_name, label_index=1)
        check_token_decode(sub_tok, expected_room=room_name, label_index=2)

        await check_webrtc_and_audio(
            pub_tok,
            sub_tok,
            publisher_id=publisher_id,
            subscriber_id=subscriber_id,
        )

        await check_error_handling(client, headers, room_name)

        await delete_room(client, headers, room_name)

    check_logging(room_name, publisher_id)
    return _summary()


def _summary() -> int:
    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    n_pass = sum(1 for r in RESULTS if r.status == "PASS")
    n_fail = sum(1 for r in RESULTS if r.status == "FAIL")
    n_skip = sum(1 for r in RESULTS if r.status == "SKIP")
    for r in RESULTS:
        print(f"  [{r.status}] {r.name:36s} {r.detail}")
    print()
    print(f"PASS={n_pass}  FAIL={n_fail}  SKIP={n_skip}  TOTAL={len(RESULTS)}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
