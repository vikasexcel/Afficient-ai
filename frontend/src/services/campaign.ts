import { api } from "./auth";
import type {
  BusinessHours,
  CampaignCreateInput,
  CampaignDraft,
  CampaignMetrics,
  CampaignOut,
  VoicemailConfig,
} from "@/types/campaign";

export type CreateCampaignResponse = {
  id: string;
  status: string;
};

export type ActivateCampaignResponse = {
  workflow_id: string | null;
  state: string;
  already_active?: boolean;
  scheduled?: boolean;
  scheduled_at?: string;
  within_business_hours?: boolean;
  enqueued_leads?: number;
  message?: string;
};

/* -------------------------------------------------------------------------- */
/* Payload mapping                                                            */
/* -------------------------------------------------------------------------- */

/**
 * Maps the dialog's `CampaignDraft` to the JSON body the backend persists.
 * Every configuration field (playbook, lead list, schedule, timezone, and
 * business hours) is sent — the server now stores them all.
 */
function toApiPayload(input: CampaignDraft) {
  return {
    name: input.name.trim(),
    playbook_id: input.playbook_id,
    lead_list_id: input.lead_list_id,
    schedule: {
      start_immediately: input.schedule.start_immediately,
      date: input.schedule.date,
      time: input.schedule.time,
      timezone: input.schedule.timezone,
    },
    business_hours: input.business_hours,
  };
}

/* -------------------------------------------------------------------------- */
/* CRUD                                                                       */
/* -------------------------------------------------------------------------- */

export async function createCampaign(
  input: CampaignCreateInput
): Promise<CreateCampaignResponse> {
  const res = await api.post<CreateCampaignResponse>("/campaigns", {
    ...toApiPayload(input),
    launch: input.launch,
  });
  return res.data;
}

export async function listCampaigns(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<{ campaigns: CampaignOut[]; total: number }> {
  const res = await api.get<{ campaigns: CampaignOut[]; total: number }>(
    "/campaigns",
    { params }
  );
  return res.data;
}

export async function getCampaign(id: string): Promise<CampaignOut> {
  const res = await api.get<CampaignOut>(`/campaigns/${id}`);
  return res.data;
}

export async function updateCampaign(
  id: string,
  input: CampaignDraft
): Promise<CampaignOut> {
  const res = await api.patch<CampaignOut>(
    `/campaigns/${id}`,
    toApiPayload(input)
  );
  return res.data;
}

export async function deleteCampaign(id: string): Promise<void> {
  await api.delete(`/campaigns/${id}`);
}

export async function activateCampaign(
  campaignId: string
): Promise<ActivateCampaignResponse> {
  const res = await api.post<ActivateCampaignResponse>("/campaigns/activate", {
    campaign_id: campaignId,
  });
  return res.data;
}

/* -------------------------------------------------------------------------- */
/* Metrics + voicemail (AMD / Voicemail Drop)                                 */
/* -------------------------------------------------------------------------- */

export async function getCampaignMetrics(
  campaignId: string
): Promise<CampaignMetrics> {
  const res = await api.get<CampaignMetrics>(`/campaigns/${campaignId}/metrics`);
  return res.data;
}

export async function getVoicemailConfig(
  campaignId: string
): Promise<VoicemailConfig & { campaign_id: string }> {
  const res = await api.get<VoicemailConfig & { campaign_id: string }>(
    `/campaigns/${campaignId}/voicemail`
  );
  return res.data;
}

/**
 * Upload or configure the campaign's voicemail-drop recording.
 *
 * Pass either a `file` (audio upload) or `voicemail_message_url` (external
 * recording). Sent as multipart/form-data to match the backend endpoint.
 */
export async function setVoicemailConfig(
  campaignId: string,
  input: {
    voicemail_enabled: boolean;
    retry_on_voicemail: boolean;
    amd_unknown_fallback?: "human" | "voicemail";
    voicemail_message_url?: string;
    file?: File;
  }
): Promise<VoicemailConfig & { campaign_id: string }> {
  const form = new FormData();
  form.append("voicemail_enabled", String(input.voicemail_enabled));
  form.append("retry_on_voicemail", String(input.retry_on_voicemail));
  form.append("amd_unknown_fallback", input.amd_unknown_fallback ?? "human");
  if (input.voicemail_message_url) {
    form.append("voicemail_message_url", input.voicemail_message_url);
  }
  if (input.file) {
    form.append("file", input.file);
  }
  const res = await api.post<VoicemailConfig & { campaign_id: string }>(
    `/campaigns/${campaignId}/voicemail`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return res.data;
}

/* -------------------------------------------------------------------------- */
/* CampaignOut -> CampaignDraft (for the edit dialog)                         */
/* -------------------------------------------------------------------------- */

function resolveLocalTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** Split a UTC ISO instant into local "YYYY-MM-DD" + "HH:mm" in `tz`. */
function splitInstant(
  iso: string,
  tz: string
): { date: string; time: string } {
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    time: `${get("hour")}:${get("minute")}`,
  };
}

const DEFAULT_BUSINESS_HOURS: BusinessHours = {
  days: ["mon", "tue", "wed", "thu", "fri"],
  start: "09:00",
  end: "18:00",
  skip_holidays: true,
};

export function campaignToDraft(c: CampaignOut): CampaignDraft {
  const tz = c.timezone || resolveLocalTimezone();
  const startImmediately = !c.scheduled_at;
  const sched = c.scheduled_at
    ? splitInstant(c.scheduled_at, tz)
    : { date: null, time: null };

  return {
    name: c.name,
    playbook_id: c.playbook_id,
    lead_list_id: c.lead_list_id,
    schedule: {
      date: sched.date,
      time: sched.time,
      timezone: tz,
      start_immediately: startImmediately,
    },
    business_hours: c.business_hours ?? { ...DEFAULT_BUSINESS_HOURS },
  };
}
