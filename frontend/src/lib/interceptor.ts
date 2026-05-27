import { api, refresh } from "@/services/auth";

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshing: Promise<string> | null = null;

api.interceptors.response.use(
  (v) => v,
  async (err) => {
    const original = err.config;

    if (
      err.response?.status === 401 &&
      original &&
      !original._retry &&
      !original.url?.includes("/auth/refresh") &&
      !original.url?.includes("/auth/login")
    ) {
      original._retry = true;

      const stored = localStorage.getItem("refresh_token");
      if (!stored) {
        localStorage.clear();
        window.location.href = "/login";
        throw err;
      }

      try {
        refreshing =
          refreshing ??
          refresh(stored).then((r) => {
            localStorage.setItem("token", r.access_token);
            return r.access_token;
          });

        const token = await refreshing;
        refreshing = null;

        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      } catch {
        refreshing = null;
        localStorage.clear();
        window.location.href = "/login";
        throw err;
      }
    }

    throw err;
  }
);
