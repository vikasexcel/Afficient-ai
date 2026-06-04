import type { AxiosError } from "axios";

type ApiErrorBody = {
  detail?: string | { msg?: string; loc?: unknown[] }[];
};

/**
 * Turn an axios/API failure into a short, user-facing message.
 * Handles 404, 405, 500, and FastAPI validation error arrays.
 */
export function formatApiError(
  err: unknown,
  fallback = "Something went wrong. Please try again."
): string {
  if (!err || typeof err !== "object") {
    return err instanceof Error ? err.message : fallback;
  }

  const axiosErr = err as AxiosError<ApiErrorBody>;
  const status = axiosErr.response?.status;
  const detail = axiosErr.response?.data?.detail;

  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object" || !("msg" in item)) return null;
        return String(item.msg).replace(/^Value error,\s*/i, "");
      })
      .filter(Boolean);
    if (messages.length) return messages.join(" · ");
  }

  if (status === 404) {
    return "The requested resource was not found.";
  }
  if (status === 405) {
    return "This action is not supported by the server. Try refreshing or contact support.";
  }
  if (status === 409) {
    return "This conflicts with existing data (for example, a duplicate phone number).";
  }
  if (status === 422) {
    return "Please check the form and fix any invalid fields.";
  }
  if (status && status >= 500) {
    return "A server error occurred. Please try again in a moment.";
  }

  if (axiosErr.message) {
    return axiosErr.message;
  }
  return fallback;
}
