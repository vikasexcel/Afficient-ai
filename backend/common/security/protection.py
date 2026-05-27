from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import HTTPException

from common.security.rate_limit import limit


async def protect(request: Request):
    ip = request.client.host
    print("RATE LIMIT:", ip, flush=True)
    limit(f"api:{ip}")


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "unknown"
        print("RATE LIMIT:", ip, request.url.path, flush=True)
        try:
            limit(f"api:{ip}")
        except HTTPException as exc:
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
            )
        return await call_next(request)