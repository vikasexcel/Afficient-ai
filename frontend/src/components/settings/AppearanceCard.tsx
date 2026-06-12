import { useEffect, useState } from "react";
import { Check, Monitor } from "lucide-react";
import { useTheme } from "next-themes";

import { useAppearance, type Density } from "@/store/appearance";
import { cn } from "@/lib/utils";

const THEMES = [
  { id: "dark" as const, label: "Dark", bg: "#0a0a0d" },
  { id: "light" as const, label: "Light", bg: "#f4f4f5" },
  { id: "system" as const, label: "System", bg: "#0a0a0d" },
];

const DENSITIES: { id: Density; label: string }[] = [
  { id: "comfortable", label: "Comfortable" },
  { id: "compact", label: "Compact" },
];

export default function AppearanceCard() {
  const { theme, setTheme } = useTheme();
  const density = useAppearance((s) => s.density);
  const setDensity = useAppearance((s) => s.setDensity);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const activeTheme = mounted ? (theme ?? "dark") : "dark";

  return (
    <div className="space-y-6 max-w-lg">
      <div>
        <h2 className="text-[15px] font-medium text-foreground">Appearance</h2>
        <p className="text-[12px] text-muted-foreground mt-0.5">
          Customize how Tellaigent looks in your browser.
        </p>
      </div>

      <section className="space-y-3">
        <h3 className="text-[12px] font-medium text-muted-foreground">Theme</h3>

        <div className="grid grid-cols-3 gap-3">
          {THEMES.map((t) => {
            const active = activeTheme === t.id;
            return (
              <button
                key={t.id}
                type="button"
                aria-pressed={active}
                onClick={() => setTheme(t.id)}
                className={cn(
                  "group relative flex flex-col items-stretch gap-2 rounded-[10px] border p-2 text-left transition-colors",
                  active
                    ? "border-violet-500/50 bg-violet-500/[0.05]"
                    : "border-border hover:border-foreground/20 bg-muted/30"
                )}
              >
                <div
                  className="h-14 rounded-[6px] border border-border flex items-center justify-center"
                  style={{ background: t.bg }}
                >
                  {t.id === "system" && (
                    <Monitor size={14} className="text-white/30" />
                  )}
                </div>
                <div className="flex items-center justify-between px-0.5">
                  <span className="text-[12px] text-foreground/80">{t.label}</span>
                  {active && <Check size={12} className="text-violet-400" />}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <section className="space-y-3 pt-5 border-t border-border">
        <h3 className="text-[12px] font-medium text-muted-foreground">Density</h3>
        <div className="grid grid-cols-2 gap-3">
          {DENSITIES.map((d) => {
            const active = density === d.id;
            return (
              <button
                key={d.id}
                type="button"
                aria-pressed={active}
                onClick={() => setDensity(d.id)}
                className={cn(
                  "flex items-center justify-between rounded-[10px] border px-3 py-2.5 text-left transition-colors",
                  active
                    ? "border-violet-500/50 bg-violet-500/[0.05]"
                    : "border-border hover:border-foreground/20 bg-muted/30"
                )}
              >
                <span className="text-[13px] text-foreground/80">{d.label}</span>
                {active && <Check size={13} className="text-violet-400" />}
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
