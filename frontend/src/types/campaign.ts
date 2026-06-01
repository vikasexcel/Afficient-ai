export type CampaignStatus = "draft" | "scheduled" | "active" | "paused" | "archived";

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
