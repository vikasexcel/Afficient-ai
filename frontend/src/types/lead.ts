// Lead management types — Phase 1

export type LeadStatus =
  | "new"
  | "contacted"
  | "qualified"
  | "converted"
  | "lost";

export interface Lead {
  id: string;
  organization_id: string;
  first_name: string;
  last_name: string | null;
  email: string | null;
  phone: string;
  linkedin_url: string | null;
  company: string | null;
  job_title: string | null;
  status: LeadStatus;
  tags: string[] | null;
  extra_data: Record<string, unknown> | null;
  lead_list_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface LeadList {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

// --------------------------------------------------------------------------
// Request payloads
// --------------------------------------------------------------------------

export interface CreateLeadInput {
  first_name: string;
  last_name?: string | null;
  email?: string | null;
  phone: string;
  linkedin_url?: string | null;
  company?: string | null;
  job_title?: string | null;
  status?: LeadStatus;
  tags?: string[] | null;
  extra_data?: Record<string, unknown> | null;
  lead_list_ids?: string[] | null;
}

export interface UpdateLeadInput {
  first_name?: string;
  last_name?: string | null;
  email?: string | null;
  phone?: string;
  linkedin_url?: string | null;
  company?: string | null;
  job_title?: string | null;
  status?: LeadStatus;
  tags?: string[] | null;
  extra_data?: Record<string, unknown> | null;
}

export interface CreateLeadListInput {
  name: string;
  description?: string | null;
}

export interface UpdateLeadListInput {
  name?: string;
  description?: string | null;
}

// --------------------------------------------------------------------------
// Response shapes
// --------------------------------------------------------------------------

export interface LeadListLeadsResponse {
  leads: Lead[];
  total: number;
}

export interface LeadListResponse {
  lead_lists: LeadList[];
}

export interface MembershipResponse {
  added?: number;
  removed?: number;
  already_member?: number;
  not_member?: number;
}

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

/** Return "First Last" or just "First" when last_name is absent. */
export function leadFullName(lead: Pick<Lead, "first_name" | "last_name">): string {
  return [lead.first_name, lead.last_name].filter(Boolean).join(" ");
}
