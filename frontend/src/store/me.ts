import { create } from "zustand";

import { me as fetchMe, type CurrentUser } from "@/services/auth";

type MeStore = {
  data: CurrentUser | null;
  loading: boolean;
  load: () => Promise<void>;
  reset: () => void;
};

export const useMe = create<MeStore>((set, get) => ({
  data: null,
  loading: false,

  async load() {
    if (get().loading) return;
    set({ loading: true });
    try {
      const data = await fetchMe();
      set({ data, loading: false });
    } catch {
      set({ data: null, loading: false });
    }
  },

  reset() {
    set({ data: null, loading: false });
  },
}));

export function canManageMembers(role?: string | null) {
  return role === "owner" || role === "admin";
}

export function isOwner(role?: string | null) {
  return role === "owner";
}

/** Can create / run campaigns (not read-only members). */
export function canUseCampaigns(role?: string | null) {
  return role === "owner" || role === "admin" || role === "agent";
}

/** Workspace nav beyond dashboard + settings. */
export function canAccessWorkspace(role?: string | null) {
  return canUseCampaigns(role);
}

/** Insights section (analytics, transcripts). */
export function canAccessInsights(role?: string | null) {
  return role === "owner" || role === "admin";
}
