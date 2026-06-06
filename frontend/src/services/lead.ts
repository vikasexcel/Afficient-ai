import { api } from "@/services/auth";
import type { AxiosError } from "axios";
import type {
  CreateLeadInput,
  CreateLeadListInput,
  Lead,
  LeadList,
  LeadListLeadsResponse,
  LeadListResponse,
  MembershipResponse,
  UpdateLeadInput,
  UpdateLeadListInput,
} from "@/types/lead";

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
// Error helper
// --------------------------------------------------------------------------

export function formatLeadApiError(err: unknown, fallback: string): string {
  const axiosErr = err as AxiosError<{ detail?: string }>;
  return axiosErr?.response?.data?.detail ?? fallback;
}
