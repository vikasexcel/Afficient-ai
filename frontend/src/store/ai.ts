import { create } from "zustand";

import {
  converse,
  finalizeCall,
  getQualification,
  getTranscript,
  type CallSummary,
  type ConverseResult,
  type QualificationFramework,
  type QualificationSnapshot,
  type TranscriptEntry,
} from "@/services/ai";

export type ChatBubble = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  ts: number;
  /** Set on assistant bubbles after a converse call completes. */
  latency_ms?: number;
  total_tokens?: number;
};

type Status = "idle" | "sending" | "finalizing";

type AIStore = {
  callId: string | null;
  persona: string | null;
  framework: QualificationFramework;

  status: Status;
  error: string | null;

  bubbles: ChatBubble[];
  qualification: QualificationSnapshot | null;
  summary: CallSummary | null;

  // ----- lifecycle -----
  start: (opts: {
    callId: string;
    persona?: string;
    framework?: QualificationFramework;
  }) => void;
  reset: () => void;

  // ----- chat -----
  send: (userInput: string) => Promise<ConverseResult | null>;

  // ----- post-call -----
  finalize: () => Promise<CallSummary | null>;
  refreshQualification: () => Promise<void>;
  loadTranscript: () => Promise<TranscriptEntry[]>;
};

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

export const useAI = create<AIStore>((set, get) => ({
  callId: null,
  persona: null,
  framework: "BANT",

  status: "idle",
  error: null,

  bubbles: [],
  qualification: null,
  summary: null,

  start({ callId, persona, framework }) {
    set({
      callId,
      persona: persona ?? null,
      framework: framework ?? "BANT",
      status: "idle",
      error: null,
      bubbles: [],
      qualification: null,
      summary: null,
    });
  },

  reset() {
    set({
      callId: null,
      persona: null,
      framework: "BANT",
      status: "idle",
      error: null,
      bubbles: [],
      qualification: null,
      summary: null,
    });
  },

  async send(userInput) {
    const trimmed = userInput.trim();
    const { callId, persona, framework, status } = get();
    if (!trimmed || !callId || status !== "idle") return null;

    const userBubble: ChatBubble = {
      id: uid(),
      role: "user",
      text: trimmed,
      ts: Date.now(),
    };
    set({
      status: "sending",
      error: null,
      bubbles: [...get().bubbles, userBubble],
    });

    try {
      const result = await converse({
        call_id: callId,
        user_input: trimmed,
        persona: persona ?? undefined,
        qualification_framework: framework,
        persist_transcript: true,
      });
      const assistantBubble: ChatBubble = {
        id: uid(),
        role: "assistant",
        text: result.reply,
        ts: Date.now(),
        latency_ms: result.latency_ms,
        total_tokens: result.total_tokens,
      };
      set({
        status: "idle",
        bubbles: [...get().bubbles, assistantBubble],
        qualification: result.qualification,
      });
      return result;
    } catch (err) {
      const message = extractMessage(err);
      set({ status: "idle", error: message });
      return null;
    }
  },

  async finalize() {
    const { callId } = get();
    if (!callId) return null;
    set({ status: "finalizing", error: null });
    try {
      const summary = await finalizeCall(callId);
      set({
        status: "idle",
        summary,
        qualification: summary.qualification ?? get().qualification,
      });
      return summary;
    } catch (err) {
      set({ status: "idle", error: extractMessage(err) });
      return null;
    }
  },

  async refreshQualification() {
    const { callId, framework } = get();
    if (!callId) return;
    try {
      const result = await getQualification(callId, framework);
      set({ qualification: result.qualification });
    } catch (err) {
      set({ error: extractMessage(err) });
    }
  },

  async loadTranscript() {
    const { callId } = get();
    if (!callId) return [];
    try {
      const result = await getTranscript(callId);
      return result.entries;
    } catch (err) {
      set({ error: extractMessage(err) });
      return [];
    }
  },
}));

function extractMessage(err: unknown): string {
  if (typeof err === "object" && err !== null) {
    // axios error
    const anyErr = err as {
      response?: { data?: { detail?: string } };
      message?: string;
    };
    if (anyErr.response?.data?.detail) return anyErr.response.data.detail;
    if (anyErr.message) return anyErr.message;
  }
  return "Unknown error";
}
