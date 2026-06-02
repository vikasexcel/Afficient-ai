/** Browsers only expose getUserMedia in secure contexts (HTTPS or localhost). */
export function microphoneUnavailableReason(): string | null {
  if (typeof window === "undefined") return null;

  if (!window.isSecureContext) {
    return (
      "Microphone access requires HTTPS (or localhost). " +
      "You are on plain HTTP at a public address — use an https:// URL " +
      "(e.g. ngrok for the frontend) instead of http://<server-ip>:port."
    );
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    return (
      "Microphone APIs are not available in this browser context. " +
      "Try Chrome/Firefox over HTTPS or open the app at http://localhost."
    );
  }

  return null;
}

export function assertMicrophoneAvailable(): void {
  const reason = microphoneUnavailableReason();
  if (reason) throw new Error(reason);
}

/** Map LiveKit / WebRTC errors to a clearer message when mediaDevices is missing. */
export function normalizeMediaError(err: unknown): string {
  const raw =
    err instanceof Error ? err.message : String(err ?? "Unknown error");
  if (
    /getUserMedia/i.test(raw) ||
    /mediaDevices/i.test(raw) ||
    /undefined.*reading/i.test(raw)
  ) {
    return (
      microphoneUnavailableReason() ??
      "Microphone unavailable. Use HTTPS or localhost to join with audio."
    );
  }
  return raw;
}
