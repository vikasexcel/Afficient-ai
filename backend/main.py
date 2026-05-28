from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.logging import configure_logging, get_logger
from common.security.protection import RateLimitMiddleware
from config.settings import settings
from modules.auth.router import router as auth_router
from modules.campaign.router import router as campaign_router
from modules.health.router import router as health_router
from modules.livekit.dependencies import shutdown_livekit_service
from modules.livekit.router import router as livekit_router
from modules.members.router import router as members_router
from modules.organization.router import router as organization_router
from modules.tts.router import router as tts_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log = get_logger("app")
    log.info("app.startup", name=settings.APP_NAME, env=settings.ENV)
    try:
        yield
    finally:
        await shutdown_livekit_service()
        log.info("app.shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0",
    lifespan=lifespan,
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
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
):
    app.include_router(r, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "environment": settings.ENV,
    }
