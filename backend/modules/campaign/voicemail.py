"""Voicemail-drop configuration, validation, and recording management.

Three concerns, kept separable so the validation math is unit-testable
without a DB or network:

1. **Config resolution** — normalise a campaign ``voicemail_config`` blob into
   engine settings (:func:`resolve_voicemail_config`).
2. **Recording validation** — audio format + file size + URL shape/accessibility
   (:func:`validate_audio_format`, :func:`validate_file_size`,
   :func:`validate_voicemail_url`).
3. **Storage** — persist an uploaded recording to local disk and return a URL
   (:func:`store_recording`). S3 is a follow-up; the storage seam lives here so
   swapping the backend doesn't touch the API layer.
"""

from __future__ import annotations

import ipaddress
import os
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from common.logging import get_logger
from config.settings import settings

log = get_logger("campaign.voicemail")


class VoicemailValidationError(ValueError):
    """Raised when a voicemail recording / config fails validation.

    Carries an HTTP-friendly ``status_code`` (always 400/422-ish) so the
    router can translate it directly.
    """

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# AMD "unknown" fallback vocabulary
# --------------------------------------------------------------------------- #

FALLBACK_CONTINUE = "human"  # treat unknown like a human -> continue AI convo
FALLBACK_VOICEMAIL = "voicemail"  # treat unknown like voicemail -> drop
_VALID_FALLBACKS = frozenset({FALLBACK_CONTINUE, FALLBACK_VOICEMAIL})

DEFAULT_UNKNOWN_FALLBACK = FALLBACK_CONTINUE


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #


@dataclass
class VoicemailSettings:
    enabled: bool = False
    message_url: str | None = None
    retry_on_voicemail: bool = False
    unknown_fallback: str = DEFAULT_UNKNOWN_FALLBACK


def resolve_voicemail_config(config: dict | None) -> VoicemailSettings:
    """Normalise a campaign ``voicemail_config`` blob into typed settings."""

    cfg = config or {}
    fallback = str(
        cfg.get("amd_unknown_fallback") or DEFAULT_UNKNOWN_FALLBACK
    ).strip().lower()
    if fallback not in _VALID_FALLBACKS:
        fallback = DEFAULT_UNKNOWN_FALLBACK
    return VoicemailSettings(
        enabled=bool(cfg.get("voicemail_enabled", False)),
        message_url=cfg.get("voicemail_message_url") or None,
        retry_on_voicemail=bool(cfg.get("retry_on_voicemail", False)),
        unknown_fallback=fallback,
    )


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #


def _allowed_formats() -> set[str]:
    return {
        f.strip().lower()
        for f in (settings.VOICEMAIL_ALLOWED_FORMATS or "").split(",")
        if f.strip()
    }


def _ext_of(name: str | None) -> str:
    if not name:
        return ""
    return os.path.splitext(name)[1].lstrip(".").lower()


def validate_audio_format(
    *, filename: str | None, content_type: str | None
) -> str:
    """Validate that an upload is an allowed audio format.

    Accepts when *either* the file extension or the content-type subtype is in
    the allow-list. Returns the detected format token (lower-cased) for
    bookkeeping. Raises :class:`VoicemailValidationError` otherwise.
    """

    allowed = _allowed_formats()
    ext = _ext_of(filename)
    # content_type like "audio/mpeg" -> subtype "mpeg".
    subtype = ""
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if "/" in ct:
            major, subtype = ct.split("/", 1)
            if major and major != "audio" and subtype not in allowed and ext not in allowed:
                raise VoicemailValidationError(
                    f"unsupported content-type '{content_type}': expected audio"
                )

    if ext and ext in allowed:
        return ext
    if subtype and subtype in allowed:
        return subtype

    raise VoicemailValidationError(
        "unsupported audio format: allowed formats are "
        f"{sorted(allowed)} (got filename={filename!r}, "
        f"content_type={content_type!r})"
    )


def validate_file_size(size_bytes: int) -> None:
    """Reject empty or oversized uploads."""

    if size_bytes <= 0:
        raise VoicemailValidationError("uploaded file is empty")
    if size_bytes > settings.VOICEMAIL_MAX_BYTES:
        raise VoicemailValidationError(
            "file too large: "
            f"{size_bytes} bytes exceeds max {settings.VOICEMAIL_MAX_BYTES}",
            status_code=413,
        )


def _is_twilio_unreachable_host(host: str) -> str | None:
    """Return a reason string when ``host`` is not reachable from Twilio's cloud.

    Twilio ``<Play>`` is fetched by Twilio's servers over the public internet,
    so loopback / private / link-local addresses and ``localhost`` / ``*.local``
    names will never resolve for them even though they work from this box.
    Returns ``None`` when the host looks publicly routable.
    """

    host = (host or "").strip().lower()
    # Strip an optional :port and surrounding brackets (IPv6).
    if host.startswith("["):
        host = host.split("]", 1)[0].lstrip("[")
    elif ":" in host and host.count(":") == 1:
        host = host.split(":", 1)[0]

    if not host:
        return "missing host"
    if host in ("localhost",) or host.endswith(".local") or host.endswith(
        ".localhost"
    ):
        return f"'{host}' is not resolvable from Twilio (local-only host)"

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # A DNS name (not a literal IP). Require a dotted FQDN so bare
        # single-label hostnames (e.g. "backend") are rejected.
        if "." not in host:
            return f"'{host}' is not a public fully-qualified domain"
        return None

    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    ):
        return f"'{host}' is a private / non-public IP address"
    return None


def validate_voicemail_url(
    url: str,
    *,
    network_check: bool | None = None,
    require_public: bool | None = None,
) -> str:
    """Validate a configured voicemail recording URL.

    Always checks the URL *shape* (http/https + host + audio-looking path).
    When ``require_public`` (defaulting to ``VOICEMAIL_REQUIRE_PUBLIC_URL``) is
    enabled, rejects ``file://`` / localhost / private / link-local hosts that
    Twilio's cloud could never fetch. When ``network_check`` (defaulting to
    ``VOICEMAIL_URL_NETWORK_CHECK``) is enabled, also performs a best-effort
    HEAD request to confirm the URL is reachable and serves audio.
    """

    url = (url or "").strip()
    if not url:
        raise VoicemailValidationError("voicemail_message_url is empty")

    parsed = urlparse(url)
    if parsed.scheme == "file":
        raise VoicemailValidationError(
            "voicemail_message_url is a file:// URL — Twilio cannot fetch "
            "local files; host the recording on a public HTTPS URL"
        )
    if parsed.scheme not in ("http", "https"):
        raise VoicemailValidationError(
            "voicemail_message_url must be an http(s) URL"
        )
    if not parsed.netloc:
        raise VoicemailValidationError(
            "voicemail_message_url is missing a host"
        )

    want_public = (
        settings.VOICEMAIL_REQUIRE_PUBLIC_URL
        if require_public is None
        else require_public
    )
    if want_public:
        reason = _is_twilio_unreachable_host(parsed.hostname or parsed.netloc)
        if reason:
            raise VoicemailValidationError(
                f"voicemail_message_url is not publicly reachable: {reason}. "
                "Twilio plays recordings from its own cloud, so the URL must "
                "be a public HTTPS address."
            )

    allowed = _allowed_formats()
    ext = _ext_of(parsed.path)
    # A path extension is optional (CDNs often omit it); when present it must
    # be an allowed audio format.
    if ext and ext not in allowed:
        raise VoicemailValidationError(
            f"voicemail_message_url has unsupported extension '.{ext}'"
        )

    do_check = (
        settings.VOICEMAIL_URL_NETWORK_CHECK
        if network_check is None
        else network_check
    )
    if do_check:
        _head_check_url(url, allowed)

    return url


def _head_check_url(url: str, allowed: set[str]) -> None:
    """Best-effort reachability + content-type check (network)."""

    try:
        import httpx
    except Exception:  # pragma: no cover - httpx is a transitive dep
        return

    try:
        resp = httpx.head(url, timeout=5.0, follow_redirects=True)
        if resp.status_code >= 400:
            # Some hosts reject HEAD — retry with a ranged GET.
            resp = httpx.get(
                url, timeout=5.0, follow_redirects=True,
                headers={"Range": "bytes=0-0"},
            )
    except Exception as exc:  # network failure -> not accessible
        raise VoicemailValidationError(
            f"voicemail_message_url is not accessible: {exc}",
            status_code=422,
        ) from exc

    if resp.status_code >= 400:
        raise VoicemailValidationError(
            f"voicemail_message_url returned HTTP {resp.status_code}",
            status_code=422,
        )

    ctype = (resp.headers.get("content-type") or "").lower()
    if ctype and "audio" not in ctype:
        subtype = ctype.split(";")[0].split("/")[-1].strip()
        if subtype not in allowed:
            raise VoicemailValidationError(
                f"voicemail_message_url is not audio (content-type {ctype})",
                status_code=422,
            )


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def store_recording(
    *,
    campaign_id: str,
    data: bytes,
    fmt: str,
) -> str:
    """Persist an uploaded recording and return a Twilio-reachable URL.

    Writes to ``VOICEMAIL_UPLOAD_DIR`` on local disk (S3 is a follow-up) and
    returns ``{TWILIO_PUBLIC_BASE_URL}{VOICEMAIL_PUBLIC_ROUTE}/{filename}``.
    The app mounts ``VOICEMAIL_UPLOAD_DIR`` at ``VOICEMAIL_PUBLIC_ROUTE`` (see
    ``main.py``) so Twilio ``<Play>`` can fetch the file.

    Refuses to emit an un-fetchable URL: a ``file://`` path or a localhost /
    private ``TWILIO_PUBLIC_BASE_URL`` would make the voicemail drop silently
    play nothing. Centralised here so swapping to S3 only touches this function.
    """

    base_dir = settings.VOICEMAIL_UPLOAD_DIR
    os.makedirs(base_dir, exist_ok=True)
    fname = f"{campaign_id}-{uuid.uuid4().hex[:12]}.{fmt}"
    path = os.path.join(base_dir, fname)

    public_base = (settings.TWILIO_PUBLIC_BASE_URL or "").rstrip("/")
    route = "/" + settings.VOICEMAIL_PUBLIC_ROUTE.strip("/")
    require_public = settings.VOICEMAIL_REQUIRE_PUBLIC_URL

    if not public_base:
        raise VoicemailValidationError(
            "cannot store voicemail upload: TWILIO_PUBLIC_BASE_URL is not set, "
            "so the recording would not be reachable by Twilio. Set a public "
            "base URL or configure voicemail_message_url directly.",
            status_code=422,
        )

    served_url = f"{public_base}{route}/{fname}"
    if require_public:
        # Validate the resulting URL shape + public reachability before we
        # commit the file, so a localhost base URL fails loudly here.
        validate_voicemail_url(served_url, network_check=False)

    with open(path, "wb") as fh:
        fh.write(data)

    log.info(
        "campaign.voicemail.stored",
        campaign_id=campaign_id,
        filename=fname,
        bytes=len(data),
        url=served_url,
    )
    return served_url
