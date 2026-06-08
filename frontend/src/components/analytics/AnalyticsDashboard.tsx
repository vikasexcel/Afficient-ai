import {
  Activity,
  CheckCircle2,
  LayoutList,
  PlayCircle,
  TrendingUp,
  Users,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { OverviewData, TrendsData } from "@/services/analytics";

interface Props {
  overview: OverviewData;
  trends: TrendsData;
}

const STAT_CARDS = (o: OverviewData) => [
  {
    label: "Total Campaigns",
    value: o.campaigns.total,
    icon: LayoutList,
    accent: "violet",
    sub: `${o.campaigns.active} active`,
  },
  {
    label: "Active Campaigns",
    value: o.campaigns.active,
    icon: PlayCircle,
    accent: "emerald",
    sub: `${o.campaigns.scheduled} scheduled`,
  },
  {
    label: "Completed Campaigns",
    value: o.campaigns.completed,
    icon: CheckCircle2,
    accent: "sky",
    sub: `${o.campaigns.archived} archived`,
  },
  {
    label: "Total Leads",
    value: o.leads.total,
    icon: Users,
    accent: "amber",
    sub: `${o.leads.qualified} qualified`,
  },
  {
    label: "Total Executions",
    value: o.executions.total,
    icon: Activity,
    accent: "indigo",
    sub: `${o.executions.running} running`,
  },
  {
    label: "Completion Rate",
    value: `${o.executions.completion_rate}%`,
    icon: TrendingUp,
    accent: "teal",
    sub: `${o.executions.completed} completed`,
  },
  {
    label: "Failure Rate",
    value: `${o.executions.failure_rate}%`,
    icon: XCircle,
    accent: "rose",
    sub: `${o.executions.failed} failed`,
  },
  {
    label: "Leads Processed",
    value: o.total_leads_processed,
    icon: CheckCircle2,
    accent: "purple",
    sub: `${o.leads.converted} converted`,
  },
] as const;

const ACCENT_MAP: Record<string, { icon: string; bar: string }> = {
  violet: { icon: "text-violet-300 bg-violet-500/10 border-violet-500/20", bar: "bg-violet-500/70" },
  emerald: { icon: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20", bar: "bg-emerald-500/70" },
  sky: { icon: "text-sky-300 bg-sky-500/10 border-sky-500/20", bar: "bg-sky-500/70" },
  amber: { icon: "text-amber-300 bg-amber-500/10 border-amber-500/20", bar: "bg-amber-500/70" },
  indigo: { icon: "text-indigo-300 bg-indigo-500/10 border-indigo-500/20", bar: "bg-indigo-500/70" },
  teal: { icon: "text-teal-300 bg-teal-500/10 border-teal-500/20", bar: "bg-teal-500/70" },
  rose: { icon: "text-rose-300 bg-rose-500/10 border-rose-500/20", bar: "bg-rose-500/70" },
  purple: { icon: "text-purple-300 bg-purple-500/10 border-purple-500/20", bar: "bg-purple-500/70" },
};

export default function AnalyticsDashboard({ overview, trends }: Props) {
  const cards = STAT_CARDS(overview);
  const executions = trends.executions_per_day;
  const campaigns = trends.campaign_growth;
  const maxExec = Math.max(...executions.map((d) => d.total), 1);
  const maxCamp = Math.max(...campaigns.map((d) => d.count), 1);

  return (
    <div className="space-y-6">
      {/* KPI grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {cards.map((card) => {
          const Icon = card.icon;
          const colors = ACCENT_MAP[card.accent];
          return (
            <div
              key={card.label}
              className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] p-4"
            >
              <div
                className={cn(
                  "h-8 w-8 rounded-[8px] border flex items-center justify-center",
                  colors.icon,
                )}
              >
                <Icon size={13} />
              </div>
              <div className="mt-3">
                <div className="text-[11px] text-white/45 uppercase tracking-wider leading-tight">
                  {card.label}
                </div>
                <div className="text-[22px] font-semibold text-white mt-0.5">
                  {card.value}
                </div>
                <div className="text-[11px] text-white/35 mt-0.5">{card.sub}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Executions per day */}
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <h2 className="text-[14px] font-medium text-white">Executions Per Day</h2>
          <p className="text-[12px] text-white/40">Completed vs failed within window</p>
          <div className="mt-5 flex items-end gap-1.5 h-36">
            {executions.length === 0 ? (
              <p className="text-[12px] text-white/30 w-full text-center self-center">No data</p>
            ) : (
              executions.map((d) => (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                  <div className="w-full flex items-end justify-center gap-0.5 h-full">
                    <div
                      className="flex-1 rounded-t-[2px] bg-violet-500/60"
                      style={{ height: `${(d.total / maxExec) * 100}%` }}
                      title={`${d.date}: ${d.total} total`}
                    />
                    <div
                      className="flex-1 rounded-t-[2px] bg-emerald-500/60"
                      style={{ height: `${(d.completed / maxExec) * 100}%` }}
                      title={`${d.completed} completed`}
                    />
                    <div
                      className="flex-1 rounded-t-[2px] bg-rose-500/60"
                      style={{ height: `${(d.failed / maxExec) * 100}%` }}
                      title={`${d.failed} failed`}
                    />
                  </div>
                  <span className="text-[9px] text-white/30 truncate max-w-full">
                    {d.date.slice(5)}
                  </span>
                </div>
              ))
            )}
          </div>
          <div className="mt-2 flex items-center gap-4 text-[11px] text-white/50">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-violet-500/60" /> Total
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-emerald-500/60" /> Completed
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-rose-500/60" /> Failed
            </span>
          </div>
        </div>

        {/* Campaign growth */}
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <h2 className="text-[14px] font-medium text-white">Campaign Growth</h2>
          <p className="text-[12px] text-white/40">New campaigns created per day</p>
          <div className="mt-5 flex items-end gap-1.5 h-36">
            {campaigns.length === 0 ? (
              <p className="text-[12px] text-white/30 w-full text-center self-center">No data</p>
            ) : (
              campaigns.map((d) => (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                  <div
                    className="w-full rounded-t-[2px] bg-sky-500/60"
                    style={{ height: `${(d.count / maxCamp) * 100}%` }}
                    title={`${d.date}: ${d.count}`}
                  />
                  <span className="text-[9px] text-white/30 truncate max-w-full">
                    {d.date.slice(5)}
                  </span>
                </div>
              ))
            )}
          </div>

          {/* Lead status breakdown */}
          <div className="mt-4 pt-4 border-t border-white/[0.04] space-y-2">
            {(
              [
                ["New", overview.leads.new, "bg-sky-500/60"],
                ["Contacted", overview.leads.contacted, "bg-violet-500/60"],
                ["Qualified", overview.leads.qualified, "bg-emerald-500/60"],
                ["Converted", overview.leads.converted, "bg-amber-500/60"],
                ["Lost", overview.leads.lost, "bg-rose-500/40"],
              ] as [string, number, string][]
            ).map(([label, count, color]) => {
              const pct = overview.leads.total
                ? Math.round((count / overview.leads.total) * 100)
                : 0;
              return (
                <div key={label}>
                  <div className="flex justify-between text-[11px] mb-0.5">
                    <span className="text-white/60">{label}</span>
                    <span className="text-white/40">{count.toLocaleString()} ({pct}%)</span>
                  </div>
                  <div className="h-1 w-full rounded-full bg-white/[0.05] overflow-hidden">
                    <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
