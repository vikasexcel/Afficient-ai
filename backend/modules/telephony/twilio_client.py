"""Thin async-friendly wrapper around the Twilio REST client.

The official ``twilio`` Python SDK is sync only. We keep that sync surface
(which is already retry- and timeout-aware) but call into it from
``asyncio.to_thread`` so the FastAPI event loop is never blocked.

Responsibilities
----------------
* Construct the SDK client lazily, once per process (see
  :func:`modules.telephony.dependencies.get_twilio_client`).
* Originate outbound calls with a webhook-driven status callback.
* Hang up in-flight calls (used by retries + admin cancel).
* Build TwiML for the ``/voice`` webhook so the PSTN leg is bridged
  into the AI agent's LiveKit room via the SIP gateway.
* Validate Twilio's ``X-Twilio-Signature`` header on inbound webhooks.

Error translation: every SDK exception is converted into
:class:`TwilioProviderError` (or :class:`TelephonyConfigError` for
misconfiguration) so the router doesn't need to know about
``TwilioRestException``.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioRestClient

from common.logging import get_logger
from config.settings import settings
from modules.telephony.exceptions import (
    TelephonyConfigError,
    TwilioProviderError,
)

log = get_logger("telephony.twilio")


@dataclass
class OriginatedCall:
    """Subset of ``twilio.rest.api.v2010.account.call.CallInstance``."""

    sid: str
    status: str | None = None
    from_: str | None = None
    to: str | None = None


class TwilioClient:
    """Process-wide Twilio REST + TwiML + signature helper."""

    def __init__(
        self,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        api_key_sid: str | None = None,
        api_key_secret: str | None = None,
        phone_number: str | None = None,
        public_base_url: str | None = None,
        livekit_sip_uri: str | None = None,
    ) -> None:
        self._account_sid = account_sid or settings.TWILIO_ACCOUNT_SID
        self._auth_token = auth_token or settings.TWILIO_AUTH_TOKEN
        self._api_key_sid = api_key_sid or settings.TWILIO_API_KEY_SID
        self._api_key_secret = (
            api_key_secret or settings.TWILIO_API_KEY_SECRET
        )
        self._phone_number = phone_number or settings.TWILIO_PHONE_NUMBER
        self._public_base_url = (
            (public_base_url or settings.TWILIO_PUBLIC_BASE_URL or "")
            .rstrip("/")
        )
        self._livekit_sip_uri = (
            livekit_sip_uri or settings.LIVEKIT_SIP_URI or ""
        ).strip()

        if not self._account_sid:
            raise TelephonyConfigError(
                "TWILIO_ACCOUNT_SID must be set (the AC... id from the "
                "Twilio console homepage — it is not a secret)"
            )

        # Two supported auth modes:
        #   1. API Key (preferred): scoped credential, rotatable without
        #      touching the master auth token.
        #   2. Auth Token: legacy / dev convenience.
        if self._api_key_sid and self._api_key_secret:
            self._client = TwilioRestClient(
                username=self._api_key_sid,
                password=self._api_key_secret,
                account_sid=self._account_sid,
            )
            self._auth_mode = "api_key"
        elif self._auth_token:
            self._client = TwilioRestClient(
                self._account_sid, self._auth_token
            )
            self._auth_mode = "auth_token"
        else:
            raise TelephonyConfigError(
                "Twilio auth required: set either "
                "TWILIO_API_KEY_SID + TWILIO_API_KEY_SECRET "
                "or TWILIO_AUTH_TOKEN"
            )

        if not self._phone_number:
            raise TelephonyConfigError(
                "TWILIO_PHONE_NUMBER must be set"
            )

        # X-Twilio-Signature is computed with the master AUTH_TOKEN,
        # never with the API Key secret. When the auth token is absent
        # we cannot validate signatures.
        self._validator = (
            RequestValidator(self._auth_token)
            if self._auth_token
            else None
        )
        if self._validator is None:
            log.warning(
                "telephony.twilio.signature_validation_disabled",
                reason="TWILIO_AUTH_TOKEN not set",
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def account_sid(self) -> str:
        return self._account_sid

    @property
    def auth_mode(self) -> str:
        return self._auth_mode

    @property
    def can_validate_signatures(self) -> bool:
        return self._validator is not None

    @property
    def phone_number(self) -> str:
        return self._phone_number

    @property
    def public_base_url(self) -> str:
        return self._public_base_url

    @property
    def livekit_sip_uri(self) -> str:
        return self._livekit_sip_uri

    # ------------------------------------------------------------------
    # Outbound origination
    # ------------------------------------------------------------------

    async def create_call(
        self,
        *,
        to_number: str,
        room_name: str,
        from_number: str | None = None,
        dial_timeout_seconds: int | None = None,
        record: bool | None = None,
        answering_machine_detection: bool = False,
        machine_detection_mode: str | None = None,
        machine_detection_timeout: int | None = None,
        status_callback_path: str = "/api/v1/telephony/webhooks/status",
        voice_callback_path: str = "/api/v1/telephony/webhooks/voice",
    ) -> OriginatedCall:
        """Originate one outbound call.

        We pass ``url`` (where Twilio fetches TwiML on answer) and
        ``status_callback`` (where Twilio POSTs lifecycle updates). The
        room name is forwarded as a query param on both so the webhook
        handlers can join the right LiveKit room without an extra DB
        lookup.
        """

        if not self._public_base_url:
            raise TelephonyConfigError(
                "TWILIO_PUBLIC_BASE_URL must be set for webhook callbacks"
            )

        if from_number is None:
            from_number = self._phone_number

        # Dev / CI: skip the real Twilio REST call when using placeholder
        # credentials (TWILIO_ACCOUNT_SID=ACdummy... in .env). Refuse to
        # mock in production so we never silently bill teams for calls
        # that never went out.
        if self._account_sid.startswith("ACdummy"):
            if settings.ENV.lower() in ("production", "prod"):
                raise TelephonyConfigError(
                    "TWILIO_ACCOUNT_SID is a dummy placeholder — refusing "
                    "to originate calls in production. Set real Twilio "
                    "credentials or disable telephony."
                )
            fake_sid = f"CA{uuid.uuid4().hex}"
            log.warning(
                "telephony.twilio.mock_originate",
                room=room_name,
                to=to_number,
                sid=fake_sid,
                env=settings.ENV,
            )
            return OriginatedCall(
                sid=fake_sid,
                status="queued",
                from_=from_number,
                to=to_number,
            )

        voice_url = (
            f"{self._public_base_url}{voice_callback_path}"
            f"?room={room_name}"
        )
        status_url = (
            f"{self._public_base_url}{status_callback_path}"
            f"?room={room_name}"
        )

        kwargs: dict[str, Any] = dict(
            to=to_number,
            from_=from_number,
            url=voice_url,
            status_callback=status_url,
            status_callback_method="POST",
            status_callback_event=[
                "initiated",
                "ringing",
                "answered",
                "completed",
            ],
            timeout=(
                dial_timeout_seconds or settings.TWILIO_DIAL_TIMEOUT_SECONDS
            ),
        )

        if (
            record
            if record is not None
            else settings.TWILIO_CALL_RECORD
        ):
            kwargs["record"] = True
            kwargs["recording_status_callback"] = (
                f"{self._public_base_url}{status_callback_path}"
                f"?room={room_name}&kind=recording"
            )

        # Answering Machine Detection. ``DetectMessageEnd`` makes Twilio wait
        # for the greeting/beep to finish before fetching the voice TwiML,
        # which is what we want before dropping a pre-recorded voicemail. The
        # detected classification arrives as ``AnsweredBy`` on the voice +
        # status webhooks (see modules.telephony.amd for the mapping).
        if answering_machine_detection:
            mode = machine_detection_mode or settings.TWILIO_AMD_MODE
            if mode not in ("Enable", "DetectMessageEnd"):
                mode = "DetectMessageEnd"
            kwargs["machine_detection"] = mode
            timeout = (
                machine_detection_timeout
                if machine_detection_timeout is not None
                else settings.TWILIO_AMD_TIMEOUT_SECONDS
            )
            # Twilio accepts 3..59 seconds.
            kwargs["machine_detection_timeout"] = max(3, min(59, int(timeout)))
            # Surface AnsweredBy on the status callback too (async AMD).
            kwargs["status_callback_event"] = [
                "initiated",
                "ringing",
                "answered",
                "completed",
            ]
            log.info(
                "telephony.twilio.amd_params",
                room=room_name,
                to=to_number,
                machine_detection=kwargs["machine_detection"],
                machine_detection_timeout=kwargs["machine_detection_timeout"],
            )

        try:
            call = await asyncio.to_thread(
                self._client.calls.create, **kwargs
            )
        except TwilioRestException as exc:
            log.warning(
                "telephony.twilio.create_failed",
                room=room_name,
                to=to_number,
                code=exc.code,
                status=exc.status,
                msg=exc.msg,
            )
            raise TwilioProviderError(
                f"twilio.calls.create failed ({exc.code}): {exc.msg}",
                status_code=502,
            ) from exc
        except Exception as exc:
            log.exception(
                "telephony.twilio.create_unexpected",
                room=room_name,
                to=to_number,
            )
            raise TwilioProviderError(
                f"unexpected twilio error: {exc}"
            ) from exc

        log.info(
            "telephony.twilio.created",
            room=room_name,
            to=to_number,
            from_=from_number,
            sid=call.sid,
            status=getattr(call, "status", None),
        )
        return OriginatedCall(
            sid=call.sid,
            status=getattr(call, "status", None),
            from_=getattr(call, "from_", None) or getattr(call, "from", None),
            to=getattr(call, "to", None),
        )

    async def hangup(self, call_sid: str) -> None:
        """Politely terminate an in-flight call."""

        def _do() -> None:
            self._client.calls(call_sid).update(status="completed")

        try:
            await asyncio.to_thread(_do)
        except TwilioRestException as exc:
            # If the call is already gone Twilio returns 404; treat as
            # success so the retry path is idempotent.
            if exc.status == 404:
                log.info(
                    "telephony.twilio.hangup_noop",
                    call_sid=call_sid,
                )
                return
            log.warning(
                "telephony.twilio.hangup_failed",
                call_sid=call_sid,
                code=exc.code,
                msg=exc.msg,
            )
            raise TwilioProviderError(
                f"twilio.calls({call_sid}).update failed: {exc.msg}"
            ) from exc

        log.info("telephony.twilio.hangup", call_sid=call_sid)

    # ------------------------------------------------------------------
    # TwiML
    # ------------------------------------------------------------------

    def build_voice_twiml(
        self,
        *,
        room_name: str,
        caller_id: str | None = None,
        opening_say: str | None = None,
    ) -> str:
        """Return TwiML the Twilio cloud will execute on call answer.

        When ``LIVEKIT_SIP_URI`` is configured we emit a ``<Dial><Sip>``
        verb that bridges the PSTN leg into the AI room over LiveKit's
        SIP gateway. Otherwise we fall back to a brief ``<Say>`` +
        ``<Hangup>`` so the call doesn't error out on the carrier (the
        operator is expected to wire SIP before going live).
        """

        sip = self._livekit_sip_uri
        caller_id = caller_id or self._phone_number

        if not sip:
            log.warning(
                "telephony.twilio.twiml.sip_missing",
                room=room_name,
            )
            msg = escape(
                opening_say
                or (
                    "Thanks for picking up. Our AI agent is not "
                    "available right now. Please try again later."
                )
            )
            return (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response>"
                f"<Say>{msg}</Say>"
                "<Hangup/>"
                "</Response>"
            )

        # LiveKit SIP convention: the room name becomes the SIP user.
        sip_uri = f"sip:{room_name}@{sip}"
        caller_id_attr = (
            f' callerId="{escape(caller_id)}"' if caller_id else ""
        )
        opening = (
            f"<Say>{escape(opening_say)}</Say>"
            if opening_say
            else ""
        )

        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"{opening}"
            f"<Dial answerOnBridge=\"true\"{caller_id_attr}>"
            f"<Sip>{escape(sip_uri)}</Sip>"
            "</Dial>"
            "</Response>"
        )

    def build_voicemail_twiml(
        self,
        *,
        recording_url: str,
    ) -> str:
        """TwiML that plays a pre-recorded voicemail message, then hangs up.

        Used when AMD classifies the answer as a machine/voicemail and the
        campaign has voicemail drop enabled. ``<Play>`` streams the configured
        recording into the call; ``<Hangup>`` ends the leg once playback
        completes so we don't leave dead air.
        """

        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Play>{escape(recording_url)}</Play>"
            "<Hangup/>"
            "</Response>"
        )

    # ------------------------------------------------------------------
    # Signature validation
    # ------------------------------------------------------------------

    def validate_signature(
        self,
        *,
        url: str,
        params: dict[str, Any] | None,
        signature: str | None,
    ) -> bool:
        """Verify ``X-Twilio-Signature`` against the canonical URL+params.

        Twilio constructs the signature from the full URL (including the
        scheme and querystring as it dialed) plus the sorted, concatenated
        POST form parameters.
        """

        if self._validator is None:
            # No master Auth Token configured — caller is expected to
            # gate the request another way (e.g. TWILIO_VALIDATE_SIGNATURE
            # = false in dev, or IP allowlist behind a proxy).
            return False
        if not signature:
            return False
        try:
            return self._validator.validate(url, params or {}, signature)
        except Exception:
            log.exception("telephony.twilio.validate.error", url=url)
            return False
