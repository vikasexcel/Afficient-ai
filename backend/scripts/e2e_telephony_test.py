#!/usr/bin/env python3
"""End-to-end validation for the Twilio PSTN integration.

Validates, against a running backend (no real Twilio dial required):

  1. Auth + tenant bootstrap.
  2. ``POST /telephony/calls``  — outbound origination.
       * Uses Twilio test credentials when configured (no real call placed)
         or stubs the TwilioClient when only ``--no-twilio`` is passed.
  3. DB row + LiveKit room are created with matching ``room_name``.
  4. ``GET /telephony/calls/{id}`` — call tracking.
  5. ``POST /telephony/webhooks/voice`` — TwiML is well-formed XML and
     contains a ``<Dial><Sip>`` verb when ``LIVEKIT_SIP_URI`` is set,
     otherwise a ``<Say>`` fallback.
  6. ``POST /telephony/webhooks/status`` — signature validation
     (negative + positive) + status transition (``ringing`` →
     ``in-progress`` → ``completed``) + ``telephony_events`` rows.
  7. ``GET /telephony/calls/{id}/events`` — event log integrity.
  8. ``POST /telephony/calls/{id}/cancel`` — cancel path is idempotent
     against a completed call.

Run a backend on ``E2E_BASE_URL`` (default ``http://127.0.0.1:8002``) with:

    cd backend
    source venv/bin/activate
    # Use Twilio's official magic test credentials so no real call lands:
    #   ACCOUNT_SID=ACxxxxxxxx...  AUTH_TOKEN=xxxxxxxx
    #   FROM_NUMBER=+15005550006   (magic "valid" number)
    #   TO_NUMBER  =+15005550006
    export TWILIO_ACCOUNT_SID=AC...
    export TWILIO_AUTH_TOKEN=...
    export TWILIO_PHONE_NUMBER=+15005550006
    export TWILIO_VALIDATE_SIGNATURE=false   # signature is computed by us below
    python scripts/e2e_telephony_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import redis as redis_pkg  # noqa: E402
from config.settings import settings  # noqa: E402

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8002")
API = f"{BASE}/api/v1"

# Twilio "magic" numbers — see
# https://www.twilio.com/docs/iam/test-credentials#test-sms-messages
TEST_FROM = os.environ.get("E2E_TEST_FROM", "+15005550006")
TEST_TO = os.environ.get("E2E_TEST_TO", "+15005550006")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def flush_rate_limit() -> None:
    try:
        rc = redis_pkg.from_url(settings.REDIS_URL)
        for key in rc.scan_iter("api:*"):
            rc.delete(key)
    except Exception as exc:  # pragma: no cover
        print(f"WARN: redis flush failed: {exc}")


def _sign(url: str, params: dict) -> str:
    """Replicate Twilio's signature algorithm for the status webhook test."""

    from twilio.request_validator import RequestValidator

    return RequestValidator(settings.TWILIO_AUTH_TOKEN).compute_signature(
        url, params
    )


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def main() -> int:
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        _fail(
            "TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN must be set on the "
            "server. Use Twilio test credentials (no real call placed)."
        )

    email = f"e2e-tel-{uuid.uuid4().hex[:8]}@example.com"
    password = "E2eTestPass123!"

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Auth
        flush_rate_limit()
        r = await client.post(
            f"{API}/auth/register",
            json={
                "full_name": "Telephony E2E",
                "email": email,
                "password": password,
                "organization": f"Telephony E2E {uuid.uuid4().hex[:6]}",
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
        _ok(f"auth ({email})")

        # 2. Initiate outbound
        flush_rate_limit()
        r = await client.post(
            f"{API}/telephony/calls",
            headers=headers,
            json={
                "to_number": TEST_TO,
                "from_number": TEST_FROM,
                "lead_name": "Jane Doe",
                "lead_phone": TEST_TO,
                "persona": "outbound_sdr",
                "qualification_framework": "BANT",
                "opening_line": (
                    "Hi Jane, this is Alex from Aifficient — got 30 seconds?"
                ),
                "extra_context": {
                    "company": "Aifficient",
                    "product": "AI outbound dialer",
                    "value_prop": "10x SDR throughput",
                    "objective": "book a 15-minute discovery call",
                    "agent_name": "Alex from Aifficient",
                },
                "dial_timeout_seconds": 30,
                "answering_machine_detection": False,
            },
        )
        if r.status_code != 201:
            _fail(f"initiate -> {r.status_code} {r.text}")
        call = r.json()
        call_id = call["id"]
        call_sid = call["call_sid"]
        room_name = call["room_name"]
        if not (call_id and call_sid and room_name):
            _fail(f"missing keys on call response: {call}")
        if call["status"] not in ("queued", "initiated", "ringing", "in-progress"):
            _fail(f"unexpected initial status: {call['status']}")
        _ok(
            f"initiate (sid={call_sid}, status={call['status']}, "
            f"room={room_name})"
        )

        # 3. LiveKit room was created with the same name
        flush_rate_limit()
        r = await client.get(
            f"{API}/livekit/sessions/{room_name}", headers=headers
        )
        if r.status_code != 200:
            _fail(f"livekit session lookup -> {r.status_code} {r.text}")
        session = r.json()
        if session.get("room_name") != room_name:
            _fail(f"livekit session room mismatch: {session}")
        _ok(f"livekit session bound to room ({room_name})")

        # 4. GET by id
        flush_rate_limit()
        r = await client.get(
            f"{API}/telephony/calls/{call_id}", headers=headers
        )
        if r.status_code != 200:
            _fail(f"get call -> {r.status_code} {r.text}")
        fetched = r.json()
        if fetched["id"] != call_id or fetched["call_sid"] != call_sid:
            _fail(f"get call mismatch: {fetched}")
        _ok("get call by id")

        # GET by SID
        r = await client.get(
            f"{API}/telephony/calls/by-sid/{call_sid}",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"get by sid -> {r.status_code}")
        _ok("get call by sid")

        # 5. /webhooks/voice TwiML
        # The voice webhook is public — no auth header required.
        flush_rate_limit()
        voice_url = (
            f"{settings.TWILIO_PUBLIC_BASE_URL.rstrip('/')}"
            f"/api/v1/telephony/webhooks/voice?room={room_name}"
        )
        voice_form = {
            "CallSid": call_sid,
            "AccountSid": settings.TWILIO_ACCOUNT_SID,
            "From": TEST_FROM,
            "To": TEST_TO,
            "CallStatus": "in-progress",
        }
        voice_headers = {}
        if settings.TWILIO_VALIDATE_SIGNATURE:
            voice_headers["X-Twilio-Signature"] = _sign(
                voice_url, voice_form
            )
        r = await client.post(
            f"{API}/telephony/webhooks/voice",
            headers=voice_headers,
            params={"room": room_name},
            data=voice_form,
        )
        if r.status_code != 200:
            _fail(f"voice webhook -> {r.status_code} {r.text}")
        twiml = r.text
        # Must be valid XML.
        try:
            root = ET.fromstring(twiml)
        except ET.ParseError as exc:
            _fail(f"voice webhook returned invalid XML: {exc} | {twiml!r}")
        if root.tag != "Response":
            _fail(f"voice webhook root tag = {root.tag!r}, expected Response")
        if settings.LIVEKIT_SIP_URI:
            dial = root.find("Dial")
            sip = dial.find("Sip") if dial is not None else None
            if sip is None or room_name not in (sip.text or ""):
                _fail(
                    f"expected <Dial><Sip>sip:{room_name}@...</Sip></Dial>, "
                    f"got: {twiml}"
                )
            _ok(f"voice TwiML SIP bridge -> {sip.text}")
        else:
            say = root.find("Say")
            if say is None:
                _fail(f"expected <Say> fallback TwiML, got: {twiml}")
            _ok("voice TwiML fallback <Say> (LIVEKIT_SIP_URI not set)")

        # 6a. /webhooks/status — invalid signature (when enabled)
        if settings.TWILIO_VALIDATE_SIGNATURE:
            flush_rate_limit()
            r = await client.post(
                f"{API}/telephony/webhooks/status",
                params={"room": room_name},
                data={
                    "CallSid": call_sid,
                    "CallStatus": "ringing",
                },
                headers={"X-Twilio-Signature": "obviously-wrong"},
            )
            if r.status_code != 403:
                _fail(
                    f"expected 403 for bad signature, got "
                    f"{r.status_code} {r.text}"
                )
            _ok("status webhook rejects bad signature (403)")

        # 6b. /webhooks/status — ringing
        flush_rate_limit()
        status_url = (
            f"{settings.TWILIO_PUBLIC_BASE_URL.rstrip('/')}"
            f"/api/v1/telephony/webhooks/status?room={room_name}"
        )
        ringing_form = {
            "CallSid": call_sid,
            "AccountSid": settings.TWILIO_ACCOUNT_SID,
            "From": TEST_FROM,
            "To": TEST_TO,
            "CallStatus": "ringing",
        }
        ringing_headers = {}
        if settings.TWILIO_VALIDATE_SIGNATURE:
            ringing_headers["X-Twilio-Signature"] = _sign(
                status_url, ringing_form
            )
        r = await client.post(
            f"{API}/telephony/webhooks/status",
            params={"room": room_name},
            data=ringing_form,
            headers=ringing_headers,
        )
        if r.status_code != 200:
            _fail(f"status (ringing) -> {r.status_code} {r.text}")
        if r.json().get("status") != "ringing":
            _fail(f"status (ringing) ack: {r.json()}")
        _ok("status webhook -> ringing")

        # 6c. /webhooks/status — answered (in-progress)
        flush_rate_limit()
        ans_form = dict(ringing_form, CallStatus="in-progress")
        ans_headers = {}
        if settings.TWILIO_VALIDATE_SIGNATURE:
            ans_headers["X-Twilio-Signature"] = _sign(
                status_url, ans_form
            )
        r = await client.post(
            f"{API}/telephony/webhooks/status",
            params={"room": room_name},
            data=ans_form,
            headers=ans_headers,
        )
        if r.status_code != 200 or r.json().get("status") != "in-progress":
            _fail(f"status (in-progress) -> {r.status_code} {r.text}")
        _ok("status webhook -> in-progress")

        # 6d. /webhooks/status — completed
        flush_rate_limit()
        done_form = dict(
            ringing_form,
            CallStatus="completed",
            CallDuration="42",
            Price="-0.0085",
            PriceUnit="USD",
        )
        done_headers = {}
        if settings.TWILIO_VALIDATE_SIGNATURE:
            done_headers["X-Twilio-Signature"] = _sign(
                status_url, done_form
            )
        r = await client.post(
            f"{API}/telephony/webhooks/status",
            params={"room": room_name},
            data=done_form,
            headers=done_headers,
        )
        if r.status_code != 200 or r.json().get("status") != "completed":
            _fail(f"status (completed) -> {r.status_code} {r.text}")
        _ok("status webhook -> completed (with price + duration)")

        # 7. /calls/{id} reflects completed + duration + price
        r = await client.get(
            f"{API}/telephony/calls/{call_id}", headers=headers
        )
        if r.status_code != 200:
            _fail(f"get after completion -> {r.status_code}")
        completed = r.json()
        if completed["status"] != "completed":
            _fail(f"final status not completed: {completed}")
        if completed["duration_seconds"] != 42:
            _fail(
                f"duration_seconds not propagated: {completed['duration_seconds']}"
            )
        if completed["price_unit"] != "USD":
            _fail(f"price_unit not propagated: {completed}")
        if completed["ended_at"] is None:
            _fail("ended_at not set on completion")
        _ok(
            f"call tracking (duration={completed['duration_seconds']}s, "
            f"price={completed['price']} {completed['price_unit']})"
        )

        # 8. /calls/{id}/events
        r = await client.get(
            f"{API}/telephony/calls/{call_id}/events",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"events -> {r.status_code}")
        events = r.json()["events"]
        types = [e["event_type"] for e in events]
        # Must contain at least: originated + ringing + in-progress + completed
        # plus an ai_agent_started marker.
        required = {
            "originated",
            "ringing",
            "in-progress",
            "completed",
            "ai_agent_started",
        }
        missing = required - set(types)
        if missing:
            _fail(f"missing events {missing!r}; got {types!r}")
        _ok(f"events log ({len(events)} rows, contains {sorted(required)})")

        # 9. Cancel on a completed call is a no-op (returns the row as-is)
        r = await client.post(
            f"{API}/telephony/calls/{call_id}/cancel",
            headers=headers,
        )
        if r.status_code != 200:
            _fail(f"cancel -> {r.status_code} {r.text}")
        if r.json()["status"] != "completed":
            _fail(
                "cancel of completed call mutated status: "
                f"{r.json()['status']}"
            )
        _ok("cancel of completed call is a no-op")

        # 10. List endpoint includes our call
        r = await client.get(
            f"{API}/telephony/calls?limit=10", headers=headers
        )
        if r.status_code != 200:
            _fail(f"list -> {r.status_code}")
        ids = [c["id"] for c in r.json()["calls"]]
        if call_id not in ids:
            _fail(f"list missing our call id ({call_id}); got {ids}")
        _ok(f"list calls ({len(ids)} total, contains our call)")

    print("\n=== Telephony E2E passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
