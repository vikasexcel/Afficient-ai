import { api } from "./auth";

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export interface DailyDataPoint {
  date: string;
  count: number;
}

export interface DailyEmailPoint {
  date: string;
  sent: number;
  failed: number;
}

export interface DailyCallPoint {
  date: string;
  attempted: number;
  completed: number;
  voicemail: number;
}

export interface DailyLinkedInPoint {
  date: string;
  connections: number;
  messages: number;
  failed: number;
}

export interface DailyExecutionPoint {
  date: string;
  total: number;
  completed: number;
  failed: number;
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

export interface CampaignSummary {
  total: number;
  active: number;
  completed: number;
  draft: number;
  paused: number;
  scheduled: number;
  archived: number;
}

export interface ExecutionSummary {
  total: number;
  completed: number;
  failed: number;
  running: number;
  queued: number;
  completion_rate: number;
  failure_rate: number;
}

export interface LeadSummary {
  total: number;
  new: number;
  contacted: number;
  qualified: number;
  converted: number;
  lost: number;
}

export interface OverviewData {
  campaigns: CampaignSummary;
  executions: ExecutionSummary;
  leads: LeadSummary;
  total_leads_processed: number;
}

// ---------------------------------------------------------------------------
// Channel analytics
// ---------------------------------------------------------------------------

export interface EmailAnalyticsData {
  sent: number;
  failed: number;
  success_rate: number;
  daily_trend: DailyEmailPoint[];
}

export interface CallAnalyticsData {
  attempted: number;
  completed: number;
  failed: number;
  voicemail: number;
  daily_trend: DailyCallPoint[];
}

export interface LinkedInAnalyticsData {
  connections_sent: number;
  messages_sent: number;
  failed: number;
  daily_trend: DailyLinkedInPoint[];
}

// ---------------------------------------------------------------------------
// Funnel
// ---------------------------------------------------------------------------

export interface FunnelStep {
  label: string;
  count: number;
  pct: number;
}

export interface FunnelData {
  steps: FunnelStep[];
}

// ---------------------------------------------------------------------------
// Workflow analytics
// ---------------------------------------------------------------------------

export interface WorkflowUsageStat {
  workflow_id: string;
  campaign_id: string;
  campaign_name: string;
  execution_count: number;
}

export interface NodeTypeStat {
  node_type: string;
  count: number;
}

export interface WorkflowAnalyticsData {
  most_used_workflows: WorkflowUsageStat[];
  node_type_distribution: NodeTypeStat[];
  total_workflows: number;
  total_executions_in_period: number;
}

// ---------------------------------------------------------------------------
// Trends
// ---------------------------------------------------------------------------

export interface TrendsData {
  executions_per_day: DailyExecutionPoint[];
  campaign_growth: DailyDataPoint[];
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export const analyticsApi = {
  overview: (days = 30): Promise<OverviewData> =>
    api.get("/analytics/overview", { params: { days } }).then((r) => r.data),

  email: (days = 30): Promise<EmailAnalyticsData> =>
    api.get("/analytics/email", { params: { days } }).then((r) => r.data),

  calls: (days = 30): Promise<CallAnalyticsData> =>
    api.get("/analytics/calls", { params: { days } }).then((r) => r.data),

  linkedin: (days = 30): Promise<LinkedInAnalyticsData> =>
    api.get("/analytics/linkedin", { params: { days } }).then((r) => r.data),

  funnel: (days = 30): Promise<FunnelData> =>
    api.get("/analytics/funnel", { params: { days } }).then((r) => r.data),

  workflow: (days = 30): Promise<WorkflowAnalyticsData> =>
    api.get("/analytics/workflow", { params: { days } }).then((r) => r.data),

  trends: (days = 30): Promise<TrendsData> =>
    api.get("/analytics/trends", { params: { days } }).then((r) => r.data),
};
