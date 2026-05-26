from fastapi import FastAPI
from config.settings import settings
from modules.health.router import router as health_router
from modules.auth.router import router as auth_router

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0",
)


app.include_router(
    health_router,
    prefix=settings.API_PREFIX,
)
app.include_router(
    auth_router,
    prefix=settings.API_PREFIX,
)


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "environment": settings.ENV,
    }