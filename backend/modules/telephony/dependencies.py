"""FastAPI dependencies for the telephony module.

Process-wide singletons for the Twilio REST client, the high-level
:class:`TelephonyService`, and the in-process :class:`CallAgentRegistry`.
``shutdown_telephony`` is invoked from the FastAPI lifespan handler so
any in-flight AI agent tasks get a clean stop signal on process exit.
"""

from __future__ import annotations

from fastapi import HTTPException

from modules.livekit.dependencies import get_livekit_service
from modules.telephony.agent_runner import (
    CallAgentRegistry,
    get_agent_registry,
    shutdown_agent_registry,
)
from modules.telephony.exceptions import TelephonyError
from modules.telephony.service import TelephonyService
from modules.telephony.twilio_client import TwilioClient

_twilio: TwilioClient | None = None
_service: TelephonyService | None = None


def get_twilio_client() -> TwilioClient:
    global _twilio
    if _twilio is None:
        try:
            _twilio = TwilioClient()
        except TelephonyError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.message
            ) from exc
    return _twilio


def get_call_agent_registry() -> CallAgentRegistry:
    return get_agent_registry()


def get_telephony_service() -> TelephonyService:
    global _service
    if _service is None:
        try:
            _service = TelephonyService(
                twilio=get_twilio_client(),
                livekit=get_livekit_service(),
                agent_registry=get_call_agent_registry(),
            )
        except TelephonyError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.message
            ) from exc
    return _service


async def shutdown_telephony() -> None:
    global _twilio, _service
    await shutdown_agent_registry()
    _service = None
    _twilio = None


def reset_telephony_singletons() -> None:
    """Test helper — wipe singletons without closing them."""

    global _twilio, _service
    _twilio = None
    _service = None
