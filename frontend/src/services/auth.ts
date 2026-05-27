import axios from "axios";

const API_BASE =
  import.meta.env.VITE_API_URL ?? "http://localhost:8001/api/v1";

export const api = axios.create({
  baseURL: API_BASE,
  headers: {
    "Content-Type": "application/json",
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
