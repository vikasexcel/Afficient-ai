import { useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  PhoneCall,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";

import AppLayout from "@/components/layout/AppLayout";
import { cn } from "@/lib/utils";

type Range = "7d" | "30d" | "90d";

const RANGES: { id: Range; label: string }[] = [
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
  { id: "90d", label: "Last 90 days" },
];

const KPIS = [
  {
    id: "calls",
    label: "Total calls",
    value: 1284,
    delta: 12.4,
    icon: PhoneCall,
    accent: "violet",
  },
  {
    id: "leads",
    label: "Qualified leads",
    value: 312,
    delta: 7.2,
    icon: Target,
    accent: "emerald",
  },
  {
    id: "talktime",
    label: "Avg. talk time",
    value: "4m 12s",
    delta: -3.1,
    icon: TrendingUp,
    accent: "amber",
  },
  {
    id: "contacts",
    label: "New contacts",
    value: 528,
    delta: 18.6,
    icon: Users,
    accent: "sky",
  },
] as const;

const ACCENTS: Record<
  (typeof KPIS)[number]["accent"],
  { icon: string; bar: string }
> = {
  violet: {
    icon: "text-violet-300 bg-violet-500/10 border-violet-500/20",
    bar: "bg-violet-500/70",
  },
  emerald: {
    icon: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
    bar: "bg-emerald-500/70",
  },
  amber: {
    icon: "text-amber-300 bg-amber-500/10 border-amber-500/20",
    bar: "bg-amber-500/70",
  },
  sky: {
    icon: "text-sky-300 bg-sky-500/10 border-sky-500/20",
    bar: "bg-sky-500/70",
  },
};

const CALL_VOLUME = [
  { day: "Mon", calls: 142, qualified: 28 },
  { day: "Tue", calls: 168, qualified: 41 },
  { day: "Wed", calls: 195, qualified: 47 },
  { day: "Thu", calls: 211, qualified: 52 },
  { day: "Fri", calls: 187, qualified: 44 },
  { day: "Sat", calls: 92, qualified: 18 },
  { day: "Sun", calls: 74, qualified: 12 },
];

const FUNNEL = [
  { label: "Dialed", count: 1284, color: "bg-sky-500/60" },
  { label: "Connected", count: 882, color: "bg-violet-500/60" },
  { label: "Qualified", count: 312, color: "bg-amber-500/60" },
  { label: "Converted", count: 96, color: "bg-emerald-500/60" },
];

const TOP_AGENTS = [
  { name: "Aditi R.", calls: 312, qualified: 88, rate: 28 },
  { name: "Karan S.", calls: 268, qualified: 71, rate: 26 },
  { name: "Riya M.", calls: 254, qualified: 62, rate: 24 },
  { name: "Vikram L.", calls: 198, qualified: 41, rate: 21 },
  { name: "Naina K.", calls: 174, qualified: 32, rate: 18 },
];

const TOP_CAMPAIGNS = [
  { name: "Q2 SaaS · Outbound", calls: 412, conversion: 9.4 },
  { name: "LATAM Expansion", calls: 286, conversion: 7.8 },
  { name: "Renewals Win-Back", calls: 218, conversion: 11.2 },
  { name: "Inbound Demo", calls: 184, conversion: 14.1 },
];

export default function Analytics() {
  const [range, setRange] = useState<Range>("7d");

  const maxCalls = useMemo(
    () => Math.max(...CALL_VOLUME.map((d) => d.calls)),
    []
  );
  const maxFunnel = FUNNEL[0].count;

  return (
    <AppLayout>
      <div className="space-y-6 max-w-6xl">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-medium text-white">
              Analytics
            </h1>
            <p className="text-[13px] text-white/40 mt-1">
              Performance overview across calls, leads, and campaigns. Data shown
              is sample.
            </p>
          </div>

          <div className="inline-flex items-center rounded-[8px] border border-white/[0.08] bg-white/[0.02] p-0.5 overflow-x-auto max-w-full">
            <CalendarDays size={13} className="text-white/40 ml-2 mr-1 shrink-0" />
            {RANGES.map((r) => {
              const active = range === r.id;
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setRange(r.id)}
                  className={cn(
                    "px-2.5 h-7 rounded-[6px] text-[12px] transition-colors whitespace-nowrap shrink-0",
                    active
                      ? "bg-white/[0.06] text-white"
                      : "text-white/55 hover:text-white/85"
                  )}
                >
                  {r.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {KPIS.map((kpi) => {
            const Icon = kpi.icon;
            const up = kpi.delta >= 0;
            return (
              <div
                key={kpi.id}
                className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] p-4"
              >
                <div className="flex items-center justify-between">
                  <div
                    className={cn(
                      "h-8 w-8 rounded-[8px] border flex items-center justify-center",
                      ACCENTS[kpi.accent].icon
                    )}
                  >
                    <Icon size={13} />
                  </div>
                  <span
                    className={cn(
                      "inline-flex items-center gap-0.5 text-[11px] font-medium",
                      up ? "text-emerald-300" : "text-red-300"
                    )}
                  >
                    {up ? (
                      <ArrowUpRight size={12} />
                    ) : (
                      <ArrowDownRight size={12} />
                    )}
                    {Math.abs(kpi.delta)}%
                  </span>
                </div>
                <div className="mt-3">
                  <div className="text-[11px] text-white/45 uppercase tracking-wider">
                    {kpi.label}
                  </div>
                  <div className="text-[20px] font-semibold text-white mt-0.5">
                    {kpi.value}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-[14px] font-medium text-white">
                  Call volume
                </h2>
                <p className="text-[12px] text-white/40">
                  Daily calls and qualified leads
                </p>
              </div>
              <div className="flex items-center gap-3 text-[11px] text-white/55">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-sm bg-violet-500/70" />
                  Calls
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-sm bg-emerald-500/70" />
                  Qualified
                </span>
              </div>
            </div>

            <div className="mt-5 flex items-end gap-3 h-44">
              {CALL_VOLUME.map((d) => (
                <div
                  key={d.day}
                  className="flex-1 flex flex-col items-center gap-1"
                >
                  <div className="w-full flex items-end justify-center gap-1 h-full">
                    <div
                      className="w-3 rounded-t-[3px] bg-violet-500/70"
                      style={{ height: `${(d.calls / maxCalls) * 100}%` }}
                      title={`${d.calls} calls`}
                    />
                    <div
                      className="w-3 rounded-t-[3px] bg-emerald-500/70"
                      style={{
                        height: `${(d.qualified / maxCalls) * 100}%`,
                      }}
                      title={`${d.qualified} qualified`}
                    />
                  </div>
                  <span className="text-[10px] text-white/45">{d.day}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
            <h2 className="text-[14px] font-medium text-white">
              Conversion funnel
            </h2>
            <p className="text-[12px] text-white/40">
              From dial to converted
            </p>

            <div className="mt-5 space-y-3">
              {FUNNEL.map((step) => {
                const pct = Math.round((step.count / maxFunnel) * 100);
                return (
                  <div key={step.label}>
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-white/75">{step.label}</span>
                      <span className="text-white/55">
                        {step.count.toLocaleString()}{" "}
                        <span className="text-white/35">({pct}%)</span>
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 w-full rounded-full bg-white/[0.05] overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", step.color)}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
            <h2 className="text-[14px] font-medium text-white">Top agents</h2>
            <p className="text-[12px] text-white/40">
              By qualified-lead rate
            </p>

            <div className="mt-4 space-y-3">
              {TOP_AGENTS.map((a) => (
                <div
                  key={a.name}
                  className="flex items-center justify-between gap-3"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-white/[0.06] border border-white/[0.08] text-[10px] font-medium text-white/80">
                      {a.name
                        .split(" ")
                        .map((p) => p[0])
                        .join("")}
                    </span>
                    <div className="min-w-0">
                      <div className="text-[13px] text-white truncate">
                        {a.name}
                      </div>
                      <div className="text-[11px] text-white/40">
                        {a.calls} calls · {a.qualified} qualified
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="hidden sm:block w-16 md:w-20 h-1.5 rounded-full bg-white/[0.05] overflow-hidden">
                      <div
                        className="h-full bg-violet-500/70 rounded-full"
                        style={{ width: `${a.rate * 3}%` }}
                      />
                    </div>
                    <span className="text-[12px] text-white/75 w-8 text-right">
                      {a.rate}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
            <h2 className="text-[14px] font-medium text-white">
              Top campaigns
            </h2>
            <p className="text-[12px] text-white/40">By conversion rate</p>

            <div className="mt-4 space-y-3">
              {TOP_CAMPAIGNS.map((c) => (
                <div
                  key={c.name}
                  className="flex items-center justify-between gap-3"
                >
                  <div className="min-w-0">
                    <div className="text-[13px] text-white truncate">
                      {c.name}
                    </div>
                    <div className="text-[11px] text-white/40">
                      {c.calls} calls
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="hidden sm:block w-16 md:w-20 h-1.5 rounded-full bg-white/[0.05] overflow-hidden">
                      <div
                        className="h-full bg-emerald-500/70 rounded-full"
                        style={{ width: `${c.conversion * 6}%` }}
                      />
                    </div>
                    <span className="text-[12px] text-white/75 w-12 text-right">
                      {c.conversion}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
