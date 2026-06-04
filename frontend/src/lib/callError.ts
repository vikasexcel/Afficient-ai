import type { CallStatus, TelephonyCall } from "@/services/telephony";

/**
 * Translation layer that turns raw Twilio / SIP / Twirp telephony errors
 * into short, user-facing copy. Raw codes + messages are preserved on the
 * returned object so they can still be surfaced in a tooltip or debug mode
 * (and they always remain in the network logs).
 */

export type FriendlyCall = {
  /** Short status label for the badge, e.g. "Call failed". */
  statusLabel: string;
  /** Badge tone class group. */
  tone: "neutral" | "info" | "progress" | "success" | "warning" | "error";
  /** One-line user-facing reason, or null when no explanation is needed. */
  reason: string | null;
  /** Whether a Retry action makes sense for this call. */
  canRetry: boolean;
  /** Raw technical detail (code + message) for tooltips / debug only. */
  rawDetail: string | null;
};

const STATUS_LABELS: Record<CallStatus, string> = {
  queued: "Queued",
  initiated: "Connecting",
  ringing: "Ringing",
  "in-progress": "In progress",
  completed: "Completed",
  failed: "Call failed",
  busy: "Busy",
  "no-answer": "No answer",
  canceled: "Canceled",
};

const STATUS_TONES: Record<CallStatus, FriendlyCall["tone"]> = {
  queued: "neutral",
  initiated: "info",
  ringing: "warning",
  "in-progress": "progress",
  completed: "success",
  failed: "error",
  busy: "warning",
  "no-answer": "warning",
  canceled: "neutral",
};

// Friendly copy keyed by a normalized reason bucket.
const REASON_COPY = {
  international:
    "This phone number cannot be called because international calling is not enabled for your account.",
  timeout: "The call was not answered.",
  busy: "The recipient's line is currently busy.",
  noAnswer: "The recipient did not answer.",
  network: "The call could not be completed due to a network issue.",
  invalidNumber: "The phone number appears to be invalid.",
  canceled: "This call was canceled.",
  unknown: "The call could not be completed. Please try again.",
} as const;

// Twilio error codes → reason bucket. Covers the common outbound failures.
const TWILIO_CODE_BUCKETS: Record<string, keyof typeof REASON_COPY> = {
  // Geographic / international permission errors.
  "13227": "international",
  "21215": "international",
  "21408": "international",
  // Invalid / unreachable destination numbers.
  "13224": "invalidNumber",
  "21211": "invalidNumber",
  "21214": "invalidNumber",
  "13223": "invalidNumber",
  // Timeouts.
  "31003": "timeout",
  "408": "timeout",
};

const RETRYABLE_STATUSES: CallStatus[] = [
  "failed",
  "busy",
  "no-answer",
  "canceled",
];

function bucketFromText(text: string): keyof typeof REASON_COPY | null {
  const t = text.toLowerCase();
  if (
    t.includes("international") ||
    t.includes("geo") ||
    t.includes("not authorized to call") ||
    t.includes("no international permission") ||
    t.includes("permission")
  ) {
    return "international";
  }
  if (t.includes("invalid") && (t.includes("number") || t.includes("phone"))) {
    return "invalidNumber";
  }
  if (t.includes("timed out") || t.includes("timeout")) {
    return "timeout";
  }
  if (t.includes("busy")) {
    return "busy";
  }
  if (
    t.includes("network") ||
    t.includes("connection") ||
    t.includes("unavailable") ||
    t.includes("sip") ||
    t.includes("twirp")
  ) {
    return "network";
  }
  return null;
}

export function describeCall(call: TelephonyCall): FriendlyCall {
  const statusLabel = STATUS_LABELS[call.status] ?? call.status;
  const tone = STATUS_TONES[call.status] ?? "neutral";
  const canRetry = RETRYABLE_STATUSES.includes(call.status);

  const rawParts: string[] = [];
  if (call.error_code) rawParts.push(`code ${call.error_code}`);
  if (call.error_message) rawParts.push(call.error_message);
  const rawDetail = rawParts.length ? rawParts.join(": ") : null;

  let reason: string | null = null;

  // Status-driven defaults first.
  if (call.status === "busy") reason = REASON_COPY.busy;
  else if (call.status === "no-answer") reason = REASON_COPY.noAnswer;
  else if (call.status === "canceled") reason = REASON_COPY.canceled;

  // A specific failure reason (code or message) overrides the default.
  if (call.status === "failed" || call.error_code || call.error_message) {
    let bucket: keyof typeof REASON_COPY | null = null;
    if (call.error_code && TWILIO_CODE_BUCKETS[String(call.error_code)]) {
      bucket = TWILIO_CODE_BUCKETS[String(call.error_code)];
    }
    if (!bucket && call.error_message) {
      bucket = bucketFromText(call.error_message);
    }
    if (!bucket && call.status === "failed") {
      bucket = "unknown";
    }
    if (bucket) reason = REASON_COPY[bucket];
  }

  return { statusLabel, tone, reason, canRetry, rawDetail };
}

/**
 * Map an axios error (thrown when an action like dial/retry/delete fails)
 * to friendly copy using the same buckets, with HTTP-status fallbacks.
 */
export function friendlyActionError(
  err: unknown,
  fallback: string = REASON_COPY.unknown
): string {
  const response = (
    err as { response?: { status?: number; data?: { detail?: unknown } } }
  )?.response;
  const status = response?.status;
  const detail = response?.data?.detail;

  const detailText =
    typeof detail === "string"
      ? detail
      : err instanceof Error
        ? err.message
        : "";

  if (detailText) {
    const bucket = bucketFromText(detailText);
    if (bucket) return REASON_COPY[bucket];
  }

  if (status === 403) return REASON_COPY.international;
  if (status === 408) return REASON_COPY.timeout;
  if (status === 404) return "This call record no longer exists.";
  if (status && status >= 500) return REASON_COPY.network;

  // Surface a concrete server message if it's already human-readable.
  if (typeof detail === "string" && detail.trim()) return detail;
  return fallback;
}
