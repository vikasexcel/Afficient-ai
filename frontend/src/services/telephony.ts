import { api } from "./auth";

// ---------------------------------------------------------------------------
// Types — mirror of backend/modules/telephony/schema.py
// ---------------------------------------------------------------------------

export type CallStatus =
  | "queued"
  | "initiated"
  | "ringing"
  | "in-progress"
  | "completed"
  | "failed"
  | "busy"
  | "no-answer"
  | "canceled";

export type CallDirection = "outbound" | "inbound";

export type TelephonyCall = {
  id: string;
  call_sid: string | null;
  room_name: string;
  direction: CallDirection;
  status: CallStatus;
  from_number: string;
  to_number: string;
  lead_id: string | null;
  lead_name: string | null;
  lead_phone: string | null;
  campaign_id: string | null;
  queued_at: string;
  initiated_at: string | null;
  ringing_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  price: number | null;
  price_unit: string | null;
  error_code: string | null;
  error_message: string | null;
  retry_count: number;
  extra: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type CallEvent = {
  id: string;
  call_sid: string | null;
  event_type: string;
  source: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

export type InitiateCallInput = {
  to_number: string;
  from_number?: string;
  lead_id?: string;
  lead_name?: string;
  lead_phone?: string;
  campaign_id?: string;
  persona?: string;
  qualification_framework?: "BANT" | "MEDDICC";
  opening_line?: string;
  extra_context?: Record<string, unknown>;
  record?: boolean;
  dial_timeout_seconds?: number;
  answering_machine_detection?: boolean;
  room_name?: string;
};

export async function initiateCall(
  input: InitiateCallInput
): Promise<TelephonyCall> {
  const res = await api.post<TelephonyCall>("/telephony/calls", input);
  return res.data;
}

export async function listCalls(
  params: { limit?: number; status?: CallStatus } = {}
): Promise<TelephonyCall[]> {
  const res = await api.get<{ calls: TelephonyCall[] }>("/telephony/calls", {
    params,
  });
  return res.data.calls;
}

export async function getCall(callId: string): Promise<TelephonyCall> {
  const res = await api.get<TelephonyCall>(
    `/telephony/calls/${encodeURIComponent(callId)}`
  );
  return res.data;
}

export async function getCallBySid(callSid: string): Promise<TelephonyCall> {
  const res = await api.get<TelephonyCall>(
    `/telephony/calls/by-sid/${encodeURIComponent(callSid)}`
  );
  return res.data;
}

export async function listCallEvents(callId: string): Promise<CallEvent[]> {
  const res = await api.get<{ events: CallEvent[] }>(
    `/telephony/calls/${encodeURIComponent(callId)}/events`
  );
  return res.data.events;
}

export type RetryResult = {
  original_call_id: string;
  new_call: TelephonyCall;
};

export async function retryCall(callId: string): Promise<RetryResult> {
  const res = await api.post<RetryResult>(
    `/telephony/calls/${encodeURIComponent(callId)}/retry`
  );
  return res.data;
}

export async function cancelCall(callId: string): Promise<TelephonyCall> {
  const res = await api.post<TelephonyCall>(
    `/telephony/calls/${encodeURIComponent(callId)}/cancel`
  );
  return res.data;
}
