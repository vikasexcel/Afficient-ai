from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import settings
from modules.health.router import router as health_router
from modules.auth.router import router as auth_router
from common.security.protection import RateLimitMiddleware
from modules.campaign.router import (router as campaign_router)
from modules.members.router import router as members_router
from modules.organization.router import router as organization_router

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0",
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


app.include_router(
    health_router,
    prefix=settings.API_PREFIX,
)
app.include_router(
    auth_router,
    prefix=settings.API_PREFIX,
)

app.include_router(
    campaign_router,
    prefix=settings.API_PREFIX,
)
app.include_router(
    members_router,
    prefix=settings.API_PREFIX,
)
app.include_router(
    organization_router,
    prefix=settings.API_PREFIX,
)


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "environment": settings.ENV,
    }