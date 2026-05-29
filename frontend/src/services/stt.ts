import { api } from "./auth";

/**
 * Deepgram STT smoke endpoint. The backend joins the room as a
 * subscribe-only agent for `duration_seconds`, pumps audio into
 * Deepgram, and returns the collected events.
 *
 * Production conversation flows do NOT use this endpoint — they run
 * inside the ConversationOrchestrator worker. This is a debugging tool
 * surfaced on the Calls page so an operator can verify the audio path
 * before kicking off a real AI agent.
 */

export type TranscriptEventKind =
  | "speech_started"
  | "partial"
  | "final"
  | "utterance_end";

export type TranscriptEvent = {
  kind: TranscriptEventKind;
  text: string;
  is_final: boolean;
  confidence: number | null;
  ts_ms: number;
  speech_final: boolean | null;
};

export type TranscribeInput = {
  room: string;
  participant_identity?: string | null;
  duration_seconds?: number;
  interim_results?: boolean | null;
  language?: string | null;
};

export type TranscribeResult = {
  room: string;
  participant_identity: string | null;
  duration_ms: number;
  events: TranscriptEvent[];
};

export async function transcribe(
  input: TranscribeInput
): Promise<TranscribeResult> {
  const res = await api.post<TranscribeResult>("/stt/transcribe", input);
  return res.data;
}
