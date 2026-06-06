export interface MonitorExecution {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  lead_id: string | null;
  lead_name: string | null;
  lead_email: string | null;
  lead_phone: string | null;
  current_node_id: string | null;
  attempt_number: number;
  outcome: string | null;
  retry_status: string | null;
  next_retry_at: string | null;
  last_failure_reason: string | null;
  node_outputs: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface CampaignMonitorPayload {
  campaign_id: string;
  campaign_name: string;
  campaign_status: string;
  campaign_created_at: string;
  lead_list_id: string | null;
  metrics: {
    total_leads: number;
    queued_leads: number;
    active_calls: number;
    completed_calls: number;
    failed_calls: number;
    failed_executions: number;
    pending_leads: number;
    progress_percent: number;
    retry_count: number;
    retry_success_rate: number;
    exhausted_retries: number;
    average_attempts_per_call: number;
    scheduled_retries?: number;
    [key: string]: unknown;
  };
  executions: MonitorExecution[];
  workflow_nodes: Array<{ id: string; type: string; label?: string; [key: string]: unknown }>;
  workflow_edges: Array<{ id: string; source: string; target: string; [key: string]: unknown }>;
}
