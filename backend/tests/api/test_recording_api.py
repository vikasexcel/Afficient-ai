"""API tests for call recording endpoints.

Covers:
* POST /telephony/webhooks/recording — Twilio RecordingStatus callback
* GET  /telephony/calls/{id}/recording — presigned S3 URL
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from main import app
from modules.telephony.dependencies import get_telephony_service, get_twilio_client
from tests._support.fakes import FakeTwilioClient

pytestmark = pytest.mark.api


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_twilio():
    fake = FakeTwilioClient()
    app.dependency_overrides[get_twilio_client] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_twilio_client, None)


@pytest.fixture
def fake_service():
    """Inject a minimal TelephonyService mock for recording-specific tests."""
    svc = MagicMock()
    svc.handle_recording_webhook = AsyncMock()
    svc.get_call = AsyncMock()
    app.dependency_overrides[get_telephony_service] = lambda: svc
    try:
        yield svc
    finally:
        app.dependency_overrides.pop(get_telephony_service, None)


# ---------------------------------------------------------------------------
# POST /telephony/webhooks/recording
# ---------------------------------------------------------------------------


class TestRecordingWebhook:
    def test_recording_webhook_acks_completed(
        self, client, fake_twilio, fake_service, monkeypatch
    ):
        monkeypatch.setattr(
            "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
        )
        call_sid = f"CA{uuid.uuid4().hex}"
        rec_sid = f"RE{uuid.uuid4().hex}"

        r = client.post(
            "/api/v1/telephony/webhooks/recording",
            data={
                "CallSid": call_sid,
                "RecordingSid": rec_sid,
                "RecordingUrl": f"https://api.twilio.com/Recordings/{rec_sid}",
                "RecordingStatus": "completed",
                "RecordingDuration": "45",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["call_sid"] == call_sid
        assert body["status"] == "completed"

        fake_service.handle_recording_webhook.assert_awaited_once()

    def test_recording_webhook_acks_in_progress(
        self, client, fake_twilio, fake_service, monkeypatch
    ):
        """Twilio fires an in-progress ping; endpoint should still return 200."""
        monkeypatch.setattr(
            "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
        )
        r = client.post(
            "/api/v1/telephony/webhooks/recording",
            data={
                "CallSid": f"CA{uuid.uuid4().hex}",
                "RecordingSid": f"RE{uuid.uuid4().hex}",
                "RecordingStatus": "in-progress",
                "RecordingDuration": "0",
            },
        )
        assert r.status_code == 200
        # Service is still called — it does the status check internally.
        fake_service.handle_recording_webhook.assert_awaited_once()

    def test_recording_webhook_requires_twilio_signature_when_enabled(
        self, client, fake_twilio, fake_service, monkeypatch
    ):
        """With TWILIO_VALIDATE_SIGNATURE=True and no X-Twilio-Signature → 403."""
        monkeypatch.setattr(
            "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", True
        )
        # FakeTwilioClient.validate_signature always returns True,
        # but there's no signature header here so it returns False.
        fake_twilio.can_validate_signatures = True

        original = fake_twilio.validate_signature

        def _reject(**kwargs):
            return False

        fake_twilio.validate_signature = _reject
        try:
            r = client.post(
                "/api/v1/telephony/webhooks/recording",
                data={
                    "CallSid": f"CA{uuid.uuid4().hex}",
                    "RecordingStatus": "completed",
                },
            )
            assert r.status_code in (400, 403, 422)
        finally:
            fake_twilio.validate_signature = original

    def test_recording_webhook_no_call_sid_still_200(
        self, client, fake_twilio, fake_service, monkeypatch
    ):
        """Missing CallSid is handled gracefully — service no-ops, route returns 200."""
        monkeypatch.setattr(
            "modules.telephony.router.settings.TWILIO_VALIDATE_SIGNATURE", False
        )
        r = client.post(
            "/api/v1/telephony/webhooks/recording",
            data={"RecordingStatus": "completed"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# GET /telephony/calls/{id}/recording  — presigned URL endpoint
# ---------------------------------------------------------------------------


class TestGetRecordingUrl:
    def test_returns_null_when_no_recording(
        self, client, auth_headers, fake_twilio, fake_service
    ):
        call_id = uuid.uuid4()
        fake_row = MagicMock()
        fake_row.id = call_id
        fake_row.organization_id = None
        fake_row.recording_url = None
        fake_service.get_call = AsyncMock(return_value=fake_row)

        r = client.get(
            f"/api/v1/telephony/calls/{call_id}/recording",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["presigned_url"] is None
        assert body["expires_in"] is None

    def test_returns_presigned_url_when_recording_exists(
        self, client, auth_headers, fake_twilio, fake_service, monkeypatch
    ):
        call_id = uuid.uuid4()
        fake_row = MagicMock()
        fake_row.id = call_id
        fake_row.organization_id = None
        fake_row.recording_url = "recordings/org/cam/CA1/RE1.mp3"
        fake_service.get_call = AsyncMock(return_value=fake_row)

        monkeypatch.setattr(
            "modules.telephony.router.settings.S3_RECORDINGS_BUCKET",
            "tellaigent-voice-recording",
        )
        monkeypatch.setattr(
            "modules.telephony.router.settings.S3_PRESIGNED_URL_EXPIRES",
            3600,
        )

        fake_s3 = MagicMock()
        fake_s3.presigned_url.return_value = (
            "https://tellaigent-voice-recording.s3.eu-west-2.amazonaws.com/"
            "recordings/org/cam/CA1/RE1.mp3?X-Amz-Expires=3600"
        )

        with patch(
            "modules.telephony.router.get_s3_client", return_value=fake_s3
        ):
            r = client.get(
                f"/api/v1/telephony/calls/{call_id}/recording",
                headers=auth_headers,
            )

        assert r.status_code == 200, r.text
        body = r.json()
        assert "presigned_url" in body
        assert body["presigned_url"].startswith("https://")
        assert body["expires_in"] == 3600

    def test_returns_404_when_call_not_found(
        self, client, auth_headers, fake_twilio, fake_service
    ):
        call_id = uuid.uuid4()
        fake_service.get_call = AsyncMock(return_value=None)

        r = client.get(
            f"/api/v1/telephony/calls/{call_id}/recording",
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_requires_auth(self, client, fake_twilio, fake_service):
        call_id = uuid.uuid4()
        r = client.get(f"/api/v1/telephony/calls/{call_id}/recording")
        assert r.status_code in (401, 403)

    def test_returns_503_when_s3_not_configured(
        self, client, auth_headers, fake_twilio, fake_service, monkeypatch
    ):
        call_id = uuid.uuid4()
        fake_row = MagicMock()
        fake_row.id = call_id
        fake_row.organization_id = None
        fake_row.recording_url = "recordings/some/key.mp3"
        fake_service.get_call = AsyncMock(return_value=fake_row)

        monkeypatch.setattr(
            "modules.telephony.router.settings.S3_RECORDINGS_BUCKET", ""
        )

        r = client.get(
            f"/api/v1/telephony/calls/{call_id}/recording",
            headers=auth_headers,
        )
        assert r.status_code == 503

    def test_returns_500_when_presign_fails(
        self, client, auth_headers, fake_twilio, fake_service, monkeypatch
    ):
        call_id = uuid.uuid4()
        fake_row = MagicMock()
        fake_row.id = call_id
        fake_row.organization_id = None
        fake_row.recording_url = "recordings/bad/key.mp3"
        fake_service.get_call = AsyncMock(return_value=fake_row)

        monkeypatch.setattr(
            "modules.telephony.router.settings.S3_RECORDINGS_BUCKET",
            "tellaigent-voice-recording",
        )

        from botocore.exceptions import ClientError

        fake_s3 = MagicMock()
        fake_s3.presigned_url.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "bucket gone"}},
            "GeneratePresignedUrl",
        )

        with patch(
            "modules.telephony.router.get_s3_client", return_value=fake_s3
        ):
            r = client.get(
                f"/api/v1/telephony/calls/{call_id}/recording",
                headers=auth_headers,
            )

        assert r.status_code == 500


# ---------------------------------------------------------------------------
# twilio_client.py — recording_status_callback uses dedicated path
# ---------------------------------------------------------------------------


class TestTwilioClientRecordingCallback:
    def test_create_call_recording_callback_uses_dedicated_path(self, monkeypatch):
        """When TWILIO_CALL_RECORD=True the recording callback URL must point
        to /webhooks/recording, NOT /webhooks/status."""
        import asyncio

        from modules.telephony.twilio_client import TwilioClient

        monkeypatch.setattr(
            "modules.telephony.twilio_client.settings.TWILIO_CALL_RECORD", True
        )
        monkeypatch.setattr(
            "modules.telephony.twilio_client.settings.TWILIO_DIAL_TIMEOUT_SECONDS",
            30,
        )
        monkeypatch.setattr(
            "modules.telephony.twilio_client.settings.ENV", "development"
        )

        tw = TwilioClient.__new__(TwilioClient)
        tw._account_sid = "ACdummy0000000000000000000000000"
        tw._auth_token = "fake_token"
        tw._api_key_sid = ""
        tw._api_key_secret = ""
        tw._phone_number = "+15550001234"
        tw._public_base_url = "https://api.test"
        tw._livekit_sip_uri = "fake.sip.livekit.cloud"
        tw._auth_mode = "auth_token"
        tw._validator = None
        tw._client = MagicMock()

        # ACdummy → mock path (no real Twilio call).
        call = asyncio.get_event_loop().run_until_complete(
            tw.create_call(
                to_number="+15559876543",
                room_name="test-room",
                record=True,
            )
        )
        # The call object is returned from the mock path; what matters is
        # the kwargs that WOULD have been passed to twilio's calls.create.
        # In ACdummy mode the real `calls.create` is not called — so we
        # verify the kwarg-building logic by inspecting what the Twilio
        # call would contain if not mocked.  We test the non-dummy path
        # separately by calling the private kwargs builder.
        assert call.sid.startswith("CA")

    def test_recording_callback_path_in_kwargs(self, monkeypatch):
        """Direct inspection of the kwargs dict built by create_call."""
        import asyncio

        from modules.telephony.twilio_client import TwilioClient

        monkeypatch.setattr(
            "modules.telephony.twilio_client.settings.TWILIO_CALL_RECORD", True
        )
        monkeypatch.setattr(
            "modules.telephony.twilio_client.settings.TWILIO_DIAL_TIMEOUT_SECONDS", 30
        )
        monkeypatch.setattr(
            "modules.telephony.twilio_client.settings.ENV", "development"
        )
        monkeypatch.setattr(
            "modules.telephony.twilio_client.settings.TWILIO_AMD_ASYNC", False
        )

        tw = TwilioClient.__new__(TwilioClient)
        tw._account_sid = "ACreal0000000000000000000000000a"
        tw._auth_token = "tok"
        tw._api_key_sid = ""
        tw._api_key_secret = ""
        tw._phone_number = "+15550001234"
        tw._public_base_url = "https://api.test"
        tw._livekit_sip_uri = "fake.sip.livekit.cloud"
        tw._auth_mode = "auth_token"
        tw._validator = None

        captured = {}

        def _fake_create(**kwargs):
            captured.update(kwargs)

            class _FakeCall:
                sid = "CAabc"
                status = "queued"
                from_ = "+15550001234"
                to = "+15559876543"

            return _FakeCall()

        tw._client = MagicMock()
        tw._client.calls.create = _fake_create

        asyncio.get_event_loop().run_until_complete(
            tw.create_call(
                to_number="+15559876543",
                room_name="test-room",
                record=True,
            )
        )

        assert "recording_status_callback" in captured
        cb = captured["recording_status_callback"]
        assert "/webhooks/recording" in cb
        assert "kind=recording" not in cb  # old status-webhook piggyback gone
        assert captured.get("recording_status_callback_event") == ["completed"]
