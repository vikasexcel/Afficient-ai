"""End-to-end proof that campaign dispatch runs the AI agent on the
long-lived FastAPI event loop (not a short-lived Celery ``asyncio.run`` loop).

Regression coverage for the "calls connect but the AI never speaks" audit:

ROOT CAUSE — the campaign scheduler dispatched executions with
``asyncio.run(run_execution(...))`` inside the Celery worker. That spun up the
AI ``CallAgentRunner`` background task + the shared async LiveKit / Redis
clients on a loop that ``asyncio.run`` tore down the moment origination
returned. The orphaned agent task died with ``RuntimeError: Event loop is
closed`` / ``Future attached to a different loop`` ~17s before the lead even
answered, so the caller heard silence.

THE FIX — the scheduler now only builds the dial payload and sends an
authenticated internal HTTP request to ``POST /api/v1/telephony/calls``. The
FastAPI process owns LiveKit room creation, agent startup, STT/LLM/TTS init,
and SIP bridging on its long-running event loop.

This test drives the real chain Campaign → Scheduler dispatcher → internal
HTTP → TelephonyService → LiveKit room → CallAgentRunner → orchestrator →
greeting, with deterministic fakes for Twilio / LiveKit / STT / TTS, and
asserts the success criteria:

* LiveKit room successfully created.
* Agent joined the room (STT + TTS sessions opened == STT/TTS initialized).
* Greeting (opening line) audio generated.
* Agent stays alive until the call ends, then shuts down cleanly with NO
  "Event loop is closed" / "Future attached to a different loop" error.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import redis

from config.settings import settings
from database.session import SessionLocal
from modules.campaign.execution_model import Execution
from modules.campaign.workflow_model import Workflow
from tests._support.fakes import (
    FakeLiveKitService,
    FakeOpenAIClient,
    FakeTwilioClient,
)


pytestmark = pytest.mark.api


def _redis_available() -> bool:
    try:
        return bool(
            redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping()
        )
    except Exception:
        return False


_WIDE_HOURS = {
    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "start": "00:00",
    "end": "23:59",
    "skip_holidays": False,
}


# --------------------------------------------------------------------------- #
# Fake realtime streamers — drive the REAL ConversationOrchestrator without
# touching LiveKit / Deepgram / ElevenLabs. Record side-effects so the test
# can assert STT/TTS init + greeting generation.
# --------------------------------------------------------------------------- #


class _FakeTTSSession:
    is_speaking = False

    def __init__(self, spoken: list[str]) -> None:
        self._spoken = spoken

    async def wait_for_human(self, *, exclude=None, timeout: float = 0.0):
        return "sip-caller"

    async def speak(self, text, *, voice_id=None, wait_for_playout=False):
        self._spoken.append(text)
        return SimpleNamespace(bytes_streamed=4096, ttfb_ms=10, stream_end_ms=50)

    async def interrupt(self):
        return SimpleNamespace(
            was_speaking=False, silence_latency_ms=0, dropped_buffer_ms=0
        )


class _FakeTTSStreamer:
    agent_identity = "ai-tts-agent"

    def __init__(self, spoken: list[str], opened: list[tuple[str, str]]) -> None:
        self._spoken = spoken
        self._opened = opened

    @asynccontextmanager
    async def open_session(self, *, room):
        self._opened.append(("tts", room))
        yield _FakeTTSSession(self._spoken)


class _FakeSTTSession:
    async def events(self):
        # No user speech in this scenario — the greeting is the only audio.
        # An empty async generator: the orchestrator loop returns at once and
        # the runner then idles on its stop event (agent stays in the room).
        return
        yield  # pragma: no cover — marks this an async generator


class _FakeSTTStreamer:
    agent_identity = "ai-stt-agent"

    def __init__(self, opened: list[tuple[str, str]]) -> None:
        self._opened = opened

    @asynccontextmanager
    async def open_session(
        self,
        *,
        room,
        target_participant=None,
        sample_rate=48000,
        num_channels=1,
        ignore_identities=None,
    ):
        self._opened.append(("stt", room))
        yield _FakeSTTSession()


# --------------------------------------------------------------------------- #
# Seeding helpers (mirror the dialing-e2e suite).
# --------------------------------------------------------------------------- #


def _seed_playbook(client, headers) -> str:
    r = client.get("/api/v1/playbooks", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["playbooks"][0]["id"]


def _seed_lead_list(client, headers) -> str:
    rows = [
        {
            "name": "Ada Lovelace",
            "email": f"ada.{uuid.uuid4().hex[:5]}@example.com",
            "phone": "+14155550199",
            "company": "Acme",
        }
    ]
    r = client.post(
        "/api/v1/leads/upload/commit",
        json={
            "rows": rows,
            "segmentation": {"tags": ["dial"]},
            "new_list_name": f"Dispatch List {uuid.uuid4().hex[:6]}",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["lead_list"]["id"]


def _launch_campaign(client, headers) -> str:
    playbook_id = _seed_playbook(client, headers)
    lead_list_id = _seed_lead_list(client, headers)
    cid = client.post(
        "/api/v1/campaigns",
        json={
            "name": f"Dispatch {uuid.uuid4().hex[:6]}",
            "playbook_id": playbook_id,
            "lead_list_id": lead_list_id,
            "schedule": {"start_immediately": True, "timezone": "UTC"},
            "business_hours": _WIDE_HOURS,
        },
        headers=headers,
    ).json()["id"]
    r = client.post(
        "/api/v1/campaigns/activate",
        json={"campaign_id": cid},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["enqueued_leads"] == 1, r.json()
    return cid


def _queued_execution(campaign_id: str) -> uuid.UUID:
    db = SessionLocal()
    try:
        row = (
            db.query(Execution)
            .join(Workflow, Workflow.id == Execution.workflow_id)
            .filter(Workflow.campaign_id == uuid.UUID(campaign_id))
            .filter(Execution.status == "queued")
            .first()
        )
        assert row is not None, "expected a queued execution after activation"
        return row.id
    finally:
        db.close()


def _poll(predicate, *, timeout: float = 4.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.mark.skipif(not _redis_available(), reason="Redis is not reachable")
def test_campaign_dispatch_runs_agent_and_generates_greeting(
    client, unique_user, monkeypatch
):
    from modules.ai.memory import ConversationMemory
    from modules.ai.service import AIService
    from modules.campaign import worker as worker_mod
    from modules.campaign.scheduler import _default_dispatcher
    from modules.telephony.agent_runner import CallAgentRegistry
    from modules.telephony.dependencies import get_telephony_service
    from modules.telephony.service import TelephonyService
    from main import app

    headers = {"Authorization": f"Bearer {unique_user['access_token']}"}
    campaign_id = _launch_campaign(client, headers)
    execution_id = _queued_execution(campaign_id)

    # --- Fakes / instrumentation ------------------------------------------- #
    spoken: list[str] = []
    opened: list[tuple[str, str]] = []
    fake_livekit = FakeLiveKitService()
    registry = CallAgentRegistry()
    svc = TelephonyService(
        twilio=FakeTwilioClient(),
        livekit=fake_livekit,
        agent_registry=registry,
    )

    # The FastAPI origination endpoint must use our fake-backed service so the
    # real CallAgentRunner spins up on the TestClient's (long-lived) loop.
    app.dependency_overrides[get_telephony_service] = lambda: svc

    # The agent runner pulls its realtime deps lazily inside ``_run`` — point
    # them at fakes (same LiveKit instance so the room is observable).
    memory = ConversationMemory()
    ai = AIService(openai=FakeOpenAIClient(), memory=memory)
    monkeypatch.setattr(
        "modules.telephony.agent_runner.get_livekit_service",
        lambda: fake_livekit,
    )
    monkeypatch.setattr(
        "modules.telephony.agent_runner.get_ai_service", lambda: ai
    )
    monkeypatch.setattr(
        "modules.telephony.agent_runner.get_stt_streamer",
        lambda: _FakeSTTStreamer(opened),
    )
    monkeypatch.setattr(
        "modules.telephony.agent_runner.get_tts_streamer",
        lambda: _FakeTTSStreamer(spoken, opened),
    )

    # Force the production HTTP dispatch path + Twilio origination (no SIP
    # trunk), and skip Twilio webhook signature checks for the teardown call.
    monkeypatch.setattr(worker_mod.settings, "CAMPAIGN_TELEPHONY_DIALING_ENABLED", True)
    monkeypatch.setattr(worker_mod.settings, "CAMPAIGN_DISPATCH_VIA_HTTP", True)
    monkeypatch.setattr(
        "modules.telephony.service.settings.LIVEKIT_SIP_OUTBOUND_TRUNK_ID", ""
    )
    monkeypatch.setattr(
        "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
    )

    # Route the worker's outbound internal HTTP request to the in-process app.
    def _fake_post(url, json=None, headers=None, timeout=None):
        path = url[url.index(settings.API_PREFIX):]
        return client.post(path, json=json, headers=headers)

    monkeypatch.setattr(worker_mod.httpx, "post", _fake_post)

    try:
        # --- Campaign → Scheduler dispatcher → internal HTTP → telephony --- #
        db = SessionLocal()
        try:
            execution = db.get(Execution, execution_id)
            _default_dispatcher(db, [execution])
            db.refresh(execution)
            assert execution.status == "running", (
                "dispatch should leave the execution running (terminal "
                "outcome arrives later via the Twilio status webhook)"
            )
            call_id = (execution.context or {}).get("telephony_call_id")
            assert call_id, "telephony_call_id should be stashed on the context"
        finally:
            db.close()

        # The FastAPI process placed the Twilio leg (origination ran on the
        # app loop, NOT a Celery asyncio.run loop).
        assert svc._twilio.calls_created, "expected origination via FastAPI"
        sid = svc._twilio.calls_created[0].sid
        room_name = svc._twilio.last_kwargs.get("room_name") or next(
            iter(fake_livekit.rooms), None
        )
        assert room_name, "a room name should have been generated"

        # SUCCESS CRITERION 1 — LiveKit room created.
        assert _poll(lambda: room_name in fake_livekit.rooms), (
            "LiveKit room was not created"
        )

        # SUCCESS CRITERION 2 — agent joined the room: STT + TTS sessions
        # opened (== STT/LLM/TTS initialized) on the long-lived loop.
        assert _poll(
            lambda: ("tts", room_name) in opened and ("stt", room_name) in opened
        ), f"agent did not open STT+TTS sessions; opened={opened}"

        # SUCCESS CRITERION 3 — greeting audio generated.
        assert _poll(lambda: len(spoken) >= 1), "no greeting was generated"
        assert spoken[0].strip(), "greeting text was empty"

        # SUCCESS CRITERION 4 — agent stays alive until the call ends.
        runner = registry.get(room_name)
        assert runner is not None and runner.is_running, (
            "agent runner should still be alive while the call is in progress"
        )

        # --- End the call via the terminal Twilio status webhook ----------- #
        r = client.post(
            "/api/v1/telephony/webhooks/status",
            data={"CallSid": sid, "CallStatus": "completed", "CallDuration": "12"},
        )
        assert r.status_code == 200, r.text

        # The runner task must finish cleanly — NO "Event loop is closed" /
        # "Future attached to a different loop".
        assert _poll(lambda: runner.task is not None and runner.task.done()), (
            "agent runner task did not finish after the call ended"
        )
        exc = runner.task.exception()
        assert exc is None, f"agent runner crashed: {exc!r}"
    finally:
        app.dependency_overrides.pop(get_telephony_service, None)
