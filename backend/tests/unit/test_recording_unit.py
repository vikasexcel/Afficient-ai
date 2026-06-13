"""Unit tests for call recording — S3 upload, service webhook handler.

Covers:
* S3RecordingClient — upload_from_url, presigned_url, upload_bytes, delete
* TelephonyService.handle_recording_webhook — happy path, missing fields,
  non-completed status, unknown CallSid, S3 not configured
* TelephonyCallRepository.update_recording
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_recording_params(
    *,
    call_sid: str | None = None,
    recording_sid: str | None = None,
    recording_url: str | None = None,
    status: str = "completed",
    duration: str = "42",
) -> dict:
    return {
        "CallSid": call_sid or f"CA{uuid.uuid4().hex}",
        "RecordingSid": recording_sid or f"RE{uuid.uuid4().hex}",
        "RecordingUrl": recording_url
        or "https://api.twilio.com/2010-04-01/Accounts/ACfake/Recordings/REfake",
        "RecordingStatus": status,
        "RecordingDuration": duration,
    }


# ---------------------------------------------------------------------------
# S3RecordingClient unit tests
# ---------------------------------------------------------------------------


class TestS3RecordingClient:
    """Pure-mock tests — no real boto3 / HTTP calls."""

    def _make_client(self, *, bucket: str = "test-bucket") -> "S3RecordingClient":
        from modules.storage.s3_client import S3RecordingClient

        with patch("modules.storage.s3_client.boto3") as mock_boto3:
            mock_boto3.client.return_value = MagicMock()
            client = S3RecordingClient.__new__(S3RecordingClient)
            client._client = MagicMock()
            client._bucket = bucket
        return client

    def test_presigned_url_returns_string(self):
        client = self._make_client()
        client._client.generate_presigned_url.return_value = (
            "https://s3.eu-west-2.amazonaws.com/test-bucket/key.mp3?X-Amz=..."
        )
        url = client.presigned_url("recordings/org/campaign/CA1/RE1.mp3", expires=900)
        assert url.startswith("https://")
        client._client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "recordings/org/campaign/CA1/RE1.mp3"},
            ExpiresIn=900,
        )

    def test_upload_bytes_calls_put_object(self):
        client = self._make_client()
        key = asyncio.get_event_loop().run_until_complete(
            client.upload_bytes(b"audio_data", "recordings/test.mp3")
        )
        assert key == "recordings/test.mp3"
        client._client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="recordings/test.mp3",
            Body=b"audio_data",
            ContentType="audio/mpeg",
        )

    def test_delete_calls_delete_object(self):
        client = self._make_client()
        asyncio.get_event_loop().run_until_complete(
            client.delete("recordings/to-delete.mp3")
        )
        client._client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="recordings/to-delete.mp3"
        )

    def test_upload_from_url_downloads_and_uploads(self):
        client = self._make_client()
        fake_audio = b"\xff\xfb\x00" * 100

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.content = fake_audio

        async def _fake_get(*args, **kwargs):
            return fake_response

        fake_http = AsyncMock()
        fake_http.__aenter__ = AsyncMock(return_value=fake_http)
        fake_http.__aexit__ = AsyncMock(return_value=False)
        fake_http.get = _fake_get

        with patch("modules.storage.s3_client.httpx.AsyncClient", return_value=fake_http):
            key = asyncio.get_event_loop().run_until_complete(
                client.upload_from_url(
                    "https://api.twilio.com/Recordings/REfake.mp3",
                    "recordings/test.mp3",
                    twilio_account_sid="ACfake",
                    twilio_auth_token="tok",
                )
            )

        assert key == "recordings/test.mp3"
        client._client.put_object.assert_called_once()
        call_kwargs = client._client.put_object.call_args.kwargs
        assert call_kwargs["Body"] == fake_audio

    def test_presigned_url_reraises_on_botocore_error(self):
        from botocore.exceptions import ClientError

        client = self._make_client()
        client._client.generate_presigned_url.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GeneratePresignedUrl"
        )
        with pytest.raises(ClientError):
            client.presigned_url("missing/key.mp3")


# ---------------------------------------------------------------------------
# Repository.update_recording
# ---------------------------------------------------------------------------


class TestUpdateRecording:
    def test_update_recording_sets_fields(self):
        from modules.telephony.model import TelephonyCall
        from modules.telephony.repository import TelephonyCallRepository

        db = MagicMock()
        row = TelephonyCall()
        TelephonyCallRepository.update_recording(
            db,
            row,
            recording_sid="REabc",
            recording_url="recordings/org/cam/CA1/REabc.mp3",
            recording_duration_seconds=42,
        )
        assert row.recording_sid == "REabc"
        assert row.recording_url == "recordings/org/cam/CA1/REabc.mp3"
        assert row.recording_duration_seconds == 42
        assert row.recording_uploaded_at is not None
        db.flush.assert_called_once()

    def test_update_recording_explicit_uploaded_at(self):
        from modules.telephony.model import TelephonyCall
        from modules.telephony.repository import TelephonyCallRepository

        db = MagicMock()
        row = TelephonyCall()
        ts = datetime(2026, 6, 13, 12, 0, 0)
        TelephonyCallRepository.update_recording(
            db, row, recording_sid="RE1", recording_url="key", recording_uploaded_at=ts
        )
        assert row.recording_uploaded_at == ts


# ---------------------------------------------------------------------------
# handle_recording_webhook — service-layer unit tests
# ---------------------------------------------------------------------------


def _make_service():
    """Build a bare-minimum TelephonyService with all deps mocked out."""
    from modules.telephony.service import TelephonyService

    svc = TelephonyService.__new__(TelephonyService)
    svc._twilio = MagicMock()
    svc._twilio._client = MagicMock()
    svc._livekit = MagicMock()
    svc._agent_registry = MagicMock()
    return svc


class TestHandleRecordingWebhook:
    """Tests for TelephonyService.handle_recording_webhook."""

    # ------------------------------------------------------------------ #
    # non-completed status — early return
    # ------------------------------------------------------------------ #

    def test_non_completed_status_is_noop(self):
        svc = _make_service()
        params = _make_recording_params(status="in-progress")

        with patch("modules.telephony.service.get_s3_client") as mock_s3:
            asyncio.get_event_loop().run_until_complete(
                svc.handle_recording_webhook(params=params)
            )
            mock_s3.assert_not_called()

    # ------------------------------------------------------------------ #
    # Missing required fields
    # ------------------------------------------------------------------ #

    def test_missing_call_sid_is_noop(self):
        svc = _make_service()
        params = {
            "RecordingStatus": "completed",
            "RecordingSid": "REfake",
            "RecordingUrl": "https://api.twilio.com/Recordings/REfake",
        }
        with patch("modules.telephony.service.get_s3_client") as mock_s3:
            asyncio.get_event_loop().run_until_complete(
                svc.handle_recording_webhook(params=params)
            )
            mock_s3.assert_not_called()

    def test_missing_recording_sid_is_noop(self):
        svc = _make_service()
        params = {
            "CallSid": "CAfake",
            "RecordingStatus": "completed",
            "RecordingUrl": "https://api.twilio.com/Recordings/REfake",
        }
        with patch("modules.telephony.service.get_s3_client") as mock_s3:
            asyncio.get_event_loop().run_until_complete(
                svc.handle_recording_webhook(params=params)
            )
            mock_s3.assert_not_called()

    # ------------------------------------------------------------------ #
    # Unknown CallSid — row not in DB
    # ------------------------------------------------------------------ #

    def test_unknown_call_sid_is_noop(self):
        svc = _make_service()
        params = _make_recording_params()

        with (
            patch(
                "modules.telephony.service.TelephonyService._fetch_by_sid",
                return_value=None,
            ),
            patch("modules.telephony.service.get_s3_client") as mock_s3,
        ):
            asyncio.get_event_loop().run_until_complete(
                svc.handle_recording_webhook(params=params)
            )
            mock_s3.assert_not_called()

    # ------------------------------------------------------------------ #
    # S3 bucket not configured
    # ------------------------------------------------------------------ #

    def test_no_s3_bucket_is_noop(self, monkeypatch):
        svc = _make_service()
        params = _make_recording_params()
        row = MagicMock()

        monkeypatch.setattr(
            "modules.telephony.service.settings.S3_RECORDINGS_BUCKET", ""
        )

        with (
            patch(
                "modules.telephony.service.TelephonyService._fetch_by_sid",
                return_value=row,
            ),
            patch("modules.telephony.service.get_s3_client") as mock_s3,
        ):
            asyncio.get_event_loop().run_until_complete(
                svc.handle_recording_webhook(params=params)
            )
            mock_s3.assert_not_called()

    # ------------------------------------------------------------------ #
    # Happy path — upload succeeds
    # ------------------------------------------------------------------ #

    def test_happy_path_uploads_to_s3_and_updates_db(self, monkeypatch):
        svc = _make_service()
        call_sid = f"CA{uuid.uuid4().hex}"
        rec_sid = f"RE{uuid.uuid4().hex}"
        params = _make_recording_params(
            call_sid=call_sid, recording_sid=rec_sid, duration="60"
        )

        org_id = uuid.uuid4()
        campaign_id = uuid.uuid4()
        fake_row = MagicMock()
        fake_row.organization_id = org_id
        fake_row.campaign_id = campaign_id

        monkeypatch.setattr(
            "modules.telephony.service.settings.S3_RECORDINGS_BUCKET",
            "tellaigent-voice-recording",
        )
        monkeypatch.setattr(
            "modules.telephony.service.settings.RECORDING_DELETE_FROM_TWILIO",
            False,
        )

        mock_s3_instance = AsyncMock()
        mock_s3_instance.upload_from_url = AsyncMock(
            return_value=f"recordings/{org_id}/{campaign_id}/{call_sid}/{rec_sid}.mp3"
        )

        updated_rows = []

        def _fake_db_scope():
            from contextlib import contextmanager

            @contextmanager
            def _ctx():
                db = MagicMock()
                yield db
                db.commit()

            return _ctx()

        with (
            patch(
                "modules.telephony.service.TelephonyService._fetch_by_sid",
                return_value=fake_row,
            ),
            patch(
                "modules.telephony.service.get_s3_client",
                return_value=mock_s3_instance,
            ),
            patch(
                "modules.telephony.service.TelephonyCallRepository.get_by_sid",
                return_value=fake_row,
            ),
            patch(
                "modules.telephony.service.TelephonyCallRepository.update_recording"
            ) as mock_update,
            patch(
                "modules.telephony.service.TelephonyEventRepository.append"
            ) as mock_event,
            patch("modules.telephony.service._db_scope", _fake_db_scope),
        ):
            asyncio.get_event_loop().run_until_complete(
                svc.handle_recording_webhook(params=params)
            )

            mock_s3_instance.upload_from_url.assert_awaited_once()
            upload_call = mock_s3_instance.upload_from_url.call_args
            assert f"{call_sid}/{rec_sid}.mp3" in upload_call.args[1]

            mock_update.assert_called_once()
            update_kwargs = mock_update.call_args.kwargs
            assert update_kwargs["recording_sid"] == rec_sid
            assert update_kwargs["recording_duration_seconds"] == 60

            mock_event.assert_called_once()
            event_kwargs = mock_event.call_args.kwargs
            assert event_kwargs["event_type"] == "recording_uploaded"

    # ------------------------------------------------------------------ #
    # S3 upload failure — no DB update
    # ------------------------------------------------------------------ #

    def test_s3_upload_failure_does_not_update_db(self, monkeypatch):
        svc = _make_service()
        params = _make_recording_params()
        fake_row = MagicMock()
        fake_row.organization_id = uuid.uuid4()
        fake_row.campaign_id = uuid.uuid4()

        monkeypatch.setattr(
            "modules.telephony.service.settings.S3_RECORDINGS_BUCKET",
            "tellaigent-voice-recording",
        )

        mock_s3_instance = AsyncMock()
        mock_s3_instance.upload_from_url = AsyncMock(
            side_effect=ConnectionError("S3 unreachable")
        )

        with (
            patch(
                "modules.telephony.service.TelephonyService._fetch_by_sid",
                return_value=fake_row,
            ),
            patch(
                "modules.telephony.service.get_s3_client",
                return_value=mock_s3_instance,
            ),
            patch(
                "modules.telephony.service.TelephonyCallRepository.update_recording"
            ) as mock_update,
        ):
            asyncio.get_event_loop().run_until_complete(
                svc.handle_recording_webhook(params=params)
            )
            mock_update.assert_not_called()

    # ------------------------------------------------------------------ #
    # delete_from_twilio is called when enabled
    # ------------------------------------------------------------------ #

    def test_deletes_twilio_recording_when_enabled(self, monkeypatch):
        svc = _make_service()
        rec_sid = f"RE{uuid.uuid4().hex}"
        params = _make_recording_params(recording_sid=rec_sid)
        fake_row = MagicMock()
        fake_row.organization_id = uuid.uuid4()
        fake_row.campaign_id = uuid.uuid4()

        monkeypatch.setattr(
            "modules.telephony.service.settings.S3_RECORDINGS_BUCKET",
            "tellaigent-voice-recording",
        )
        monkeypatch.setattr(
            "modules.telephony.service.settings.RECORDING_DELETE_FROM_TWILIO",
            True,
        )

        mock_s3_instance = AsyncMock()
        mock_s3_instance.upload_from_url = AsyncMock(return_value="key")

        def _fake_db_scope():
            from contextlib import contextmanager

            @contextmanager
            def _ctx():
                yield MagicMock()

            return _ctx()

        with (
            patch(
                "modules.telephony.service.TelephonyService._fetch_by_sid",
                return_value=fake_row,
            ),
            patch(
                "modules.telephony.service.get_s3_client",
                return_value=mock_s3_instance,
            ),
            patch(
                "modules.telephony.service.TelephonyCallRepository.get_by_sid",
                return_value=fake_row,
            ),
            patch("modules.telephony.service.TelephonyCallRepository.update_recording"),
            patch("modules.telephony.service.TelephonyEventRepository.append"),
            patch("modules.telephony.service._db_scope", _fake_db_scope),
            patch.object(
                svc,
                "_delete_twilio_recording",
                new=AsyncMock(),
            ) as mock_del,
        ):
            asyncio.get_event_loop().run_until_complete(
                svc.handle_recording_webhook(params=params)
            )
            mock_del.assert_awaited_once_with(rec_sid)
