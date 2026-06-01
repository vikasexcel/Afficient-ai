import { api } from "./auth";
import type { CampaignCreateInput, CampaignDraft } from "@/types/campaign";

export type CreateCampaignResponse = {
  id: string;
  status: string;
};

export type ActivateCampaignResponse = {
  workflow_id: string;
  state: string;
  already_active?: boolean;
};

/**
 * Builds the JSON body for `POST /campaigns`.
 *
 * The backend currently only persists `{name}`. We still construct the full
 * payload so this function is the single point to extend the moment the
 * backend accepts more fields (playbook_id, schedule, business_hours, ...).
 */
function toCreatePayload(input: CampaignCreateInput) {
  return {
    name: input.name.trim(),
  };
}

export async function createCampaign(
  input: CampaignCreateInput
): Promise<CreateCampaignResponse> {
  const res = await api.post<CreateCampaignResponse>(
    "/campaigns",
    toCreatePayload(input)
  );
  return res.data;
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
/* Local draft persistence                                                    */
/* -------------------------------------------------------------------------- */
/* Draft, scheduling, business-hours, and lead-list config are not yet stored */
/* server-side. We keep them in localStorage keyed by org so reloads don't    */
/* lose the user's work; the moment the backend grows these columns, swap    */
/* these helpers for real API calls.                                          */

const DRAFTS_KEY = "afficient.campaign.drafts.v1";

export type StoredDraft = {
  /** Stable client-generated id so drafts survive before they have a server id. */
  id: string;
  saved_at: string;
  data: CampaignDraft;
  /** Server id once the campaign has been persisted (still in draft state). */
  server_id?: string;
};

function readDrafts(): StoredDraft[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(DRAFTS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as StoredDraft[]) : [];
  } catch {
    return [];
  }
}

function writeDrafts(drafts: StoredDraft[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts));
}

export function listDrafts(): StoredDraft[] {
  return readDrafts().sort((a, b) =>
    a.saved_at < b.saved_at ? 1 : a.saved_at > b.saved_at ? -1 : 0
  );
}

export function upsertDraft(draft: StoredDraft): StoredDraft {
  const existing = readDrafts();
  const idx = existing.findIndex((d) => d.id === draft.id);
  if (idx === -1) existing.push(draft);
  else existing[idx] = draft;
  writeDrafts(existing);
  return draft;
}

export function removeDraft(id: string) {
  writeDrafts(readDrafts().filter((d) => d.id !== id));
}

export function newDraftId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `draft_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
