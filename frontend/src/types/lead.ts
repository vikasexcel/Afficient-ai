export type LeadStatus =
  | "new"
  | "contacted"
  | "qualified"
  | "converted"
  | "lost";

export type Lead = {
  id: string;
  lead_list_id: string | null;
  name: string;
  email: string | null;
  phone: string;
  company: string | null;
  industry: string | null;
  location: string | null;
  source: string | null;
  status: LeadStatus;
  tags: string[] | null;
  custom_fields: Record<string, unknown> | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type LeadList = {
  id: string;
  name: string;
  description: string | null;
  source: string | null;
  lead_count: number;
  created_at: string;
  updated_at: string;
};

export type ActivityType = "call" | "email" | "meeting" | "note";

export type LeadActivity = {
  id: string;
  lead_id: string;
  user_id: string | null;
  activity_type: ActivityType;
  notes: string | null;
  created_at: string;
};

export type CreateLeadInput = {
  name: string;
  phone: string;
  email?: string | null;
  company?: string | null;
  industry?: string | null;
  location?: string | null;
  source?: string | null;
  status?: LeadStatus;
  lead_list_id?: string | null;
  tags?: string[] | null;
};

export type UpdateLeadInput = {
  name?: string;
  phone?: string;
  email?: string | null;
  company?: string | null;
  industry?: string | null;
  status?: LeadStatus;
  tags?: string[] | null;
};

/** A canonical column id our auto-mapper understands. */
export type LeadColumnId =
  | "name"
  | "email"
  | "phone"
  | "company"
  | "industry"
  | "location"
  | "tags";

export type DetectedColumns = Record<LeadColumnId, string | null>;

export type ParsedRowStatus = "valid" | "invalid" | "duplicate";

export type ParsedRow = {
  /** 1-indexed row number that matches the user's spreadsheet (header = 1). */
  row_number: number;
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
};

export type UploadStats = {
  total: number;
  valid: number;
  invalid: number;
  duplicate: number;
};

export type UploadPreview = {
  rows: ParsedRow[];
  detected_columns: DetectedColumns;
  stats: UploadStats;
};

export type UploadSegmentation = {
  industry: string | null;
  location: string | null;
  tags: string[];
  custom_fields: Record<string, string>;
};

export type CommitRow = {
  name: string;
  email: string | null;
  phone: string;
  company: string | null;
  industry: string | null;
  location: string | null;
  tags: string[] | null;
  custom_fields: Record<string, string> | null;
};

export type CommitUploadPayload = {
  rows: CommitRow[];
  segmentation: UploadSegmentation;
  lead_list_id: string | null;
  new_list_name: string | null;
  source: string | null;
};

export type CommitUploadResult = {
  inserted: number;
  skipped_duplicates: number;
  lead_list: LeadList;
};
