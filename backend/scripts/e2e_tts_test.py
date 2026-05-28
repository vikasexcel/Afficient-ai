#!/usr/bin/env python3
"""End-to-end: auth → room → ElevenLabs TTS speak → voices API."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import httpx

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8001")
API = f"{BASE}/api/v1"


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


async def main() -> None:
    email = f"e2e-tts-{uuid.uuid4().hex[:8]}@example.com"
    password = "E2eTestPass123!"
    room_name = f"tts-e2e-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Health
        r = await client.get(f"{API}/health")
        if r.status_code != 200:
            _fail(f"health -> {r.status_code}")
        _ok("health")

        # Auth
        r = await client.post(
            f"{API}/auth/register",
            json={
                "full_name": "TTS E2E",
                "email": email,
                "password": password,
                "organization": f"TTS Org {uuid.uuid4().hex[:6]}",
            },
        )
        if r.status_code not in (200, 201):
            _fail(f"register -> {r.status_code} {r.text}")

        r = await client.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
        )
        if r.status_code != 200:
            _fail(f"login -> {r.status_code}")
        access = r.json().get("access_token")
        if not access:
            _fail("no access_token")
        headers = {"Authorization": f"Bearer {access}"}
        _ok("auth")

        # List voices (ElevenLabs)
        r = await client.get(f"{API}/tts/voices", headers=headers)
        if r.status_code != 200:
            _fail(f"tts/voices -> {r.status_code} {r.text}")
        voices = r.json().get("voices", [])
        if not voices:
            _fail("no voices returned")
        _ok(f"tts/voices ({len(voices)} voices)")

        # Create LiveKit room
        r = await client.post(
            f"{API}/livekit/rooms",
            headers=headers,
            json={"name": room_name, "max_participants": 4},
        )
        if r.status_code not in (200, 201):
            _fail(f"create room -> {r.status_code} {r.text}")
        _ok(f"livekit room ({room_name})")

        # Speak into room (blocking — real ElevenLabs + LiveKit stream)
        r = await client.post(
            f"{API}/tts/speak",
            headers=headers,
            json={
                "room": room_name,
                "text": "Hello. This is an end to end test of Aifficient text to speech.",
                "wait": True,
            },
            timeout=120.0,
        )
        if r.status_code != 200:
            _fail(f"tts/speak -> {r.status_code} {r.text}")
        body = r.json()
        if body.get("bytes_streamed", 0) <= 0:
            _fail(f"no audio streamed: {body}")
        if body.get("dispatched"):
            _fail("expected blocking speak, got dispatched=true")
        _ok(
            f"tts/speak ({body['bytes_streamed']} bytes, "
            f"{body['duration_ms']} ms, voice={body['voice_id'][:8]}…)"
        )

        # Background dispatch smoke
        r = await client.post(
            f"{API}/tts/speak",
            headers=headers,
            json={
                "room": room_name,
                "text": "Background task test.",
                "wait": False,
            },
        )
        if r.status_code != 200:
            _fail(f"tts/speak async -> {r.status_code} {r.text}")
        if not r.json().get("dispatched"):
            _fail("expected dispatched=true for wait=false")
        _ok("tts/speak async dispatch")
        await asyncio.sleep(3)

        # Cleanup room
        r = await client.delete(
            f"{API}/livekit/rooms/{room_name}",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"delete room -> {r.status_code}")
        _ok("cleanup room")

    print("\n=== TTS E2E passed ===")


if __name__ == "__main__":
    asyncio.run(main())
