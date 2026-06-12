"""Google Calendar OAuth + management endpoints.

Mounted at ``/auth/google`` (outside the /api/v1 prefix) to match the
configured Google redirect URI: https://api.aifuturegroup.co/auth/google/callback

Routes
------
GET  /auth/google                 → returns the Google OAuth authorization URL
GET  /auth/google/callback        → exchange code for tokens, redirect to frontend
POST /api/v1/calendar/disconnect  → revoke + delete integration
GET  /api/v1/calendar/status      → returns connection status for the current org
GET  /api/v1/calendar/availability → free slots for a date
POST /api/v1/calendar/book        → book a specific slot (internal/testing endpoint)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from common.logging import get_logger
from common.security.dependencies import get_current_user
from config.settings import settings
from database.dependencies import get_db
from modules.auth.model import User
from modules.auth.tenant import get_current_tenant
from modules.calendar.dependencies import get_calendar_service
from modules.calendar.exceptions import CalendarError, NoCalendarError
from modules.calendar.schema import (
    AvailabilityResponse,
    BookedEvent,
    BookingRequest,
    CalendarIntegrationOut,
    FreeSlot,
)
from modules.calendar.service import CalendarService

log = get_logger("calendar.router")

# Two routers — one at /auth/google (no prefix), one at /api/v1/calendar
auth_router = APIRouter(tags=["Calendar Auth"])
api_router = APIRouter(prefix="/calendar", tags=["Calendar"])


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------


@auth_router.get("", summary="Start Google Calendar OAuth flow")
async def start_google_oauth(
    org_id: Optional[str] = Query(None, description="Organization ID to connect for"),
    current_user: User = Depends(get_current_user),
):
    """Returns a redirect URL to start Google OAuth. Frontend should redirect to it."""
    from google_auth_oauthlib.flow import Flow
    import redis as _redis

    state = f"{current_user['sub']}:{org_id or ''}"

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
        ],
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )

    # Store PKCE code_verifier in Redis so the callback can use it
    code_verifier = getattr(flow, "code_verifier", None)
    if code_verifier:
        try:
            r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
            r.setex(f"oauth:cv:{state}", 300, code_verifier)
        except Exception as exc:
            log.warning("calendar.oauth.store_verifier_failed", error=str(exc))

    return {"auth_url": auth_url}


@auth_router.get("/callback", summary="Google OAuth callback", include_in_schema=False)
async def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(""),
    db: Session = Depends(get_db),
    calendar_svc: CalendarService = Depends(get_calendar_service),
):
    """Exchange auth code for tokens, persist, redirect to frontend."""
    from google_auth_oauthlib.flow import Flow
    import requests as http_requests

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
        ],
        state=state,
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI

    # Retrieve the PKCE code_verifier stored during auth URL generation
    code_verifier: Optional[str] = None
    try:
        import redis as _redis
        r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
        code_verifier = r.get(f"oauth:cv:{state}")
        if code_verifier:
            r.delete(f"oauth:cv:{state}")
    except Exception:
        pass

    try:
        if code_verifier:
            flow.fetch_token(code=code, code_verifier=code_verifier)
        else:
            flow.fetch_token(code=code)
    except Exception as exc:
        log.warning("calendar.oauth_callback.token_fetch_failed", error=str(exc))
        frontend_url = settings.APP_LOGIN_URL.replace("/login", "")
        return RedirectResponse(
            url=f"{frontend_url}/settings?error=oauth_failed"
        )

    creds = flow.credentials

    # Fetch the Google account email (for display)
    calendar_email: Optional[str] = None
    try:
        resp = http_requests.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            calendar_email = resp.json().get("email")
    except Exception:
        pass

    # Fetch the *actual* primary calendar ID from the Calendar API.
    # Google's FreeBusy API returns the real calendar email (e.g. "user@gmail.com")
    # as the response key — the alias "primary" is NOT echoed back.  We must
    # store the resolved ID so that fb["calendars"][calendar_id] lookups work.
    actual_calendar_id: Optional[str] = None
    try:
        from google.oauth2.credentials import Credentials as GoogleCredentials
        import googleapiclient.discovery as discovery

        google_creds = GoogleCredentials(
            token=creds.token,
            refresh_token=creds.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
        )
        cal_api = discovery.build("calendar", "v3", credentials=google_creds, cache_discovery=False)
        primary_cal = cal_api.calendars().get(calendarId="primary").execute()
        actual_calendar_id = primary_cal.get("id")  # resolved email, e.g. "user@gmail.com"
        log.info(
            "calendar.oauth_callback.resolved_calendar_id",
            calendar_email=calendar_email,
            calendar_id=actual_calendar_id,
        )
    except Exception as exc:
        log.warning(
            "calendar.oauth_callback.fetch_calendar_id_failed",
            calendar_email=calendar_email,
            error=str(exc),
        )
        # Fall back: primary calendar ID is usually the same as the account email
        actual_calendar_id = calendar_email

    # Parse org_id from state ("user_id:org_id")
    parts = state.split(":", 1)
    org_id_str = parts[1] if len(parts) == 2 else ""
    try:
        org_id = uuid.UUID(org_id_str)
    except (ValueError, AttributeError):
        frontend_url = settings.APP_LOGIN_URL.replace("/login", "")
        return RedirectResponse(
            url=f"{frontend_url}/settings?error=invalid_state"
        )

    # Store expiry as naive UTC — _build_credentials keeps expiry naive to
    # avoid TypeError inside google-auth's _helpers.utcnow() comparison.
    expiry: Optional[datetime] = None
    if creds.expiry:
        expiry = creds.expiry.replace(tzinfo=None) if creds.expiry.tzinfo is not None else creds.expiry

    CalendarService.upsert_integration(
        db,
        org_id=org_id,
        access_token=creds.token,
        refresh_token=creds.refresh_token or "",
        token_expiry=expiry,
        calendar_email=calendar_email,
        calendar_id=actual_calendar_id or "primary",
    )

    log.info(
        "calendar.oauth_connected",
        org_id=str(org_id),
        calendar_email=calendar_email,
        calendar_id=actual_calendar_id,
    )

    frontend_url = settings.APP_LOGIN_URL.replace("/login", "")
    return RedirectResponse(
        url=f"{frontend_url}/settings?connected=1"
    )


# ---------------------------------------------------------------------------
# Management endpoints (under /api/v1/calendar)
# ---------------------------------------------------------------------------


@api_router.get("/status", response_model=Optional[CalendarIntegrationOut])
async def calendar_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant=Depends(get_current_tenant),
):
    """Return the current org's calendar integration status, or null if not connected."""
    from modules.calendar.model import CalendarIntegration

    org_id = uuid.UUID(str(tenant["organization_id"]))
    row = (
        db.query(CalendarIntegration)
        .filter_by(organization_id=org_id, provider="google")
        .first()
    )
    if row is None:
        return None
    return CalendarIntegrationOut.model_validate(row)


@api_router.post("/disconnect")
async def disconnect_calendar(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant=Depends(get_current_tenant),
    calendar_svc: CalendarService = Depends(get_calendar_service),
):
    """Revoke Google Calendar access and delete the integration."""
    from modules.calendar.model import CalendarIntegration
    from modules.calendar.encryption import decrypt_token

    org_id = uuid.UUID(str(tenant["organization_id"]))
    row = (
        db.query(CalendarIntegration)
        .filter_by(organization_id=org_id, provider="google")
        .first()
    )
    if row:
        # Best-effort token revocation
        try:
            import requests as http_requests
            token = decrypt_token(row.access_token_enc)
            http_requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                timeout=5,
            )
        except Exception:
            pass

    deleted = CalendarService.delete_integration(db, org_id)
    return {"disconnected": deleted}


@api_router.get("/availability", response_model=AvailabilityResponse)
async def get_availability(
    date_iso: str = Query(..., description="Date as YYYY-MM-DD"),
    tz: str = Query("UTC", description="IANA timezone"),
    duration_minutes: int = Query(30),
    count: int = Query(3),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant=Depends(get_current_tenant),
    calendar_svc: CalendarService = Depends(get_calendar_service),
):
    """Return available meeting slots for a given date."""
    try:
        target_date = date.fromisoformat(date_iso)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format — use YYYY-MM-DD")

    org_id = uuid.UUID(str(tenant["organization_id"]))
    try:
        slots = await calendar_svc.get_free_slots(
            db,
            org_id=org_id,
            target_date=target_date,
            duration_minutes=duration_minutes,
            timezone=tz,
            count=count,
        )
    except NoCalendarError:
        raise HTTPException(status_code=404, detail="No Google Calendar connected for this organization")
    except CalendarError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    import calendar as _cal
    date_display = target_date.strftime(f"%A, {_cal.month_name[target_date.month]} {target_date.day}")
    return AvailabilityResponse(slots=slots, date_display=date_display)


@api_router.post("/book", response_model=BookedEvent)
async def book_meeting_endpoint(
    payload: BookingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant=Depends(get_current_tenant),
    calendar_svc: CalendarService = Depends(get_calendar_service),
):
    """Book a meeting slot (used by the admin UI and tests)."""
    from datetime import datetime as dt
    try:
        start = dt.fromisoformat(payload.slot_start_iso.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slot_start_iso — use ISO8601")

    org_id = uuid.UUID(str(tenant["organization_id"]))
    try:
        event = await calendar_svc.book_meeting(
            db,
            org_id=org_id,
            start=start,
            duration_minutes=payload.duration_minutes,
            title=payload.title,
            description=payload.description,
            attendee_email=payload.attendee_email,
            attendee_name=payload.attendee_name,
            timezone=payload.timezone,
        )
    except NoCalendarError:
        raise HTTPException(status_code=404, detail="No Google Calendar connected for this organization")
    except CalendarError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return event
