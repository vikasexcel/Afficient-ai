from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.logging import configure_logging, get_logger
from common.security.protection import RateLimitMiddleware
from config.settings import settings
from modules.ai.dependencies import shutdown_ai
from modules.ai.router import router as ai_router
from modules.auth.router import router as auth_router
from modules.campaign.router import router as campaign_router
from modules.health.router import router as health_router
from modules.livekit.dependencies import shutdown_livekit_service
from modules.livekit.router import router as livekit_router
from modules.members.router import router as members_router
from modules.organization.router import router as organization_router
from modules.stt.router import router as stt_router
from modules.telephony.dependencies import shutdown_telephony
from modules.telephony.router import router as telephony_router
from modules.playbook.router import router as playbook_router
from modules.tts.router import router as tts_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log = get_logger("app")
    log.info("app.startup", name=settings.APP_NAME, env=settings.ENV)

    # Loud guard rails for production deployments: refuse to start (or
    # at least scream) when known-unsafe combinations are detected.
    if settings.ENV.lower() in ("production", "prod"):
        if not settings.TWILIO_VALIDATE_SIGNATURE:
            log.error(
                "app.startup.unsafe",
                reason="TWILIO_VALIDATE_SIGNATURE must be true in production",
            )
        if (settings.TWILIO_ACCOUNT_SID or "").startswith("ACdummy"):
            log.error(
                "app.startup.unsafe",
                reason="TWILIO_ACCOUNT_SID is a dummy placeholder",
            )
        if not settings.JWT_SECRET or len(settings.JWT_SECRET) < 32:
            log.error(
                "app.startup.unsafe",
                reason="JWT_SECRET is missing or shorter than 32 chars",
            )

    try:
        yield
    finally:
        await shutdown_telephony()
        await shutdown_ai()
        await shutdown_livekit_service()
        log.info("app.shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0",
    lifespan=lifespan,
)
app.add_middleware(RateLimitMiddleware)
_is_prod = (settings.ENV or "").lower() == "production"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://localhost:20197",
        "http://127.0.0.1:20197",
        "http://localhost:20198",
        "http://127.0.0.1:20198",
    ],
    # In non-production, also accept any localhost/127.0.0.1 port so Vite
    # fallbacks (e.g. 20198 when 20197 is taken) don't break preflights.
    allow_origin_regex=(
        None if _is_prod else r"^http://(localhost|127\.0\.0\.1):\d+$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


for r in (
    health_router,
    auth_router,
    campaign_router,
    members_router,
    organization_router,
    livekit_router,
    tts_router,
    stt_router,
    ai_router,
    telephony_router,
    playbook_router,
):
    app.include_router(r, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "environment": settings.ENV,
    }
