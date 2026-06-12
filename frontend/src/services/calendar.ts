import { api } from "./auth";

export interface CalendarIntegration {
  id: string;
  organization_id: string;
  provider: string;
  calendar_email: string | null;
  calendar_id: string;
  connected: boolean;
  created_at: string;
}

export interface FreeSlot {
  start: string;
  end: string;
  start_display: string;
  duration_minutes: number;
}

export interface AvailabilityResponse {
  slots: FreeSlot[];
  date_display: string;
}

/** Fetch the current org's calendar connection status (null = not connected). */
export async function getCalendarStatus(): Promise<CalendarIntegration | null> {
  const { data } = await api.get<CalendarIntegration | null>(
    "/calendar/status"
  );
  return data;
}

/** Start Google OAuth — returns the URL to redirect the user to. */
export async function startGoogleOAuth(orgId: string): Promise<string> {
  const { data } = await api.get<{ auth_url: string }>(
    "/auth/google",
    { params: { org_id: orgId }, baseURL: window.location.origin }
  );
  return data.auth_url;
}

/** Disconnect (revoke + delete) the calendar integration. */
export async function disconnectCalendar(): Promise<void> {
  await api.post("/calendar/disconnect");
}

/** Get available slots for a specific date. */
export async function getAvailability(
  dateIso: string,
  tz: string = "UTC",
  durationMinutes = 30
): Promise<AvailabilityResponse> {
  const { data } = await api.get<AvailabilityResponse>(
    "/calendar/availability",
    { params: { date_iso: dateIso, tz, duration_minutes: durationMinutes } }
  );
  return data;
}
