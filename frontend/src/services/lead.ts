import { api } from "./auth";
import { formatApiError } from "@/lib/apiError";
import type {
  ActivityType,
  CommitUploadPayload,
  CommitUploadResult,
  CreateLeadInput,
  Lead,
  LeadActivity,
  LeadList,
  UpdateLeadInput,
  UploadPreview,
} from "@/types/lead";

export { formatApiError as formatLeadApiError };

/* -------------------------------------------------------------------------- */
/* Lead lists                                                                 */
/* -------------------------------------------------------------------------- */

export async function listLeadLists(): Promise<LeadList[]> {
  const res = await api.get<{ lead_lists: LeadList[] }>("/lead-lists");
  return res.data.lead_lists;
}

export async function createLeadList(input: {
  name: string;
  description?: string;
  source?: string;
}): Promise<LeadList> {
  const res = await api.post<LeadList>("/lead-lists", input);
  return res.data;
}

/* -------------------------------------------------------------------------- */
/* Leads                                                                      */
/* -------------------------------------------------------------------------- */

export async function listLeads(params?: {
  lead_list_id?: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<{ leads: Lead[]; total: number }> {
  const res = await api.get<{ leads: Lead[]; total: number }>("/leads", {
    params,
  });
  return res.data;
}

/** Fetch a single lead by id (`GET /leads/{id}`). */
export async function getLead(leadId: string): Promise<Lead> {
  const res = await api.get<Lead>(`/leads/${encodeURIComponent(leadId)}`);
  return res.data;
}

export async function createLead(input: CreateLeadInput): Promise<Lead> {
  const res = await api.post<Lead>("/leads", input);
  return res.data;
}

export async function updateLead(
  leadId: string,
  input: UpdateLeadInput
): Promise<Lead> {
  const res = await api.patch<Lead>(
    `/leads/${encodeURIComponent(leadId)}`,
    input
  );
  return res.data;
}

export async function deleteLead(leadId: string): Promise<void> {
  await api.delete(`/leads/${encodeURIComponent(leadId)}`);
}

/* -------------------------------------------------------------------------- */
/* Lead activities                                                            */
/* -------------------------------------------------------------------------- */

export async function listLeadActivities(
  leadId: string
): Promise<LeadActivity[]> {
  const res = await api.get<{ activities: LeadActivity[] }>(
    `/leads/${encodeURIComponent(leadId)}/activities`
  );
  return res.data.activities;
}

export async function logLeadActivity(
  leadId: string,
  input: { activity_type: ActivityType; notes?: string | null }
): Promise<LeadActivity> {
  const res = await api.post<LeadActivity>(
    `/leads/${encodeURIComponent(leadId)}/activities`,
    input
  );
  return res.data;
}

/* -------------------------------------------------------------------------- */
/* CSV upload                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * Send the raw CSV file to the server for parse + validate + dedupe.
 *
 * The server cross-checks against the org's existing phones so the FE
 * preview shows accurate "already exists in your workspace" hints.
 */
export async function previewUpload(file: File): Promise<UploadPreview> {
  const form = new FormData();
  form.append("file", file, file.name);
  const res = await api.post<UploadPreview>("/leads/upload/preview", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

export async function commitUpload(
  payload: CommitUploadPayload
): Promise<CommitUploadResult> {
  const res = await api.post<CommitUploadResult>(
    "/leads/upload/commit",
    payload
  );
  return res.data;
}
