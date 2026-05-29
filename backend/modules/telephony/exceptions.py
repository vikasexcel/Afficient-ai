"""Telephony module exceptions.

These are translated into HTTPException by the router so callers see
stable, well-typed errors regardless of which provider failed (Twilio
SDK, LiveKit SDK, or AI orchestrator).
"""

from __future__ import annotations


class TelephonyError(Exception):
    """Base error for telephony operations."""

    status_code: int = 500

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class TelephonyConfigError(TelephonyError):
    """Twilio credentials / SIP URI missing or invalid."""

    status_code = 500


class TwilioProviderError(TelephonyError):
    """Twilio REST API returned an error."""

    status_code = 502


class InvalidPhoneNumberError(TelephonyError):
    """The phone number failed E.164 validation."""

    status_code = 400


class InvalidWebhookSignatureError(TelephonyError):
    """``X-Twilio-Signature`` did not match the request body / URL."""

    status_code = 403


class CallNotFoundError(TelephonyError):
    """No ``telephony_calls`` row matched the lookup key."""

    status_code = 404
