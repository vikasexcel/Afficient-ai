import { CheckCircle2, LayoutList, Pause, PlayCircle, SkipForward } from "lucide-react";
import { cn } from "@/lib/utils";
import type { OverviewData } from "@/services/analytics";

interface Props {
  overview: OverviewData;
}

export default function CampaignAnalytics({ overview }: Props) {
  const { campaigns, executions } = overview;
  const total = campaigns.total || 1;

  const statuses = [
    { label: "Draft", count: campaigns.draft, color: "bg-white/20", icon: LayoutList },
    { label: "Scheduled", count: campaigns.scheduled, color: "bg-sky-500/60", icon: SkipForward },
    { label: "Active", count: campaigns.active, color: "bg-emerald-500/60", icon: PlayCircle },
    { label: "Paused", count: campaigns.paused, color: "bg-amber-500/60", icon: Pause },
    { label: "Completed", count: campaigns.completed, color: "bg-violet-500/60", icon: CheckCircle2 },
    { label: "Archived", count: campaigns.archived, color: "bg-white/10", icon: LayoutList },
  ] as const;

  const execStats = [
    { label: "Total Executions", value: executions.total },
    { label: "Completed", value: executions.completed },
    { label: "Failed", value: executions.failed },
    { label: "Running", value: executions.running },
    { label: "Queued", value: executions.queued },
  ];

  return (
    <div className="space-y-5">
      {/* Campaign status breakdown */}
      <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
        <h2 className="text-[14px] font-medium text-white">Campaign Status Distribution</h2>
        <p className="text-[12px] text-white/40 mt-0.5">
          {campaigns.total} total campaigns across all statuses
        </p>
        <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 gap-3">
          {statuses.map(({ label, count, color, icon: Icon }) => {
            const pct = Math.round((count / total) * 100);
            return (
              <div
                key={label}
                className="rounded-[10px] border border-white/[0.06] bg-white/[0.015] p-4"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[12px] text-white/55">{label}</span>
                  <Icon size={12} className="text-white/30" />
                </div>
                <div className="text-[24px] font-semibold text-white mt-1.5">{count}</div>
                <div className="mt-2 h-1 w-full rounded-full bg-white/[0.05] overflow-hidden">
                  <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
                </div>
                <div className="text-[10px] text-white/30 mt-1">{pct}% of total</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Execution rate gauges */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <h2 className="text-[14px] font-medium text-white">Execution Metrics</h2>
          <p className="text-[12px] text-white/40 mt-0.5">Within selected period</p>
          <div className="mt-5 space-y-3">
            {execStats.map(({ label, value }) => (
              <div key={label} className="flex items-center justify-between">
                <span className="text-[13px] text-white/65">{label}</span>
                <span className="text-[14px] font-medium text-white">{value.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <h2 className="text-[14px] font-medium text-white">Rate Overview</h2>
          <p className="text-[12px] text-white/40 mt-0.5">Completion vs failure</p>

          {/* Completion rate ring */}
          <div className="mt-6 flex gap-6">
            <div className="flex-1 text-center">
              <div className="text-[36px] font-bold text-emerald-400">
                {executions.completion_rate}%
              </div>
              <div className="text-[12px] text-white/40 mt-1">Completion Rate</div>
              <div className="mt-2 h-2 w-full rounded-full bg-white/[0.05] overflow-hidden">
                <div
                  className="h-full rounded-full bg-emerald-500/70"
                  style={{ width: `${executions.completion_rate}%` }}
                />
              </div>
            </div>
            <div className="flex-1 text-center">
              <div className="text-[36px] font-bold text-rose-400">
                {executions.failure_rate}%
              </div>
              <div className="text-[12px] text-white/40 mt-1">Failure Rate</div>
              <div className="mt-2 h-2 w-full rounded-full bg-white/[0.05] overflow-hidden">
                <div
                  className="h-full rounded-full bg-rose-500/70"
                  style={{ width: `${executions.failure_rate}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
