"""Google Calendar service — token management, FreeBusy, event creation.

Responsibilities
----------------
* Persist / refresh OAuth tokens (Fernet-encrypted in Postgres).
* Check free/busy via the Google Calendar FreeBusy API.
* Create events with auto-generated Google Meet links.
* Cache free-slot responses in Redis (5-min TTL) to avoid hammering the
  Google API on repeated availability checks mid-call.

All methods are async-compatible via ``asyncio.to_thread`` for the sync
Google API client.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone, date
from typing import Optional
import uuid

from common.logging import get_logger
from config.settings import settings
from modules.calendar.encryption import decrypt_token, encrypt_token
from modules.calendar.exceptions import (
    CalendarAPIError,
    CalendarAuthError,
    CalendarError,
    NoCalendarError,
    SlotUnavailableError,
)
from modules.calendar.model import CalendarIntegration
from modules.calendar.schema import BookedEvent, FreeSlot

log = get_logger("calendar.service")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime:
    """Parse an ISO8601 string to a timezone-aware datetime (UTC)."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_display(dt: datetime, tz_name: str) -> str:
    """Return a human-readable date/time string in the given IANA timezone."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
        local = dt.astimezone(tz)
    except Exception:
        local = dt.astimezone(timezone.utc)
    return local.strftime("%-I:%M %p, %B %-d")


def _slot_cache_key(org_id: uuid.UUID, date_str: str, duration: int) -> str:
    h = hashlib.sha1(f"{org_id}:{date_str}:{duration}".encode()).hexdigest()[:12]
    return f"cal:slots:{h}"


# ---------------------------------------------------------------------------
# CalendarService
# ---------------------------------------------------------------------------


class CalendarService:
    """High-level calendar operations for one org."""

    def __init__(self, *, redis_client=None) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Token & integration management
    # ------------------------------------------------------------------

    @staticmethod
    def get_integration(db, org_id: uuid.UUID) -> CalendarIntegration:
        row = (
            db.query(CalendarIntegration)
            .filter_by(organization_id=org_id, provider="google")
            .first()
        )
        if row is None:
            raise NoCalendarError(str(org_id))
        return row

    @staticmethod
    def upsert_integration(
        db,
        *,
        org_id: uuid.UUID,
        access_token: str,
        refresh_token: str,
        token_expiry: Optional[datetime],
        calendar_email: Optional[str],
        calendar_id: str = "primary",
    ) -> CalendarIntegration:
        row = (
            db.query(CalendarIntegration)
            .filter_by(organization_id=org_id, provider="google")
            .first()
        )
        enc_access = encrypt_token(access_token)
        enc_refresh = encrypt_token(refresh_token)
        if row is None:
            row = CalendarIntegration(
                organization_id=org_id,
                provider="google",
                access_token_enc=enc_access,
                refresh_token_enc=enc_refresh,
                token_expiry=token_expiry,
                calendar_email=calendar_email,
                calendar_id=calendar_id,
            )
            db.add(row)
        else:
            row.access_token_enc = enc_access
            row.refresh_token_enc = enc_refresh
            row.token_expiry = token_expiry
            if calendar_email:
                row.calendar_email = calendar_email
            # Always update calendar_id on reconnect so that if the real ID was
            # resolved during OAuth (e.g. "user@gmail.com"), it replaces the
            # old "primary" default stored from a previous connection.
            if calendar_id and calendar_id != "primary":
                row.calendar_id = calendar_id
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def delete_integration(db, org_id: uuid.UUID) -> bool:
        row = (
            db.query(CalendarIntegration)
            .filter_by(organization_id=org_id, provider="google")
            .first()
        )
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True

    # ------------------------------------------------------------------
    # Google API credential builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_credentials(row: CalendarIntegration, db=None):
        """Build a google.oauth2.credentials.Credentials from the DB row,
        refreshing the access token if it has expired or is about to.

        When ``db`` is provided the refreshed token is written back to the row
        so the next call does not need to refresh again.

        IMPORTANT: google-auth's internal _helpers.utcnow() returns a *naive* UTC
        datetime regardless of version.  creds.expiry must therefore remain naive
        UTC so that the library's ``expired`` property (which compares
        ``_helpers.utcnow() >= skewed_expiry``) does not raise a TypeError.
        """
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        access_token = decrypt_token(row.access_token_enc)
        refresh_token = decrypt_token(row.refresh_token_enc)

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=[
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
            ],
        )

        if row.token_expiry:
            # Keep expiry as naive UTC — google-auth._helpers.utcnow() is naive,
            # so mixing aware/naive causes TypeError inside credentials.expired.
            expiry = row.token_expiry
            if expiry.tzinfo is not None:
                expiry = expiry.replace(tzinfo=None)
            creds.expiry = expiry

        # Use naive UTC for comparison to match google-auth's internal representation.
        now_utc_naive = datetime.utcnow()
        needs_refresh = (
            creds.expiry is None
            or creds.expiry <= now_utc_naive + timedelta(minutes=5)
        )
        log.debug(
            "calendar.CREDENTIALS_EXPIRY_CHECK",
            calendar_id=row.calendar_id,
            creds_expiry=str(creds.expiry),
            now_utc_naive=str(now_utc_naive),
            needs_refresh=needs_refresh,
        )
        if needs_refresh:
            log.info("calendar.TOKEN_REFRESHING", calendar_id=row.calendar_id)
            try:
                creds.refresh(Request())
            except Exception as exc:
                log.warning("calendar.token_refresh_failed", calendar_id=row.calendar_id, error=str(exc))
                raise CalendarAuthError() from exc

            # google-auth sets creds.expiry to naive UTC after refresh — keep it naive.
            # Do NOT add tzinfo here; it would break the library's expired check.
            log.info(
                "calendar.TOKEN_REFRESHED",
                calendar_id=row.calendar_id,
                new_expiry=str(creds.expiry),
            )

            # Persist the new access token so the next call doesn't re-refresh
            if db is not None and creds.token:
                try:
                    row.access_token_enc = encrypt_token(creds.token)
                    if creds.expiry:
                        # Store as naive UTC (strip tzinfo if google-auth ever adds it)
                        expiry_to_store = creds.expiry
                        if expiry_to_store.tzinfo is not None:
                            expiry_to_store = expiry_to_store.replace(tzinfo=None)
                        row.token_expiry = expiry_to_store
                    db.commit()
                    log.info("calendar.token_refreshed_and_persisted", org_id=str(row.organization_id))
                except Exception as exc:
                    log.warning("calendar.token_persist_failed", error=str(exc))

        return creds

    @staticmethod
    def _build_service(creds):
        """Build the google-api-python-client calendar service."""
        import googleapiclient.discovery as discovery
        import googleapiclient.errors

        return discovery.build("calendar", "v3", credentials=creds, cache_discovery=False)

    # ------------------------------------------------------------------
    # Free/busy check
    # ------------------------------------------------------------------

    async def get_free_slots(
        self,
        db,
        *,
        org_id: uuid.UUID,
        target_date: date,
        duration_minutes: int = 30,
        timezone: str = "UTC",
        count: int = 3,
    ) -> list[FreeSlot]:
        """Return up to ``count`` free slots on ``target_date`` for the org's calendar."""

        cache_key = _slot_cache_key(org_id, str(target_date), duration_minutes)
        log.debug(
            "calendar.GET_FREE_SLOTS_CALLED",
            org_id=str(org_id),
            target_date=str(target_date),
            duration_minutes=duration_minutes,
            timezone=timezone,
            count=count,
            cache_key=cache_key,
        )
        if self._redis:
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    log.info(
                        "calendar.FREE_SLOTS_CACHE_HIT",
                        org_id=str(org_id),
                        target_date=str(target_date),
                        slots_count=len(data),
                        cache_key=cache_key,
                    )
                    return [FreeSlot(**s) for s in data]
            except Exception as exc:
                log.warning("calendar.FREE_SLOTS_CACHE_ERROR", error=str(exc))

        row = self.get_integration(db, org_id)
        log.info(
            "calendar.GET_FREE_SLOTS_DB_ROW",
            org_id=str(org_id),
            calendar_id=row.calendar_id,
            calendar_email=row.calendar_email,
            token_expiry=str(row.token_expiry),
        )
        slots = await asyncio.to_thread(
            self._fetch_free_slots_sync,
            row,
            db=db,
            target_date=target_date,
            duration_minutes=duration_minutes,
            tz_name=timezone,
            count=count,
        )

        if self._redis and slots:
            try:
                await self._redis.set(
                    cache_key,
                    json.dumps([s.model_dump(mode="json") for s in slots]),
                    ex=settings.CALENDAR_SLOTS_CACHE_TTL_SECONDS,
                )
            except Exception:
                pass

        return slots

    def _fetch_free_slots_sync(
        self,
        row: CalendarIntegration,
        *,
        db=None,
        target_date: date,
        duration_minutes: int,
        tz_name: str,
        count: int,
    ) -> list[FreeSlot]:
        import zoneinfo

        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            log.warning("calendar.invalid_timezone", tz_name=tz_name, fallback="UTC")
            tz = timezone.utc  # type: ignore[assignment]

        # Work window: 09:00–18:00 on the target date in the prospect's timezone
        day_start = datetime(
            target_date.year, target_date.month, target_date.day, 9, 0, tzinfo=tz
        )
        day_end = datetime(
            target_date.year, target_date.month, target_date.day, 18, 0, tzinfo=tz
        )

        # Don't offer slots in the past — advance day_start to the next
        # 30-minute boundary strictly after now.
        now = _utcnow().astimezone(tz)
        if day_start < now:
            # Round up: (minute // 30 + 1) * 30 gives the next :00 or :30 mark.
            mins = (now.minute // 30 + 1) * 30
            candidate = now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=mins)
            day_start = candidate

        # Guard: if the past-time push consumed the entire work window, bail early
        # rather than making a pointless API call that returns no slots anyway.
        if day_start >= day_end:
            log.info(
                "calendar.NO_SLOTS_WORKDAY_OVER",
                target_date=str(target_date),
                tz_name=tz_name,
                day_start=day_start.isoformat(),
                day_end=day_end.isoformat(),
            )
            return []

        log.info(
            "calendar.FETCHING_FREE_SLOTS",
            calendar_id=row.calendar_id,
            target_date=str(target_date),
            window_start=day_start.astimezone(timezone.utc).isoformat(),
            window_end=day_end.astimezone(timezone.utc).isoformat(),
            duration_minutes=duration_minutes,
            count_requested=count,
        )

        creds = self._build_credentials(row, db=db)
        try:
            svc = self._build_service(creds)
        except Exception as exc:
            log.warning(
                "calendar.BUILD_SERVICE_FAILED",
                calendar_id=row.calendar_id,
                error=str(exc),
            )
            raise CalendarAPIError(f"Failed to initialise Google Calendar client: {exc}") from exc

        body = {
            "timeMin": day_start.astimezone(timezone.utc).isoformat(),
            "timeMax": day_end.astimezone(timezone.utc).isoformat(),
            "items": [{"id": row.calendar_id}],
        }
        log.info(
            "calendar.FREEBUSY_REQUEST",
            calendar_id=row.calendar_id,
            time_min=body["timeMin"],
            time_max=body["timeMax"],
        )

        try:
            fb = svc.freebusy().query(body=body).execute()
        except Exception as exc:
            log.warning(
                "calendar.FREEBUSY_API_FAILED",
                calendar_id=row.calendar_id,
                target_date=str(target_date),
                error=str(exc),
            )
            raise CalendarAPIError(str(exc)) from exc

        response_keys = list(fb.get("calendars", {}).keys())
        key_found = row.calendar_id in response_keys
        log.info(
            "calendar.FREEBUSY_RESPONSE",
            calendar_id=row.calendar_id,
            target_date=str(target_date),
            response_keys=response_keys,
            calendar_key_found=key_found,
        )
        if not key_found:
            log.warning(
                "calendar.FREEBUSY_KEY_MISMATCH",
                calendar_id=row.calendar_id,
                response_keys=response_keys,
                hint=(
                    "The calendar_id stored in the DB does not match any key in the "
                    "FreeBusy response.  Re-connect the calendar to resolve the actual ID."
                ),
            )

        busy_periods = fb.get("calendars", {}).get(row.calendar_id, {}).get("busy", [])
        log.info(
            "calendar.FREEBUSY_BUSY_INTERVALS",
            calendar_id=row.calendar_id,
            target_date=str(target_date),
            busy_period_count=len(busy_periods),
            busy_intervals=[
                {"start": b.get("start"), "end": b.get("end")} for b in busy_periods
            ],
        )

        busy: list[tuple[datetime, datetime]] = []
        for b in busy_periods:
            busy.append((_parse_iso(b["start"]), _parse_iso(b["end"])))
        busy.sort(key=lambda x: x[0])

        # Walk the day in 30-minute steps (regardless of duration) so we find
        # all possible start-times; skip any block that overlaps a busy period.
        slots: list[FreeSlot] = []
        cursor = day_start
        step = timedelta(minutes=duration_minutes)
        while cursor + step <= day_end and len(slots) < count:
            slot_end = cursor + step
            overlaps = any(
                b_start < slot_end and b_end > cursor for b_start, b_end in busy
            )
            if not overlaps:
                slots.append(
                    FreeSlot(
                        start=cursor.astimezone(timezone.utc),
                        end=slot_end.astimezone(timezone.utc),
                        start_display=_format_display(cursor, tz_name),
                        duration_minutes=duration_minutes,
                    )
                )
            cursor += timedelta(minutes=30)

        log.info(
            "calendar.FREE_SLOTS_FOUND",
            calendar_id=row.calendar_id,
            target_date=str(target_date),
            slots_found=len(slots),
            slots_requested=count,
        )
        return slots

    # ------------------------------------------------------------------
    # Availability check for a specific slot
    # ------------------------------------------------------------------

    async def is_slot_available(
        self,
        db,
        *,
        org_id: uuid.UUID,
        start: datetime,
        duration_minutes: int = 30,
    ) -> bool:
        log.info(
            "calendar.IS_SLOT_AVAILABLE_CALLED",
            org_id=str(org_id),
            start=start.isoformat(),
            start_tzinfo=str(start.tzinfo),
            duration_minutes=duration_minutes,
        )
        row = self.get_integration(db, org_id)
        log.info(
            "calendar.IS_SLOT_AVAILABLE_DB_ROW",
            org_id=str(org_id),
            calendar_id=row.calendar_id,
            calendar_email=row.calendar_email,
            token_expiry=str(row.token_expiry),
        )
        return await asyncio.to_thread(
            self._check_slot_sync,
            row,
            db=db,
            start=start,
            duration_minutes=duration_minutes,
        )

    def _check_slot_sync(
        self,
        row: CalendarIntegration,
        *,
        db=None,
        start: datetime,
        duration_minutes: int,
    ) -> bool:
        end = start + timedelta(minutes=duration_minutes)
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)

        log.info(
            "calendar.CHECKING_SLOT",
            calendar_id=row.calendar_id,
            start=start_utc.isoformat(),
            end=end_utc.isoformat(),
        )

        creds = self._build_credentials(row, db=db)
        try:
            svc = self._build_service(creds)
        except Exception as exc:
            log.warning(
                "calendar.BUILD_SERVICE_FAILED",
                calendar_id=row.calendar_id,
                error=str(exc),
            )
            raise CalendarAPIError(f"Failed to initialise Google Calendar client: {exc}") from exc

        body = {
            "timeMin": start_utc.isoformat(),
            "timeMax": end_utc.isoformat(),
            "items": [{"id": row.calendar_id}],
        }
        log.info(
            "calendar.SLOT_CHECK_REQUEST",
            calendar_id=row.calendar_id,
            time_min=body["timeMin"],
            time_max=body["timeMax"],
        )
        try:
            fb = svc.freebusy().query(body=body).execute()
        except Exception as exc:
            log.warning(
                "calendar.SLOT_CHECK_API_FAILED",
                calendar_id=row.calendar_id,
                start=start_utc.isoformat(),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise CalendarAPIError(str(exc)) from exc

        response_keys = list(fb.get("calendars", {}).keys())
        key_found = row.calendar_id in response_keys
        log.info(
            "calendar.SLOT_CHECK_RAW_RESPONSE",
            calendar_id=row.calendar_id,
            start=start_utc.isoformat(),
            response_keys=response_keys,
            calendar_key_found=key_found,
            raw_calendars=fb.get("calendars", {}),
        )
        if not key_found:
            log.warning(
                "calendar.SLOT_CHECK_KEY_MISMATCH",
                calendar_id=row.calendar_id,
                response_keys=response_keys,
                hint=(
                    "The calendar_id in the DB does not appear in the FreeBusy response. "
                    "Re-connect the calendar integration to store the resolved email."
                ),
            )

        busy = fb.get("calendars", {}).get(row.calendar_id, {}).get("busy", [])
        available = len(busy) == 0
        log.info(
            "calendar.SLOT_CHECK_RESULT",
            calendar_id=row.calendar_id,
            start=start_utc.isoformat(),
            response_keys=response_keys,
            calendar_key_found=key_found,
            busy_intervals=[
                {"start": b.get("start"), "end": b.get("end")} for b in busy
            ],
            available=available,
            decision=("AVAILABLE" if available else "BUSY"),
        )
        return available

    # ------------------------------------------------------------------
    # Book a meeting
    # ------------------------------------------------------------------

    async def book_meeting(
        self,
        db,
        *,
        org_id: uuid.UUID,
        start: datetime,
        duration_minutes: int = 30,
        title: str = "Meeting",
        description: str = "",
        attendee_email: str,
        attendee_name: str,
        organizer_email: Optional[str] = None,
        timezone: str = "UTC",
    ) -> BookedEvent:
        row = self.get_integration(db, org_id)
        return await asyncio.to_thread(
            self._book_meeting_sync,
            row,
            db=db,
            start=start,
            duration_minutes=duration_minutes,
            title=title,
            description=description,
            attendee_email=attendee_email,
            attendee_name=attendee_name,
            organizer_email=organizer_email or row.calendar_email,
            tz_name=timezone,
        )

    def _book_meeting_sync(
        self,
        row: CalendarIntegration,
        *,
        db=None,
        start: datetime,
        duration_minutes: int,
        title: str,
        description: str,
        attendee_email: str,
        attendee_name: str,
        organizer_email: Optional[str],
        tz_name: str,
    ) -> BookedEvent:
        end = start + timedelta(minutes=duration_minutes)
        log.info(
            "calendar.BOOK_MEETING_SYNC_START",
            calendar_id=row.calendar_id,
            calendar_email=row.calendar_email,
            start_utc=start.astimezone(timezone.utc).isoformat(),
            end_utc=end.astimezone(timezone.utc).isoformat(),
            start_tzinfo=str(start.tzinfo),
            duration_minutes=duration_minutes,
            attendee_email=attendee_email,
            attendee_name=attendee_name,
            organizer_email=organizer_email,
            tz_name=tz_name,
        )
        creds = self._build_credentials(row, db=db)
        svc = self._build_service(creds)

        attendees = [{"email": attendee_email, "displayName": attendee_name}]
        if organizer_email and organizer_email != attendee_email:
            attendees.append({"email": organizer_email})

        event_body = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": start.astimezone(timezone.utc).isoformat(),
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": end.astimezone(timezone.utc).isoformat(),
                "timeZone": "UTC",
            },
            "attendees": attendees,
            "conferenceData": {
                "createRequest": {
                    "requestId": f"meet-{start.strftime('%Y%m%d%H%M%S')}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 60},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }

        log.info(
            "calendar.EVENTS_INSERT_REQUEST",
            calendar_id=row.calendar_id,
            event_summary=title,
            start_utc=event_body["start"]["dateTime"],
            end_utc=event_body["end"]["dateTime"],
            attendees=[a["email"] for a in event_body["attendees"]],
        )
        try:
            created = (
                svc.events()
                .insert(
                    calendarId=row.calendar_id,
                    body=event_body,
                    conferenceDataVersion=1,
                    sendUpdates="all",
                )
                .execute()
            )
        except Exception as exc:
            log.warning(
                "calendar.book_failed",
                calendar_id=row.calendar_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise CalendarAPIError(str(exc)) from exc
        log.info(
            "calendar.EVENTS_INSERT_SUCCESS",
            calendar_id=row.calendar_id,
            event_id=created.get("id"),
            html_link=created.get("htmlLink"),
            has_conference_data="conferenceData" in created,
        )

        meet_link: Optional[str] = None
        entry_points = (
            created.get("conferenceData", {})
            .get("entryPoints", [])
        )
        for ep in entry_points:
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri")
                break

        return BookedEvent(
            event_id=created["id"],
            meet_link=meet_link,
            html_link=created.get("htmlLink", ""),
            start_iso=created["start"]["dateTime"],
            end_iso=created["end"]["dateTime"],
            start_display=_format_display(start, tz_name),
            title=title,
        )
