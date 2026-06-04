"""Unit tests for voicemail-drop config + validation + retry policy.

Pure-Python — covers:

* ``resolve_voicemail_config`` normalisation.
* recording validation (audio format, file size, URL shape).
* the campaign ``retry_on_voicemail`` policy applied by ``process_outcome``.
"""

from __future__ import annotations

import pytest

from modules.campaign.retry import process_outcome
from modules.campaign.voicemail import (
    VoicemailValidationError,
    resolve_voicemail_config,
    validate_audio_format,
    validate_file_size,
    validate_voicemail_url,
)
from config.settings import settings


pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #


def test_resolve_voicemail_config_defaults():
    s = resolve_voicemail_config(None)
    assert s.enabled is False
    assert s.message_url is None
    assert s.retry_on_voicemail is False
    assert s.unknown_fallback == "human"


def test_resolve_voicemail_config_values():
    s = resolve_voicemail_config(
        {
            "voicemail_enabled": True,
            "voicemail_message_url": "https://cdn.test/vm.mp3",
            "retry_on_voicemail": True,
            "amd_unknown_fallback": "voicemail",
        }
    )
    assert s.enabled is True
    assert s.message_url == "https://cdn.test/vm.mp3"
    assert s.retry_on_voicemail is True
    assert s.unknown_fallback == "voicemail"


def test_resolve_voicemail_config_bad_fallback_falls_back():
    s = resolve_voicemail_config({"amd_unknown_fallback": "nonsense"})
    assert s.unknown_fallback == "human"


# --------------------------------------------------------------------------- #
# Audio format validation
# --------------------------------------------------------------------------- #


def test_validate_audio_format_accepts_by_extension():
    assert validate_audio_format(filename="hello.mp3", content_type=None) == "mp3"
    assert validate_audio_format(filename="hi.wav", content_type=None) == "wav"


def test_validate_audio_format_accepts_by_content_type():
    fmt = validate_audio_format(filename="blob", content_type="audio/mpeg")
    assert fmt == "mpeg"


def test_validate_audio_format_rejects_unknown():
    with pytest.raises(VoicemailValidationError):
        validate_audio_format(filename="virus.exe", content_type=None)
    with pytest.raises(VoicemailValidationError):
        validate_audio_format(filename="doc.pdf", content_type="application/pdf")


# --------------------------------------------------------------------------- #
# File size validation
# --------------------------------------------------------------------------- #


def test_validate_file_size_rejects_empty():
    with pytest.raises(VoicemailValidationError):
        validate_file_size(0)


def test_validate_file_size_rejects_oversized():
    with pytest.raises(VoicemailValidationError) as exc:
        validate_file_size(settings.VOICEMAIL_MAX_BYTES + 1)
    assert exc.value.status_code == 413


def test_validate_file_size_accepts_normal():
    validate_file_size(1024)  # no raise


# --------------------------------------------------------------------------- #
# URL validation (shape only — network check off)
# --------------------------------------------------------------------------- #


def test_validate_voicemail_url_accepts_https_audio():
    url = validate_voicemail_url(
        "https://cdn.test/path/vm.mp3", network_check=False
    )
    assert url == "https://cdn.test/path/vm.mp3"


def test_validate_voicemail_url_accepts_no_extension():
    # CDNs often omit the extension; shape check still passes.
    url = validate_voicemail_url(
        "https://cdn.test/recordings/abc123", network_check=False
    )
    assert url.endswith("abc123")


def test_validate_voicemail_url_rejects_non_http():
    with pytest.raises(VoicemailValidationError):
        validate_voicemail_url("ftp://cdn.test/vm.mp3", network_check=False)
    with pytest.raises(VoicemailValidationError):
        validate_voicemail_url("not-a-url", network_check=False)


def test_validate_voicemail_url_rejects_bad_extension():
    with pytest.raises(VoicemailValidationError):
        validate_voicemail_url(
            "https://cdn.test/vm.exe", network_check=False
        )


# --------------------------------------------------------------------------- #
# Public-reachability validation (Twilio fetches recordings from its cloud)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///var/data/vm.mp3",
        "http://localhost:8000/vm.mp3",
        "http://localhost/vm.mp3",
        "http://127.0.0.1/vm.mp3",
        "http://127.0.0.1:9000/vm.mp3",
        "http://10.0.0.5/vm.mp3",
        "http://192.168.1.10/vm.mp3",
        "http://172.16.4.2/vm.mp3",
        "http://169.254.1.1/vm.mp3",  # link-local
        "http://backend/vm.mp3",  # bare single-label host
        "http://app.local/vm.mp3",
    ],
)
def test_validate_voicemail_url_rejects_unreachable(bad_url):
    with pytest.raises(VoicemailValidationError):
        validate_voicemail_url(bad_url, network_check=False, require_public=True)


@pytest.mark.parametrize(
    "good_url",
    [
        "https://cdn.test/vm.mp3",
        "https://api.aifuturegroup.co/media/voicemail/x.mp3",
        "http://8.8.8.8/vm.mp3",  # public literal IP
    ],
)
def test_validate_voicemail_url_accepts_public(good_url):
    assert (
        validate_voicemail_url(good_url, network_check=False, require_public=True)
        == good_url
    )


def test_validate_voicemail_url_localhost_ok_when_not_requiring_public():
    # When public reachability isn't required (isolated dev), localhost passes.
    url = validate_voicemail_url(
        "http://localhost:8000/vm.mp3", network_check=False, require_public=False
    )
    assert url.startswith("http://localhost")


# --------------------------------------------------------------------------- #
# store_recording — emits a Twilio-reachable served URL, refuses file://
# --------------------------------------------------------------------------- #


def test_store_recording_builds_public_served_url(tmp_path, monkeypatch):
    from modules.campaign import voicemail as vm

    monkeypatch.setattr(settings, "VOICEMAIL_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings, "TWILIO_PUBLIC_BASE_URL", "https://api.aifuturegroup.co"
    )
    monkeypatch.setattr(settings, "VOICEMAIL_PUBLIC_ROUTE", "/media/voicemail")
    monkeypatch.setattr(settings, "VOICEMAIL_REQUIRE_PUBLIC_URL", True)

    url = vm.store_recording(campaign_id="abc", data=b"ID3audio" * 64, fmt="mp3")
    assert url.startswith("https://api.aifuturegroup.co/media/voicemail/")
    assert url.endswith(".mp3")
    assert "file://" not in url


def test_store_recording_refuses_without_public_base(tmp_path, monkeypatch):
    from modules.campaign import voicemail as vm

    monkeypatch.setattr(settings, "VOICEMAIL_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "TWILIO_PUBLIC_BASE_URL", "")
    with pytest.raises(VoicemailValidationError):
        vm.store_recording(campaign_id="abc", data=b"x" * 32, fmt="mp3")


def test_store_recording_refuses_localhost_base(tmp_path, monkeypatch):
    from modules.campaign import voicemail as vm

    monkeypatch.setattr(settings, "VOICEMAIL_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(
        settings, "TWILIO_PUBLIC_BASE_URL", "http://localhost:8000"
    )
    monkeypatch.setattr(settings, "VOICEMAIL_REQUIRE_PUBLIC_URL", True)
    with pytest.raises(VoicemailValidationError):
        vm.store_recording(campaign_id="abc", data=b"x" * 32, fmt="mp3")


# --------------------------------------------------------------------------- #
# retry_on_voicemail policy (process_outcome)
# --------------------------------------------------------------------------- #


class _FakeExecution:
    def __init__(self, attempt_number: int = 1):
        self.attempt_number = attempt_number
        self.context = None
        self.status = "running"
        self.outcome = None
        self.retry_status = "pending"
        self.next_retry_at = None
        self.last_failure_reason = None


_CFG = {"max_attempts": 3, "retry_interval_minutes": 15, "backoff_strategy": "fixed"}


def test_voicemail_completes_when_retry_disabled():
    ex = _FakeExecution()
    process_outcome(
        None,
        ex,
        "voicemail",
        retry_config=_CFG,
        voicemail_config={"retry_on_voicemail": False},
        commit=False,
    )
    assert ex.status == "completed"
    assert ex.retry_status == "completed"
    assert ex.next_retry_at is None


def test_voicemail_retries_when_enabled():
    ex = _FakeExecution()
    process_outcome(
        None,
        ex,
        "voicemail",
        retry_config=_CFG,
        voicemail_config={"retry_on_voicemail": True},
        commit=False,
    )
    assert ex.status == "failed"
    assert ex.retry_status == "scheduled"
    assert ex.attempt_number == 2
    assert ex.next_retry_at is not None


def test_voicemail_legacy_behaviour_without_config():
    # No voicemail_config -> preserve the legacy "voicemail is retryable" path.
    ex = _FakeExecution()
    process_outcome(None, ex, "voicemail", retry_config=_CFG, commit=False)
    assert ex.status == "failed"
    assert ex.retry_status == "scheduled"
