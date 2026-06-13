import type { BusinessHours } from "@/types/campaign";

export interface WizardDraft {
  // Step 1
  name: string;
  timezone: string;

  // Step 2
  lead_list_id: string | null;
  lead_list_name: string | null;
  lead_count: number | null;

  // Step 3
  workflow_nodes: unknown[];
  workflow_edges: unknown[];
  workflow_template_name: string | null;

  // Step 4
  start_immediately: boolean;
  scheduled_date: string | null;
  scheduled_time: string | null;
  business_hours: BusinessHours;
}

export const DRAFT_STORAGE_KEY = "campaign_wizard_draft";

export function defaultDraft(): WizardDraft {
  const tz =
    typeof Intl !== "undefined"
      ? Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
      : "UTC";
  return {
    name: "",
    timezone: tz,
    lead_list_id: null,
    lead_list_name: null,
    lead_count: null,
    workflow_nodes: [],
    workflow_edges: [],
    workflow_template_name: null,
    start_immediately: true,
    scheduled_date: null,
    scheduled_time: null,
    business_hours: {
      days: ["mon", "tue", "wed", "thu", "fri"],
      start: "09:00",
      end: "18:00",
      skip_holidays: true,
    },
  };
}

export const WIZARD_STEPS = [
  { id: 1, label: "Details" },
  { id: 2, label: "Leads" },
  { id: 3, label: "Workflow" },
  { id: 4, label: "Schedule" },
  { id: 5, label: "Review" },
] as const;

export const COMMON_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Anchorage",
  "Pacific/Honolulu",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Moscow",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Australia/Sydney",
  "Pacific/Auckland",
];
