export type CampaignStatus =
  | "draft"
  | "scheduled"
  | "active"
  | "paused"
  | "completed"
  | "archived";

export type RetryConfig = {
  max_attempts: number;
  backoff_minutes: number;
  retry_on: string[];
};

/** AMD / Voicemail-drop configuration (campaign voicemail settings). */
export type VoicemailConfig = {
  voicemail_enabled: boolean;
  voicemail_message_url: string | null;
  retry_on_voicemail: boolean;
  amd_unknown_fallback: "human" | "voicemail";
};

/** Campaign metrics (GET /campaigns/{id}/metrics). */
export type CampaignMetrics = {
  campaign_id: string;
  status: string;
  total_leads: number;
  queued_leads: number;
  active_calls: number;
  completed_calls: number;
  failed_calls: number;
  pending_leads: number;
  progress_percent: number;
  retry_count: number;
  retry_success_rate: number;
  exhausted_retries: number;
  average_attempts_per_call: number;
  // AMD / Voicemail-drop.
  human_answered: number;
  voicemail_detected: number;
  voicemail_dropped: number;
  voicemail_retry_count: number;
  voicemail_success_rate: number;
};

export type Campaign = {
  id: string;
  name: string;
  status: CampaignStatus;
  prompt_template?: string;
  playbook_id?: string | null;
  lead_list_id?: string | null;
  scheduled_at?: string | null;
  timezone?: string | null;
  business_hours?: BusinessHours | null;
  created_at?: string;
  updated_at?: string;
};

/** Full campaign record returned by the backend (GET /campaigns). */
export type CampaignOut = {
  id: string;
  name: string;
  status: CampaignStatus | string;
  playbook_id: string | null;
  lead_list_id: string | null;
  scheduled_at: string | null;
  timezone: string | null;
  business_hours: BusinessHours | null;
  retry_config: RetryConfig | null;
  voicemail_config: VoicemailConfig | null;
  created_at: string;
  updated_at: string;
  playbook_name: string | null;
  lead_list_name: string | null;
  lead_count: number | null;
};

export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

export const WEEKDAYS: { id: Weekday; short: string; long: string }[] = [
  { id: "mon", short: "Mon", long: "Monday" },
  { id: "tue", short: "Tue", long: "Tuesday" },
  { id: "wed", short: "Wed", long: "Wednesday" },
  { id: "thu", short: "Thu", long: "Thursday" },
  { id: "fri", short: "Fri", long: "Friday" },
  { id: "sat", short: "Sat", long: "Saturday" },
  { id: "sun", short: "Sun", long: "Sunday" },
];

export type BusinessHours = {
  /** Days the campaign may dial on. */
  days: Weekday[];
  /** 24h "HH:mm" window start. */
  start: string;
  /** 24h "HH:mm" window end. */
  end: string;
  /** Skip national holidays (best-effort, surface-only flag for now). */
  skip_holidays: boolean;
};

export type CampaignDraft = {
  name: string;
  playbook_id: string | null;
  lead_list_id: string | null;
  schedule: {
    /** Local date "YYYY-MM-DD". */
    date: string | null;
    /** Local time "HH:mm". */
    time: string | null;
    /** IANA timezone, e.g. "Asia/Kolkata". */
    timezone: string;
    /** If true, start immediately on launch (ignores date/time). */
    start_immediately: boolean;
  };
  business_hours: BusinessHours;
};

export type CampaignCreateInput = CampaignDraft & {
  /** Activate the campaign immediately after creation. */
  launch: boolean;
};
