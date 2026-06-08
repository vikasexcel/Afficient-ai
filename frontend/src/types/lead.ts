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
  /** Optional override label. Falls back to first_name + last_name when null. */
  display_name: string | null;
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
  /** Populated by GET /lead-lists since backend now returns it. */
  lead_count: number;
  /** Not in current API response; reserved for future use. */
  source?: string | null;
  created_at: string;
  updated_at: string;
}

// --------------------------------------------------------------------------
// Request payloads
// --------------------------------------------------------------------------

export interface CreateLeadInput {
  display_name?: string | null;
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
  display_name?: string | null;
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

/**
 * Primary display label for a lead.
 * Uses display_name when set; falls back to first_name + last_name.
 */
export function leadDisplayName(
  lead: Pick<Lead, "display_name" | "first_name" | "last_name">
): string {
  const dn = lead.display_name?.trim();
  return dn || leadFullName(lead);
}

// --------------------------------------------------------------------------
// CSV import types (shared between lib/csvParser and lib/csv)
// --------------------------------------------------------------------------

export type ParsedRowStatus = "valid" | "invalid" | "duplicate";

export interface ParsedRow {
  row_number: number;
  display_name: string | null;
  name: string | null;
  email: string | null;
  phone: string | null;
  company: string | null;
  industry: string | null;
  location: string | null;
  tags: string[] | null;
  custom_fields: Record<string, string> | null;
  status: ParsedRowStatus;
  errors: string[];
}

export interface UploadPreview {
  rows: ParsedRow[];
  stats: {
    total: number;
    valid: number;
    invalid: number;
    duplicate: number;
  };
}

export interface CommitUploadResult {
  inserted: number;
  skipped_duplicates: number;
  lead_list: { id: string; name: string };
}
