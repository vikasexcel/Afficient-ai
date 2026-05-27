import { create } from "zustand";

type AuthStore = {
  token: string | null;
  refreshToken: string | null;
  setAuth: (token: string, refresh: string) => void;
  logout: () => void;
  hydrate: () => void;
};

function readToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

function readRefresh() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("refresh_token");
}

export const useAuth = create<AuthStore>((set) => ({
  token: readToken(),
  refreshToken: readRefresh(),

  hydrate() {
    set({ token: readToken(), refreshToken: readRefresh() });
  },

  setAuth(token, refresh) {
    localStorage.setItem("token", token);
    localStorage.setItem("refresh_token", refresh);
    set({ token, refreshToken: refresh });
  },

  logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("refresh_token");
    set({ token: null, refreshToken: null });
  },
}));
