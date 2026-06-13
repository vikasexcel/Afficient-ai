import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpDown,
  ChevronDown,
  ChevronUp,
  Download,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";

import AppLayout from "@/components/layout/AppLayout";
import { useDashboardMetrics } from "@/hooks/useDashboardMetrics";
import { listCampaigns } from "@/services/campaign";
import type { CampaignOut, CampaignStatus } from "@/types/campaign";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(n: number): string {
  return n.toLocaleString();
}

function deltaLabel(d: number | null): { text: string; positive: boolean } | null {
  if (d === null) return null;
  return { text: `${d >= 0 ? "+" : ""}${d}%`, positive: d >= 0 };
}

function convRate(c: CampaignOut): number {
  const leads = c.lead_count ?? 0;
  const meetings = c.meetings_booked ?? 0;
  if (!leads) return 0;
  return Math.round((meetings / leads) * 100);
}

function exportCsv(rows: CampaignOut[]) {
  const headers = ["Campaign", "Status", "Leads", "Called", "Meetings", "Conv. Rate %"];
  const lines = rows.map((c) =>
    [
      `"${c.name.replace(/"/g, '""')}"`,
      c.status,
      c.lead_count ?? 0,
      c.executions_completed ?? 0,
      c.meetings_booked ?? 0,
      convRate(c),
    ].join(",")
  );
  const blob = new Blob([[headers.join(","), ...lines].join("\n")], {
    type: "text/csv",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `campaigns-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------------------------------------------------------------------------
// Status styles
// ---------------------------------------------------------------------------

const STATUS_STYLE: Record<string, { dot: string; text: string; bg: string; border: string }> = {
  active:    { dot: "#4ade80", text: "#4ade80", bg: "rgba(74,222,128,0.08)",  border: "rgba(74,222,128,0.2)" },
  paused:    { dot: "#fbbf24", text: "#fbbf24", bg: "rgba(251,191,36,0.08)",  border: "rgba(251,191,36,0.2)" },
  scheduled: { dot: "#38bdf8", text: "#38bdf8", bg: "rgba(56,189,248,0.08)",  border: "rgba(56,189,248,0.2)" },
  draft:     { dot: "#94a3b8", text: "#64748b", bg: "rgba(100,116,139,0.08)", border: "rgba(100,116,139,0.18)" },
  completed: { dot: "#94a3b8", text: "#64748b", bg: "rgba(100,116,139,0.08)", border: "rgba(100,116,139,0.18)" },
  archived:  { dot: "#cbd5e1", text: "#94a3b8", bg: "rgba(100,116,139,0.04)", border: "rgba(100,116,139,0.10)" },
};
const DEFAULT_STATUS_STYLE = STATUS_STYLE.draft;

// ---------------------------------------------------------------------------
// Sort config
// ---------------------------------------------------------------------------

type SortCol = "name" | "leads" | "called" | "meetings" | "rate";
type SortDir = "asc" | "desc";

// ---------------------------------------------------------------------------
// Today's date label
// ---------------------------------------------------------------------------

const today = new Date().toLocaleDateString("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const metrics = useDashboardMetrics(30_000);

  // Campaign table state
  const [campaigns, setCampaigns] = useState<CampaignOut[]>([]);
  const [campaignsLoading, setCampaignsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<CampaignStatus | "all">("all");
  const [sortCol, setSortCol] = useState<SortCol>("meetings");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  useEffect(() => {
    setCampaignsLoading(true);
    listCampaigns({ limit: 200 })
      .then((r) => setCampaigns(r.campaigns))
      .catch(console.error)
      .finally(() => setCampaignsLoading(false));
  }, []);

  function toggleSort(col: SortCol) {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return campaigns.filter(
      (c) =>
        (statusFilter === "all" || c.status === statusFilter) &&
        (!q || c.name.toLowerCase().includes(q))
    );
  }, [campaigns, search, statusFilter]);

  const sorted = useMemo(() => {
    const val = (c: CampaignOut): number => {
      if (sortCol === "leads") return c.lead_count ?? 0;
      if (sortCol === "called") return c.executions_completed ?? 0;
      if (sortCol === "meetings") return c.meetings_booked ?? 0;
      if (sortCol === "rate") return convRate(c);
      return 0;
    };
    return [...filtered].sort((a, b) => {
      if (sortCol === "name") {
        const cmp = a.name.localeCompare(b.name);
        return sortDir === "asc" ? cmp : -cmp;
      }
      return sortDir === "asc" ? val(a) - val(b) : val(b) - val(a);
    });
  }, [filtered, sortCol, sortDir]);

  // Funnel from hook
  const funnelSteps = useMemo(() => {
    if (!metrics.funnel) return null;
    const s = metrics.funnel.steps;
    return [
      s[0] ?? { label: "Leads uploaded",    count: 0, pct: 100 },
      s[2] ?? { label: "Contacted",          count: 0, pct: 0 },
      s[4] ?? { label: "Qualified",          count: 0, pct: 0 },
      s[5] ?? { label: "Meetings booked",    count: 0, pct: 0 },
    ];
  }, [metrics.funnel]);

  // ---------------------------------------------------------------------------
  // Metric card data
  // ---------------------------------------------------------------------------

  const metricCards = [
    {
      label: "Calls made",
      value: metrics.loading ? null : fmt(metrics.callsMade),
      delta: deltaLabel(metrics.callsMadeDelta),
      sub: "vs yesterday",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.64 12 19.79 19.79 0 0 1 1.56 3.44 2 2 0 0 1 3.54 1.25h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.81a16 16 0 0 0 5.55 5.55l.88-.88a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 21 16z" />
        </svg>
      ),
    },
    {
      label: "Connected",
      value: metrics.loading ? null : `${metrics.connectedRate}%`,
      delta: deltaLabel(metrics.connectedRateDelta),
      sub: "connection rate",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8h1a4 4 0 0 1 0 8h-1" />
          <path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z" />
          <line x1="6" y1="1" x2="6" y2="4" />
          <line x1="10" y1="1" x2="10" y2="4" />
          <line x1="14" y1="1" x2="14" y2="4" />
        </svg>
      ),
    },
    {
      label: "Meetings booked",
      value: metrics.loading ? null : fmt(metrics.meetingsBooked),
      delta: deltaLabel(metrics.meetingsBookedDelta),
      sub: "vs yesterday",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
          <path d="m9 16 2 2 4-4" />
        </svg>
      ),
    },
    {
      label: "Active campaigns",
      value: metrics.loading ? null : fmt(campaigns.filter((c) => c.status === "active").length),
      delta: null,
      sub: "currently running",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="5 3 19 12 5 21 5 3" />
        </svg>
      ),
    },
  ];

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <AppLayout>
      <div className="space-y-6 sm:space-y-8">

        {/* Page header */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div>
            <h1
              className="text-[20px] sm:text-[22px] font-semibold text-white"
              style={{ fontFamily: "'DM Serif Display', serif" }}
            >
              Dashboard
            </h1>
            <p className="text-[12px] sm:text-[13px] text-white/35 mt-0.5 flex items-center gap-1.5">
              {today}
              {metrics.loading && (
                <Loader2 size={11} className="animate-spin text-white/25" />
              )}
              {!metrics.loading && (
                <span className="text-white/20 text-[10px]">· auto-refreshes every 30s</span>
              )}
            </p>
          </div>
          <Link to="/campaigns" className="shrink-0">
            <button className="flex items-center gap-1.5 bg-violet-600 hover:bg-violet-500 transition-colors text-white text-[12px] font-semibold px-3.5 py-2 rounded-[8px] whitespace-nowrap">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              New campaign
            </button>
          </Link>
        </div>

        {/* Error banner */}
        {metrics.error && (
          <div className="rounded-[8px] border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-[12px] text-rose-300">
            {metrics.error}
          </div>
        )}

        {/* Metric cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {metricCards.map((m) => (
            <div
              key={m.label}
              className="bg-white/[0.03] border border-white/[0.07] rounded-[10px] p-4 hover:bg-white/[0.05] transition-colors"
            >
              <div className="flex items-center gap-1.5 text-white/40 mb-3">
                {m.icon}
                <span className="text-[11px] font-medium tracking-wide">{m.label}</span>
              </div>
              <div
                className="text-[26px] font-semibold text-white leading-none mb-2"
                style={{ fontFamily: "'DM Mono', monospace" }}
              >
                {m.value ?? (
                  <span className="inline-block w-16 h-6 bg-white/[0.06] rounded-[4px] animate-pulse" />
                )}
              </div>
              <div className="flex items-center gap-1.5">
                {m.delta ? (
                  <span
                    className="text-[11px] font-medium px-1.5 py-0.5 rounded-[4px]"
                    style={{
                      color: m.delta.positive ? "#4ade80" : "#f87171",
                      background: m.delta.positive ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)",
                    }}
                  >
                    {m.delta.text}
                  </span>
                ) : null}
                <span className="text-[11px] text-white/25">{m.sub}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Funnel row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 bg-white/[0.02] border border-white/[0.06] rounded-[10px] overflow-hidden">
          {(funnelSteps ?? [
            { label: "Leads uploaded",  pct: 100, count: 0 },
            { label: "Contacted",       pct: 0,   count: 0 },
            { label: "Qualified",       pct: 0,   count: 0 },
            { label: "Meetings booked", pct: 0,   count: 0 },
          ]).map((s, i) => {
            const mobileBorderB = i < 2 ? "border-b lg:border-b-0" : "";
            const mobileBorderR = i % 2 === 0 ? "border-r" : "lg:border-r";
            const desktopLast = i === 3 ? "lg:border-r-0" : "";
            const barColors = ["#6d28d9", "#7c3aed", "#8b5cf6", "#a78bfa"];
            return (
              <div
                key={s.label}
                className={`px-4 sm:px-5 py-4 border-white/[0.06] ${mobileBorderB} ${mobileBorderR} ${desktopLast}`}
              >
                <div className="text-[11px] text-white/30 mb-2">{s.label}</div>
                <div
                  className="text-[20px] font-semibold text-white mb-2"
                  style={{ fontFamily: "'DM Mono', monospace" }}
                >
                  {metrics.loading && !funnelSteps ? (
                    <span className="inline-block w-12 h-5 bg-white/[0.06] rounded animate-pulse" />
                  ) : (
                    s.count.toLocaleString()
                  )}
                </div>
                <div className="h-1 bg-white/[0.06] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${s.pct}%`, background: barColors[i] }}
                  />
                </div>
                <div className="text-[10px] text-white/20 mt-1.5">{s.pct}% of total</div>
              </div>
            );
          })}
        </div>

        {/* Campaign table */}
        <div>
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-3.5">
            <h2 className="text-[14px] font-semibold text-white/80 shrink-0">Campaigns</h2>

            <div className="flex-1 flex flex-col sm:flex-row items-stretch sm:items-center gap-2 sm:ml-3">
              {/* Search */}
              <div className="relative flex-1 max-w-xs">
                <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/35 pointer-events-none" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search campaigns…"
                  className="w-full pl-7 pr-3 h-8 bg-white/[0.03] border border-white/[0.08] rounded-[7px] text-[12px] text-white placeholder-white/25 outline-none focus:border-violet-500/40"
                />
              </div>

              {/* Status filter */}
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as CampaignStatus | "all")}
                className="h-8 px-2 bg-white/[0.03] border border-white/[0.08] rounded-[7px] text-[12px] text-white/70 outline-none focus:border-violet-500/40"
              >
                <option value="all">All statuses</option>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="scheduled">Scheduled</option>
                <option value="completed">Completed</option>
                <option value="draft">Draft</option>
              </select>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => exportCsv(sorted)}
                className="flex items-center gap-1.5 h-8 px-3 bg-white/[0.03] border border-white/[0.08] rounded-[7px] text-[12px] text-white/60 hover:text-white hover:bg-white/[0.06] transition-colors"
              >
                <Download size={12} />
                CSV
              </button>
              <Link
                to="/campaigns"
                className="text-[12px] text-violet-400 hover:text-violet-300 transition-colors"
              >
                View all →
              </Link>
            </div>
          </div>

          <div className="bg-white/[0.02] border border-white/[0.07] rounded-[10px] overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-[13px] border-collapse">
                <thead>
                  <tr className="border-b border-white/[0.06]">
                    {(
                      [
                        { key: "name",     label: "Campaign" },
                        { key: null,       label: "Status" },
                        { key: "leads",    label: "Leads" },
                        { key: "called",   label: "Called" },
                        { key: "meetings", label: "Meetings" },
                        { key: "rate",     label: "Conv. rate" },
                      ] as { key: SortCol | null; label: string }[]
                    ).map(({ key, label }) => (
                      <th
                        key={label}
                        onClick={() => key && toggleSort(key)}
                        className={`text-left px-4 py-3 text-[11px] font-medium text-white/25 tracking-wide whitespace-nowrap select-none ${key ? "cursor-pointer hover:text-white/50" : ""}`}
                      >
                        <span className="inline-flex items-center gap-1">
                          {label}
                          {key && sortCol === key ? (
                            sortDir === "asc" ? <ChevronUp size={10} /> : <ChevronDown size={10} />
                          ) : key ? (
                            <ArrowUpDown size={10} className="opacity-30" />
                          ) : null}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {campaignsLoading ? (
                    Array.from({ length: 3 }).map((_, i) => (
                      <tr key={i} className="border-b border-white/[0.04]">
                        {Array.from({ length: 6 }).map((_, j) => (
                          <td key={j} className="px-4 py-3.5">
                            <div className="h-3 bg-white/[0.06] rounded animate-pulse" style={{ width: j === 0 ? "140px" : "48px" }} />
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : sorted.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-[12px] text-white/35">
                        {search || statusFilter !== "all" ? "No campaigns match your filters." : "No campaigns yet."}
                      </td>
                    </tr>
                  ) : (
                    sorted.map((c) => {
                      const s = STATUS_STYLE[c.status] ?? DEFAULT_STATUS_STYLE;
                      const leads = c.lead_count ?? 0;
                      const called = c.executions_completed ?? 0;
                      const meetings = c.meetings_booked ?? 0;
                      const pct = leads ? Math.round((called / leads) * 100) : 0;
                      const rate = convRate(c);
                      return (
                        <tr
                          key={c.id}
                          className="border-b border-white/[0.04] last:border-b-0 hover:bg-white/[0.02] transition-colors cursor-pointer group"
                        >
                          <td className="px-4 py-3.5 font-medium text-white/90 group-hover:text-white transition-colors">
                            {c.name}
                          </td>
                          <td className="px-4 py-3.5">
                            <span
                              className="inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full"
                              style={{ color: s.text, background: s.bg, border: `0.5px solid ${s.border}` }}
                            >
                              <span className="w-[5px] h-[5px] rounded-full flex-shrink-0" style={{ background: s.dot }} />
                              {c.status.charAt(0).toUpperCase() + c.status.slice(1)}
                            </span>
                          </td>
                          <td className="px-4 py-3.5 text-white/50" style={{ fontFamily: "'DM Mono', monospace" }}>
                            {fmt(leads)}
                          </td>
                          <td className="px-4 py-3.5">
                            <div className="flex items-center gap-2">
                              <div className="w-16 h-1 bg-white/[0.08] rounded-full overflow-hidden">
                                <div className="h-full rounded-full bg-violet-500" style={{ width: `${pct}%` }} />
                              </div>
                              <span className="text-white/50" style={{ fontFamily: "'DM Mono', monospace" }}>
                                {fmt(called)}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-3.5 text-white/50" style={{ fontFamily: "'DM Mono', monospace" }}>
                            {fmt(meetings)}
                          </td>
                          <td
                            className="px-4 py-3.5 font-medium"
                            style={{
                              fontFamily: "'DM Mono', monospace",
                              color: rate >= 10 ? "#4ade80" : "rgba(255,255,255,0.5)",
                            }}
                          >
                            {rate}%
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

      </div>
    </AppLayout>
  );
}
