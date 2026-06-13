import { useCallback, useEffect, useState } from "react";
import {
  CalendarDays,
  Download,
  FileJson,
  FileSpreadsheet,
  FileText,
  Loader2,
  RefreshCw,
} from "lucide-react";

import AppLayout from "@/components/layout/AppLayout";
import AnalyticsDashboard from "@/components/analytics/AnalyticsDashboard";
import CampaignAnalytics from "@/components/analytics/CampaignAnalytics";
import EmailAnalytics from "@/components/analytics/EmailAnalytics";
import CallAnalytics from "@/components/analytics/CallAnalytics";
import LinkedInAnalytics from "@/components/analytics/LinkedInAnalytics";
import FunnelAnalytics from "@/components/analytics/FunnelAnalytics";
import WorkflowAnalytics from "@/components/analytics/WorkflowAnalytics";
import MeetingsChart from "@/components/analytics/MeetingsChart";
import { cn } from "@/lib/utils";
import {
  analyticsApi,
  type CallAnalyticsData,
  type EmailAnalyticsData,
  type FunnelData,
  type LinkedInAnalyticsData,
  type MeetingsTrendData,
  type OverviewData,
  type TrendsData,
  type WorkflowAnalyticsData,
} from "@/services/analytics";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Range = 7 | 30 | 90;
type TabId = "overview" | "campaigns" | "email" | "calls" | "linkedin" | "funnel" | "workflow";

const RANGES: { id: Range; label: string }[] = [
  { id: 7, label: "7d" },
  { id: 30, label: "30d" },
  { id: 90, label: "90d" },
];

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "campaigns", label: "Campaigns" },
  { id: "email", label: "Email" },
  { id: "calls", label: "Calls" },
  { id: "linkedin", label: "LinkedIn" },
  { id: "funnel", label: "Funnel" },
  { id: "workflow", label: "Workflow" },
];

// ---------------------------------------------------------------------------
// Export helpers
// ---------------------------------------------------------------------------

function flattenForCsv(data: Record<string, unknown>, prefix = ""): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(data)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(out, flattenForCsv(v as Record<string, unknown>, key));
    } else if (Array.isArray(v)) {
      out[key] = v.length;
    } else {
      out[key] = v;
    }
  }
  return out;
}

function downloadFile(content: string, filename: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportCsv(payload: Record<string, unknown>, filename: string) {
  const flat = flattenForCsv(payload);
  const headers = Object.keys(flat).join(",");
  const values = Object.values(flat)
    .map((v) => (typeof v === "string" && v.includes(",") ? `"${v}"` : String(v ?? "")))
    .join(",");
  downloadFile(`${headers}\n${values}`, filename, "text/csv");
}

function exportJson(payload: unknown, filename: string) {
  downloadFile(JSON.stringify(payload, null, 2), filename, "application/json");
}

function exportPdf() {
  window.print();
}

// ---------------------------------------------------------------------------
// Default empty state
// ---------------------------------------------------------------------------

const EMPTY_OVERVIEW: OverviewData = {
  campaigns: { total: 0, active: 0, completed: 0, draft: 0, paused: 0, scheduled: 0, archived: 0 },
  executions: { total: 0, completed: 0, failed: 0, running: 0, queued: 0, completion_rate: 0, failure_rate: 0 },
  leads: { total: 0, new: 0, contacted: 0, qualified: 0, converted: 0, lost: 0 },
  total_leads_processed: 0,
};

const EMPTY_EMAIL: EmailAnalyticsData = { sent: 0, failed: 0, success_rate: 0, daily_trend: [] };
const EMPTY_CALLS: CallAnalyticsData = { attempted: 0, completed: 0, failed: 0, voicemail: 0, daily_trend: [] };
const EMPTY_LINKEDIN: LinkedInAnalyticsData = { connections_sent: 0, messages_sent: 0, failed: 0, daily_trend: [] };
const EMPTY_FUNNEL: FunnelData = {
  steps: [
    { label: "Lead Uploaded", count: 0, pct: 100 },
    { label: "Workflow Started", count: 0, pct: 0 },
    { label: "Email Sent", count: 0, pct: 0 },
    { label: "Call Connected", count: 0, pct: 0 },
    { label: "Qualified", count: 0, pct: 0 },
    { label: "Meeting Booked", count: 0, pct: 0 },
  ],
};
const EMPTY_WORKFLOW: WorkflowAnalyticsData = {
  most_used_workflows: [],
  node_type_distribution: [],
  total_workflows: 0,
  total_executions_in_period: 0,
};
const EMPTY_TRENDS: TrendsData = { executions_per_day: [], campaign_growth: [] };
const EMPTY_MEETINGS: MeetingsTrendData = { total: 0, daily: [] };

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Analytics() {
  const [tab, setTab] = useState<TabId>("overview");
  const [range, setRange] = useState<Range>(30);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [overview, setOverview] = useState<OverviewData>(EMPTY_OVERVIEW);
  const [email, setEmail] = useState<EmailAnalyticsData>(EMPTY_EMAIL);
  const [calls, setCalls] = useState<CallAnalyticsData>(EMPTY_CALLS);
  const [linkedin, setLinkedin] = useState<LinkedInAnalyticsData>(EMPTY_LINKEDIN);
  const [funnel, setFunnel] = useState<FunnelData>(EMPTY_FUNNEL);
  const [workflow, setWorkflow] = useState<WorkflowAnalyticsData>(EMPTY_WORKFLOW);
  const [trends, setTrends] = useState<TrendsData>(EMPTY_TRENDS);
  const [meetings, setMeetings] = useState<MeetingsTrendData>(EMPTY_MEETINGS);

  const load = useCallback(async (days: Range) => {
    setLoading(true);
    setError(null);
    try {
      const [ov, em, ca, li, fu, wf, tr, mt] = await Promise.all([
        analyticsApi.overview(days),
        analyticsApi.email(days),
        analyticsApi.calls(days),
        analyticsApi.linkedin(days),
        analyticsApi.funnel(days),
        analyticsApi.workflow(days),
        analyticsApi.trends(days),
        analyticsApi.meetings(days),
      ]);
      setOverview(ov);
      setEmail(em);
      setCalls(ca);
      setLinkedin(li);
      setFunnel(fu);
      setWorkflow(wf);
      setTrends(tr);
      setMeetings(mt);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(range);
  }, [range, load]);

  // Export current tab data
  const handleExport = (format: "csv" | "json" | "pdf") => {
    const ts = new Date().toISOString().slice(0, 10);
    const base = `analytics-${tab}-${ts}`;

    const payloads: Record<TabId, unknown> = {
      overview,
      campaigns: overview,
      email,
      calls,
      linkedin,
      funnel,
      workflow,
    };
    const payload = payloads[tab] as Record<string, unknown>;

    if (format === "csv") exportCsv(payload, `${base}.csv`);
    else if (format === "json") exportJson(payload, `${base}.json`);
    else exportPdf();
  };

  return (
    <AppLayout>
      {/* Print styles */}
      <style>{`@media print { .no-print { display: none !important; } }`}</style>

      <div className="space-y-5 max-w-6xl">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-medium text-white">Analytics</h1>
            <p className="text-[13px] text-white/40 mt-0.5">
              Business intelligence across campaigns, channels, and lead conversion.
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap no-print">
            {/* Date range */}
            <div className="inline-flex items-center rounded-[8px] border border-white/[0.08] bg-white/[0.02] p-0.5">
              <CalendarDays size={12} className="text-white/40 ml-2 mr-1 shrink-0" />
              {RANGES.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setRange(r.id)}
                  className={cn(
                    "px-2.5 h-7 rounded-[6px] text-[12px] transition-colors whitespace-nowrap",
                    range === r.id
                      ? "bg-white/[0.06] text-white"
                      : "text-white/55 hover:text-white/85",
                  )}
                >
                  {r.label}
                </button>
              ))}
            </div>

            {/* Refresh */}
            <button
              type="button"
              onClick={() => load(range)}
              disabled={loading}
              className="h-8 w-8 rounded-[8px] border border-white/[0.08] bg-white/[0.02] flex items-center justify-center text-white/50 hover:text-white/80 transition-colors disabled:opacity-40"
              title="Refresh"
            >
              {loading ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <RefreshCw size={13} />
              )}
            </button>

            {/* Export dropdown */}
            <div className="relative group">
              <button
                type="button"
                className="h-8 px-3 rounded-[8px] border border-white/[0.08] bg-white/[0.02] flex items-center gap-1.5 text-[12px] text-white/60 hover:text-white/85 transition-colors"
              >
                <Download size={12} />
                Export
              </button>
              <div className="absolute right-0 top-full mt-1 w-44 rounded-[10px] border border-white/[0.08] bg-[#0e0e14] shadow-2xl hidden group-hover:block z-20">
                {[
                  { id: "csv", label: "CSV Export", icon: FileSpreadsheet },
                  { id: "json", label: "JSON Export", icon: FileJson },
                  { id: "pdf", label: "PDF Summary", icon: FileText },
                ].map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => handleExport(id as "csv" | "json" | "pdf")}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[12px] text-white/65 hover:text-white hover:bg-white/[0.04] transition-colors first:rounded-t-[10px] last:rounded-b-[10px]"
                  >
                    <Icon size={12} className="shrink-0" />
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="rounded-[8px] border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-[13px] text-rose-300">
            {error}
          </div>
        )}

        {/* Tabs */}
        <div className="border-b border-white/[0.06] no-print">
          <div className="flex items-center gap-0 overflow-x-auto">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={cn(
                  "px-4 py-2.5 text-[13px] whitespace-nowrap border-b-2 transition-colors shrink-0",
                  tab === t.id
                    ? "border-violet-500 text-white"
                    : "border-transparent text-white/50 hover:text-white/80",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Loading overlay */}
        {loading && (
          <div className="flex items-center justify-center py-16">
            <div className="flex items-center gap-2 text-white/50 text-[13px]">
              <Loader2 size={16} className="animate-spin" />
              Loading analytics…
            </div>
          </div>
        )}

        {/* Tab content */}
        {!loading && (
          <div>
            {tab === "overview" && (
              <div className="space-y-6">
                <AnalyticsDashboard overview={overview} trends={trends} />
                <MeetingsChart data={meetings} />
              </div>
            )}
            {tab === "campaigns" && (
              <CampaignAnalytics overview={overview} />
            )}
            {tab === "email" && (
              <EmailAnalytics data={email} />
            )}
            {tab === "calls" && (
              <CallAnalytics data={calls} />
            )}
            {tab === "linkedin" && (
              <LinkedInAnalytics data={linkedin} />
            )}
            {tab === "funnel" && (
              <FunnelAnalytics data={funnel} />
            )}
            {tab === "workflow" && (
              <WorkflowAnalytics data={workflow} />
            )}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
