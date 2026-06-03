import axios from "axios";

const API_BASE =
  import.meta.env.VITE_API_URL ?? "http://localhost:8001/api/v1";

// ngrok free tier serves an HTML interstitial to browser clients without
// this header; the page has no CORS headers, so XHR fails with a generic
// "blocked by CORS policy" error even though the API CORS config is fine.
const NGROK_SKIP_WARNING = API_BASE.includes("ngrok")
  ? { "ngrok-skip-browser-warning": "true" }
  : {};

export const api = axios.create({
  baseURL: API_BASE,
  headers: {
    "Content-Type": "application/json",
    ...NGROK_SKIP_WARNING,
  },
});

export type LoginInput = {
  email: string;
  password: string;
};

export type SignupInput = {
  full_name: string;
  organization: string;
  email: string;
  password: string;
};

/** Mirrors backend modules/auth/schema.py password rules. */
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 72;

export function validatePassword(password: string): string | null {
  const bytes = new TextEncoder().encode(password);
  if (bytes.length < PASSWORD_MIN_LENGTH) {
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters`;
  }
  if (bytes.length > PASSWORD_MAX_LENGTH) {
    return `Password must be at most ${PASSWORD_MAX_LENGTH} characters`;
  }
  if (!/[A-Za-z]/.test(password) || !/[^A-Za-z]/.test(password)) {
    return "Password must contain at least one letter and one number or symbol";
  }
  return null;
}

export function formatAuthError(err: unknown): string {
  if (!err || typeof err !== "object" || !("response" in err)) {
    return "Something went wrong. Please try again.";
  }
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    .response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object" || !("msg" in item)) return null;
        const msg = String((item as { msg: string }).msg);
        return msg.replace(/^Value error,\s*/i, "");
      })
      .filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  return "Something went wrong. Please try again.";
}

export type AuthTokens = {
  access_token: string;
  refresh_token: string;
};

export async function login(data: LoginInput): Promise<AuthTokens> {
  const res = await api.post<AuthTokens>("/auth/login", data);
  return res.data;
}

export async function signup(data: SignupInput) {
  const res = await api.post("/auth/register", data);
  return res.data;
}

export type CurrentUser = {
  id: string;
  full_name: string;
  email: string;
  role: "owner" | "admin" | "agent" | "member" | null;
  membership_id: string | null;
  organization: { id: string; name: string } | null;
};

export async function me(): Promise<CurrentUser> {
  const res = await api.get<CurrentUser>("/auth/me");
  return res.data;
}

export async function refresh(refresh_token: string) {
  const res = await api.post<{ access_token: string }>("/auth/refresh", {
    refresh_token,
  });
  return res.data;
}

export async function logout(refresh_token: string) {
  const res = await api.post("/auth/logout", { refresh_token });
  return res.data;
}
