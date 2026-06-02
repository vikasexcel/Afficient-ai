import { create } from "zustand";

/**
 * Lightweight UI store for cross-cutting layout state that doesn't belong to
 * any single page (e.g. mobile sidebar drawer open/close).
 *
 * Keeping this in Zustand mirrors the pattern used by other client stores
 * (auth, me, appearance) so consumers stay consistent.
 */
type UIStore = {
  /** Whether the off-canvas sidebar drawer is open on mobile/tablet. */
  sidebarOpen: boolean;
  openSidebar: () => void;
  closeSidebar: () => void;
  toggleSidebar: () => void;
};

export const useUI = create<UIStore>((set) => ({
  sidebarOpen: false,
  openSidebar: () => set({ sidebarOpen: true }),
  closeSidebar: () => set({ sidebarOpen: false }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
}));
