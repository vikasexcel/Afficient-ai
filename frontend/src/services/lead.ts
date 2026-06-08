import { api } from "@/services/auth";
import type { AxiosError } from "axios";
import type {
  CommitUploadResult,
  CreateLeadInput,
  CreateLeadListInput,
  Lead,
  LeadList,
  LeadListLeadsResponse,
  LeadListResponse,
  MembershipResponse,
  UpdateLeadInput,
  UpdateLeadListInput,
  UploadPreview,
} from "@/types/lead";
import { processCSV } from "@/lib/csvParser";

// --------------------------------------------------------------------------
// Lead lists
// --------------------------------------------------------------------------

export async function listLeadLists(): Promise<LeadList[]> {
  const res = await api.get<LeadListResponse>("/lead-lists");
  return res.data.lead_lists;
}

export async function createLeadList(
  input: CreateLeadListInput
): Promise<LeadList> {
  const res = await api.post<LeadList>("/lead-lists", input);
  return res.data;
}

export async function updateLeadList(
  listId: string,
  input: UpdateLeadListInput
): Promise<LeadList> {
  const res = await api.patch<LeadList>(`/lead-lists/${listId}`, input);
  return res.data;
}

export async function deleteLeadList(listId: string): Promise<void> {
  await api.delete(`/lead-lists/${listId}`);
}

export async function addLeadsToList(
  listId: string,
  leadIds: string[]
): Promise<MembershipResponse> {
  const res = await api.post<MembershipResponse>(
    `/lead-lists/${listId}/leads`,
    { lead_ids: leadIds }
  );
  return res.data;
}

export async function removeLeadsFromList(
  listId: string,
  leadIds: string[]
): Promise<MembershipResponse> {
  const res = await api.delete<MembershipResponse>(
    `/lead-lists/${listId}/leads`,
    { data: { lead_ids: leadIds } }
  );
  return res.data;
}

// --------------------------------------------------------------------------
// Leads
// --------------------------------------------------------------------------

export interface ListLeadsParams {
  lead_list_id?: string;
  search?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export async function listLeads(
  params: ListLeadsParams = {}
): Promise<LeadListLeadsResponse> {
  const res = await api.get<LeadListLeadsResponse>("/leads", { params });
  return res.data;
}

export async function getLead(leadId: string): Promise<Lead> {
  const res = await api.get<Lead>(`/leads/${leadId}`);
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
  const res = await api.patch<Lead>(`/leads/${leadId}`, input);
  return res.data;
}

export async function deleteLead(leadId: string): Promise<void> {
  await api.delete(`/leads/${leadId}`);
}

// --------------------------------------------------------------------------
// CSV upload — client-side preview + commit (no new backend endpoints needed)
// --------------------------------------------------------------------------

export interface CommitUploadPayload {
  rows: Array<{
    name: string;
    email: string | null;
    phone: string;
    company: string | null;
    industry: string | null;
    location: string | null;
    tags: string[] | null;
    custom_fields: Record<string, string> | null;
  }>;
  segmentation: {
    industry: string | null;
    location: string | null;
    tags: string[];
    custom_fields: Record<string, string>;
  };
  lead_list_id: string | null;
  new_list_name: string | null;
  source: string | null;
}

/**
 * Parse the CSV in-browser and return a structured preview.
 * No backend round-trip — identical validation logic to the server.
 */
export async function previewUpload(file: File): Promise<UploadPreview> {
  const text = await file.text();
  const { rows, summary } = processCSV(text);
  return {
    rows,
    stats: {
      total: summary.total,
      valid: summary.valid,
      invalid: summary.invalid,
      duplicate: summary.duplicate,
    },
  };
}

/**
 * Commit a set of pre-validated rows via the existing createLead endpoint.
 * Segmentation fields are merged into each lead before saving.
 */
export async function commitUpload(
  payload: CommitUploadPayload
): Promise<CommitUploadResult> {
  // Resolve or create the target lead list.
  let targetListId: string | null = payload.lead_list_id;
  let targetListName = "";

  if (!targetListId && payload.new_list_name) {
    const list = await createLeadList({ name: payload.new_list_name });
    targetListId = list.id;
    targetListName = list.name;
  } else if (targetListId) {
    const lists = await listLeadLists();
    targetListName = lists.find((l) => l.id === targetListId)?.name ?? "List";
  }

  // Fire individual createLead calls (HTTP/2 pipelines them efficiently).
  const results = await Promise.allSettled(
    payload.rows.map(async (row) => {
      const parts = (row.name ?? "Unknown").trim().split(/\s+/);
      const mergedTags = [
        ...(row.tags ?? []),
        ...(payload.segmentation.tags ?? []),
      ];
      return createLead({
        first_name: parts[0],
        last_name: parts.slice(1).join(" ") || null,
        email: row.email ?? null,
        phone: row.phone,
        company:
          row.company ??
          payload.segmentation.industry ??
          null,
        tags: mergedTags.length > 0 ? mergedTags : null,
        extra_data: {
          ...(row.custom_fields ?? {}),
          ...(payload.segmentation.custom_fields ?? {}),
        },
        lead_list_ids: targetListId ? [targetListId] : null,
      });
    })
  );

  const inserted = results.filter((r) => r.status === "fulfilled").length;
  const skippedDuplicates = results.filter(
    (r) =>
      r.status === "rejected" &&
      (r.reason as { response?: { status?: number } })?.response?.status === 409
  ).length;

  return {
    inserted,
    skipped_duplicates: skippedDuplicates,
    lead_list: { id: targetListId ?? "", name: targetListName },
  };
}

// --------------------------------------------------------------------------
// Error helper
// --------------------------------------------------------------------------

export function formatLeadApiError(err: unknown, fallback: string): string {
  const axiosErr = err as AxiosError<{ detail?: string }>;
  return axiosErr?.response?.data?.detail ?? fallback;
}
