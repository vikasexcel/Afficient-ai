/** Types matching the Phase 3A backend schemas. */

export interface WorkflowNode {
  id: string;
  type: string; // CALL | EMAIL | WAIT | CONDITION | LINKEDIN | STOP
  label?: string;
  position?: { x: number; y: number }; // persisted via extra="allow" on backend
  [key: string]: unknown;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition?: string | null; // "TRUE" | "FALSE" | null
}

export interface WorkflowGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface WorkflowGraphResponse {
  workflow_id: string;
  campaign_id: string;
  state: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  node_count: number;
  edge_count: number;
  is_graph: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkflowValidationResponse {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Per-node config schemas
// ---------------------------------------------------------------------------

export interface EmailConfig {
  subject: string;
  body: string;
}

export interface CallConfig {
  playbook_id: string;
  retry_count: number;
  /** Optional phone number override — when set, this number is dialled instead
   * of the lead's phone. Used by the Email Reply → Call Follow-Up workflow. */
  to_number?: string;
}

export interface WaitConfig {
  duration: number;
  unit: "minutes" | "hours" | "days";
}

export interface ConditionConfig {
  condition_type: "EMAIL_SENT" | "EMAIL_FAILED" | "EMAIL_REPLIED" | "NEGATIVE_REPLY" | "CALL_COMPLETED" | "CALL_FAILED";
  /** For EMAIL_REPLIED / NEGATIVE_REPLY: minutes after send within which a reply counts as timely. */
  window_minutes?: number;
}

export interface LinkedinConfig {
  action: "CONNECT" | "MESSAGE";
  message: string;
}

export type NodeConfig = EmailConfig | CallConfig | WaitConfig | ConditionConfig | LinkedinConfig;

// ---------------------------------------------------------------------------
// Workflow template types (GET/POST /workflow-templates)
// ---------------------------------------------------------------------------

export interface WorkflowTemplate {
  id: string;
  organization_id: string | null;
  name: string;
  description: string | null;
  category: string | null;
  is_system: boolean;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  created_at: string;
  updated_at: string;
}

export interface WorkflowTemplateListResponse {
  templates: WorkflowTemplate[];
  total: number;
}

// ---------------------------------------------------------------------------
// Workflow version history types (Phase 3C)
// ---------------------------------------------------------------------------

export interface WorkflowVersionSummary {
  version: number;
  workflow_id: string;
  created_at: string;
  created_by: string | null;
}

export interface WorkflowVersionDetail {
  version: number;
  workflow_id: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  created_at: string;
  created_by: string | null;
}

export interface WorkflowVersionListResponse {
  workflow_id: string;
  versions: WorkflowVersionSummary[];
  total: number;
}

export interface WorkflowRestoreResponse {
  workflow_id: string;
  restored_from_version: number;
  new_version: number;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

/** React Flow node data payload. */
export interface NodeData extends Record<string, unknown> {
  type: string;
  label?: string;
  config?: NodeConfig;
}

// ---------------------------------------------------------------------------
// Workflow test-run types
// ---------------------------------------------------------------------------

export interface WorkflowTestRequest {
  test_email: string;
  test_phone?: string;
  skip_wait?: boolean;
}

export interface WorkflowTestLogEntry {
  step: number;
  node_id: string;
  node_type: string;
  node_label: string;
  status: "running" | "completed" | "skipped" | "failed" | "condition_true" | "condition_false";
  message: string;
  output?: Record<string, unknown> | null;
  timestamp: string;
}

export interface WorkflowTestResponse {
  workflow_id: string;
  test_email: string;
  test_phone: string;
  result: "completed" | "stopped" | "failed";
  logs: WorkflowTestLogEntry[];
  error?: string | null;
}
