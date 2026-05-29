import { api } from "./auth";

// ---------------------------------------------------------------------------
// Types — mirrored from backend/modules/ai/schema.py
// ---------------------------------------------------------------------------

export type MessageRole = "system" | "user" | "assistant" | "tool";

export type QualificationFramework = "BANT" | "MEDDICC";

export type QualificationStatus =
  | "not_started"
  | "in_progress"
  | "qualified"
  | "disqualified";

export type QualificationSnapshot = {
  framework: QualificationFramework;
  status: QualificationStatus;
  score: number;
  answered_fields: string[];
  pending_fields: string[];
  fields: Record<string, string | null>;
  last_updated: string | null;
};

// ---------------------------------------------------------------------------
// /ai/generate
// ---------------------------------------------------------------------------

export type GenerateInput = {
  prompt: string;
  system?: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
};

export type GenerateResult = {
  output: string;
  model: string;
  finish_reason: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
};

export async function generate(input: GenerateInput): Promise<GenerateResult> {
  const res = await api.post<GenerateResult>("/ai/generate", input);
  return res.data;
}

// ---------------------------------------------------------------------------
// /ai/converse
// ---------------------------------------------------------------------------

export type ConverseInput = {
  call_id: string;
  user_input: string;
  persona?: string;
  qualification_framework?: QualificationFramework;
  persist_transcript?: boolean;
  extra_context?: Record<string, unknown>;
};

export type ConverseResult = {
  call_id: string;
  reply: string;
  model: string;
  finish_reason: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  history_length: number;
  qualification: QualificationSnapshot;
};

export async function converse(input: ConverseInput): Promise<ConverseResult> {
  const res = await api.post<ConverseResult>("/ai/converse", input);
  return res.data;
}

// ---------------------------------------------------------------------------
// /ai/calls/{id}/...
// ---------------------------------------------------------------------------

export type TranscriptEntry = {
  role: MessageRole;
  content: string;
  ts: string;
  latency_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
};

export type TranscriptResult = {
  call_id: string;
  organization_id: string | null;
  entries: TranscriptEntry[];
};

export async function getTranscript(callId: string): Promise<TranscriptResult> {
  const res = await api.get<TranscriptResult>(
    `/ai/calls/${encodeURIComponent(callId)}/transcript`
  );
  return res.data;
}

export type QualificationGetResult = {
  call_id: string;
  qualification: QualificationSnapshot;
};

export async function getQualification(
  callId: string,
  framework?: QualificationFramework
): Promise<QualificationGetResult> {
  const res = await api.get<QualificationGetResult>(
    `/ai/calls/${encodeURIComponent(callId)}/qualification`,
    { params: framework ? { framework } : undefined }
  );
  return res.data;
}

export type CallSummary = {
  call_id: string;
  summary: string | null;
  qualification: QualificationSnapshot | null;
  total_turns: number;
  total_tokens: number;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
};

export async function finalizeCall(callId: string): Promise<CallSummary> {
  const res = await api.post<CallSummary>(
    `/ai/calls/${encodeURIComponent(callId)}/finalize`
  );
  return res.data;
}

// ---------------------------------------------------------------------------
// /ai/calls (list) + /ai/personas
// ---------------------------------------------------------------------------

export type CallListEntry = {
  call_id: string;
  persona: string | null;
  framework: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  summary: string | null;
  qualification_status: string | null;
  qualification_score: number | null;
  total_turns: number;
  total_tokens: number;
};

export async function listCalls(limit = 50): Promise<CallListEntry[]> {
  const res = await api.get<{ calls: CallListEntry[] }>("/ai/calls", {
    params: { limit },
  });
  return res.data.calls;
}

export type Persona = {
  name: string;
  description: string;
  default_objective: string;
};

export async function listPersonas(): Promise<Persona[]> {
  const res = await api.get<{ personas: Persona[] }>("/ai/personas");
  return res.data.personas;
}
