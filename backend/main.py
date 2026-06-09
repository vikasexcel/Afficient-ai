import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from common.logging import configure_logging, get_logger
from common.middleware import CorrelationIdMiddleware, global_exception_handler
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
from modules.leads.router import list_router as lead_lists_router
from modules.leads.router import router as leads_router
from modules.tts.router import router as tts_router
from modules.campaign.template_router import router as workflow_templates_router
from modules.analytics.router import router as analytics_router
from modules.campaign.inbound_email_router import router as inbound_email_router


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
        from database.session import SessionLocal
        from modules.campaign.scheduler_diagnostics import scheduler_status

        db = SessionLocal()
        try:
            sched = scheduler_status(db)
            if not sched["scheduler_online"]:
                log.warning(
                    "app.startup.scheduler_offline",
                    worker_running=sched["worker_running"],
                    beat_running=sched["beat_running"],
                    redis_connected=sched["redis_connected"],
                    queued_executions=sched["queued_executions"],
                    message=sched["message"],
                )
        finally:
            db.close()
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

# Correlation IDs must be outermost so request_id is available everywhere.
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(RateLimitMiddleware)

# Global catch-all for unhandled exceptions — returns structured JSON 500.
app.add_exception_handler(Exception, global_exception_handler)  # type: ignore[arg-type]
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
        "http://localhost:20199",
        "http://127.0.0.1:20199",
        # Vite network URL (public IP) when accessing UI remotely
        "http://116.202.210.102:20197",
        "https://handmade-agreed-dimple.ngrok-free.dev",
        "https://aifuturegroup.co",
        "https://www.aifuturegroup.co"
        
    ],
    # In non-production, accept any localhost/127.0.0.1 port AND any
    # http(s)://host:port so Vite served on a public IP (e.g. for remote
    # browser access) doesn't break CORS preflights.
    allow_origin_regex=(
        None if _is_prod else r"^https?://[^/]+(:\d+)?$"
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
    leads_router,
    lead_lists_router,
    workflow_templates_router,
    analytics_router,
    inbound_email_router,
):
    app.include_router(r, prefix=settings.API_PREFIX)

# ---------------------------------------------------------------------------
# Prometheus metrics — instrumentation via prometheus-fastapi-instrumentator.
# Exposes GET /metrics (Prometheus text format) for scraping by Prometheus /
# Grafana Agent / Datadog OpenMetrics collector.
#
# Metrics included (default instrumentator profile):
#   * http_requests_total (by method, handler, status)
#   * http_request_duration_seconds (latency histogram by handler)
#   * http_request_size_bytes / http_response_size_bytes
#   * in_flight requests gauge
#
# The endpoint is intentionally NOT added to RATE_LIMIT_EXEMPT_PATHS — it
# should be protected by network policy (scrape-only access from the
# Prometheus server) or by adding it to the exempt list in production.
# ---------------------------------------------------------------------------
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=True,  # honour ENABLE_METRICS env var
        should_instrument_requests_inprogress=True,
        excluded_handlers=[
            "/health",
            "/health/ready",
            "/",
        ],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    get_logger("app").info("app.metrics_enabled", endpoint="/metrics")
except ImportError:
    get_logger("app").warning(
        "app.metrics_disabled",
        reason="prometheus-fastapi-instrumentator not installed",
    )


# Serve uploaded voicemail recordings over a public route so Twilio's cloud
# can fetch them for ``<Play>`` voicemail drops. The directory + route are
# configurable; the Twilio-reachable URL is built in
# ``modules.campaign.voicemail.store_recording``.
_vm_dir = settings.VOICEMAIL_UPLOAD_DIR
try:
    os.makedirs(_vm_dir, exist_ok=True)
    app.mount(
        "/" + settings.VOICEMAIL_PUBLIC_ROUTE.strip("/"),
        StaticFiles(directory=_vm_dir),
        name="voicemail-recordings",
    )
except OSError:
    # A read-only FS shouldn't crash startup; uploads will fail later with a
    # clear error and operators can configure voicemail_message_url instead.
    get_logger("app").warning(
        "app.voicemail_mount_failed", directory=_vm_dir
    )


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "environment": settings.ENV,
    }
