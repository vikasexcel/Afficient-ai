import { create } from "zustand";

export type Density = "comfortable" | "compact";

const DENSITY_KEY = "afficient-density";

function readDensity(): Density {
  if (typeof window === "undefined") return "comfortable";
  const stored = localStorage.getItem(DENSITY_KEY);
  return stored === "compact" ? "compact" : "comfortable";
}

function applyDensity(density: Density) {
  document.documentElement.setAttribute("data-density", density);
}

type AppearanceStore = {
  density: Density;
  setDensity: (density: Density) => void;
  hydrate: () => void;
};

export const useAppearance = create<AppearanceStore>((set) => ({
  density: readDensity(),

  setDensity(density) {
    localStorage.setItem(DENSITY_KEY, density);
    applyDensity(density);
    set({ density });
  },

  hydrate() {
    const density = readDensity();
    applyDensity(density);
    set({ density });
  },
}));
