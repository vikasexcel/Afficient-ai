"""Latency benchmarks for the Twilio call-setup path.

By default we exercise the fake client + TwiML builder so we capture
the framework overhead (validators, asyncio.to_thread bridging, etc.).
The real Twilio REST call only runs when ``RUN_TWILIO_BENCH=1`` and
the credentials are non-dummy.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from config.settings import settings
from modules.telephony.twilio_client import TwilioClient
from tests._support.benchmark import measure, measure_async, twilio_enabled
from tests._support.fakes import FakeTwilioClient


pytestmark = pytest.mark.latency


FAKE_ITERS = int(os.environ.get("BENCH_TWILIO_FAKE_ITERATIONS", "30"))
LIVE_ITERS = int(os.environ.get("BENCH_TWILIO_LIVE_ITERATIONS", "2"))


def test_latency_twilio_build_voice_twiml():
    """Pure XML build — no I/O. Tiny, but useful as a floor."""

    client = TwilioClient(
        account_sid="ACdummy00000000000000000000000000",
        auth_token="dummytoken",
        phone_number="+15551234567",
        public_base_url="https://api.test",
        livekit_sip_uri="sip.livekit.cloud",
    )
    for _ in range(FAKE_ITERS):
        with measure("twilio", "build_voice_twiml"):
            client.build_voice_twiml(room_name="bench-room")


def test_latency_twilio_create_call_with_fake():
    fake = FakeTwilioClient(create_latency_ms=2)

    async def go() -> None:
        for _ in range(FAKE_ITERS):
            async with measure_async(
                "twilio",
                "create_call (fake)",
                metadata={"mode": "fake"},
            ):
                await fake.create_call(
                    to_number="+15558675309", room_name="bench-room"
                )

    asyncio.run(go())


def test_latency_twilio_hangup_with_fake():
    fake = FakeTwilioClient(hangup_latency_ms=2)

    async def go() -> None:
        for _ in range(FAKE_ITERS):
            async with measure_async(
                "twilio",
                "hangup (fake)",
                metadata={"mode": "fake"},
            ):
                await fake.hangup("CA0000000000000000000000000000000a")

    asyncio.run(go())


@pytest.mark.external
@pytest.mark.skipif(
    not (
        twilio_enabled()
        and settings.TWILIO_ACCOUNT_SID
        and not settings.TWILIO_ACCOUNT_SID.startswith("ACdummy")
    ),
    reason="Twilio benchmark disabled (set RUN_TWILIO_BENCH=1 and real creds)",
)
def test_latency_twilio_create_call_live():
    """WARNING: places live PSTN calls — only run with explicit consent."""

    async def go() -> None:
        client = TwilioClient()
        to_number = os.environ.get(
            "BENCH_TWILIO_TO_NUMBER", settings.TWILIO_PHONE_NUMBER
        )
        for _ in range(LIVE_ITERS):
            async with measure_async(
                "twilio",
                "create_call (live)",
                metadata={"mode": "live", "to": to_number},
            ):
                originated = await client.create_call(
                    to_number=to_number, room_name="bench-room"
                )
                await client.hangup(originated.sid)

    asyncio.run(go())
