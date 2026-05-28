#!/usr/bin/env python3
"""End-to-end smoke test: auth → LiveKit room → token → session."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import httpx

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8001")
API = f"{BASE}/api/v1"
LIVEKIT_HTTP = os.environ.get("LIVEKIT_HTTP_URL", "http://127.0.0.1:7880")


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


async def main() -> None:
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    password = "E2eTestPass123!"
    room_name = f"e2e-room-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Health
        r = await client.get(f"{API}/health")
        if r.status_code != 200:
            _fail(f"health -> {r.status_code} {r.text}")
        _ok("health")

        # 2. Register
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
            _fail(f"register -> {r.status_code} {r.text}")
        _ok(f"register ({email})")

        # 3. Login (register does not return tokens)
        r = await client.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
        )
        if r.status_code != 200:
            _fail(f"login -> {r.status_code} {r.text}")
        tokens = r.json()
        access = tokens.get("access_token")
        if not access:
            _fail(f"login missing access_token: {tokens}")
        _ok("login")

        headers = {"Authorization": f"Bearer {access}"}

        # 4. Me
        r = await client.get(f"{API}/auth/me", headers=headers)
        if r.status_code != 200:
            _fail(f"me -> {r.status_code} {r.text}")
        _ok("auth/me")

        # Members (tenant-scoped)
        r = await client.get(f"{API}/members", headers=headers)
        if r.status_code != 200:
            _fail(f"members list -> {r.status_code} {r.text}")
        members = r.json()
        if not isinstance(members, list) or len(members) < 1:
            _fail(f"expected at least one member, got: {members}")
        _ok(f"members list ({len(members)} member(s))")

        # 5. LiveKit server reachable
        r = await client.get(LIVEKIT_HTTP)
        if r.status_code not in (200, 404):
            _fail(f"livekit server -> {r.status_code}")
        _ok("livekit server up")

        # 6. Create room
        r = await client.post(
            f"{API}/livekit/rooms",
            headers=headers,
            json={"name": room_name, "max_participants": 4},
        )
        if r.status_code not in (200, 201):
            _fail(f"create room -> {r.status_code} {r.text}")
        room = r.json()
        if room.get("name") != room_name:
            _fail(f"unexpected room payload: {room}")
        _ok(f"create room ({room_name})")

        # 7. Get room
        r = await client.get(f"{API}/livekit/rooms/{room_name}", headers=headers)
        if r.status_code != 200:
            _fail(f"get room -> {r.status_code} {r.text}")
        _ok("get room")

        # 8. List rooms — only assert the endpoint works. LiveKit Cloud has a
        # propagation delay on the unfiltered ListRooms call, so a freshly
        # created room may not appear immediately; the named lookup in step 7
        # is the authoritative existence check.
        r = await client.get(f"{API}/livekit/rooms", headers=headers)
        if r.status_code != 200:
            _fail(f"list rooms -> {r.status_code} {r.text}")
        names = [x["name"] for x in r.json().get("rooms", [])]
        present = "yes" if room_name in names else "not yet (cloud delay)"
        _ok(f"list rooms ({len(names)} total, target {present})")

        # 9. Issue token
        identity = f"user-{uuid.uuid4().hex[:6]}"
        r = await client.post(
            f"{API}/livekit/tokens",
            headers=headers,
            json={
                "room": room_name,
                "identity": identity,
                "name": "E2E Participant",
            },
        )
        if r.status_code != 200:
            _fail(f"token -> {r.status_code} {r.text}")
        tok = r.json()
        if not tok.get("token") or not tok.get("url"):
            _fail(f"bad token response: {tok}")
        _ok("issue token")

        # 10. Session record
        r = await client.get(
            f"{API}/livekit/sessions/{room_name}",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"session -> {r.status_code} {r.text}")
        session = r.json()
        if session.get("room_name") != room_name:
            _fail(f"bad session: {session}")
        _ok("session record")

        # 11. Delete room
        r = await client.delete(
            f"{API}/livekit/rooms/{room_name}",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"delete room -> {r.status_code} {r.text}")
        _ok("delete room")

    print("\n=== All E2E checks passed ===")


if __name__ == "__main__":
    asyncio.run(main())
