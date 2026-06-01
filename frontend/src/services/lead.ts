import { api } from "./auth";
import type {
  CommitUploadPayload,
  CommitUploadResult,
  Lead,
  LeadList,
  UploadPreview,
} from "@/types/lead";

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
  limit?: number;
  offset?: number;
}): Promise<{ leads: Lead[]; total: number }> {
  const res = await api.get<{ leads: Lead[]; total: number }>("/leads", {
    params,
  });
  return res.data;
}

export async function deleteLead(leadId: string): Promise<void> {
  await api.delete(`/leads/${leadId}`);
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
