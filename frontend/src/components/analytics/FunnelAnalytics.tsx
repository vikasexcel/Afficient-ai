import { ArrowDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FunnelData } from "@/services/analytics";

interface Props {
  data: FunnelData;
}

const STEP_COLORS = [
  "bg-sky-500/60",
  "bg-indigo-500/60",
  "bg-violet-500/60",
  "bg-amber-500/60",
  "bg-emerald-500/60",
  "bg-teal-500/60",
];

const STEP_TEXT_COLORS = [
  "text-sky-300",
  "text-indigo-300",
  "text-violet-300",
  "text-amber-300",
  "text-emerald-300",
  "text-teal-300",
];

export default function FunnelAnalytics({ data }: Props) {
  const { steps } = data;
  const top = steps[0]?.count || 1;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Funnel visualization */}
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <h2 className="text-[14px] font-medium text-white">Lead Conversion Funnel</h2>
          <p className="text-[12px] text-white/40 mt-0.5">
            From upload to meeting booked
          </p>

          <div className="mt-6 space-y-1">
            {steps.map((step, i) => {
              const dropoff =
                i > 0 ? steps[i - 1].count - step.count : 0;
              const dropoffPct =
                i > 0 && steps[i - 1].count
                  ? Math.round((dropoff / steps[i - 1].count) * 100)
                  : 0;

              return (
                <div key={step.label}>
                  {i > 0 && (
                    <div className="flex items-center gap-2 py-1 pl-2">
                      <ArrowDown size={11} className="text-white/20" />
                      {dropoff > 0 && (
                        <span className="text-[10px] text-rose-300/60">
                          −{dropoff.toLocaleString()} ({dropoffPct}% drop-off)
                        </span>
                      )}
                    </div>
                  )}
                  <div className="rounded-[8px] border border-white/[0.05] bg-white/[0.015] p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[13px] text-white/75">{step.label}</span>
                      <span className={cn("text-[15px] font-semibold", STEP_TEXT_COLORS[i])}>
                        {step.count.toLocaleString()}
                      </span>
                    </div>
                    <div className="h-2 w-full rounded-full bg-white/[0.04] overflow-hidden">
                      <div
                        className={cn("h-full rounded-full transition-all", STEP_COLORS[i])}
                        style={{ width: `${step.pct}%` }}
                      />
                    </div>
                    <div className="text-[10px] text-white/30 mt-1">{step.pct}% of uploaded leads</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Funnel metrics table */}
        <div className="space-y-4">
          <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
            <h2 className="text-[14px] font-medium text-white">Stage Metrics</h2>
            <p className="text-[12px] text-white/40 mt-0.5">Absolute count and conversion rate</p>

            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-white/[0.04]">
                    <th className="pb-2 text-left text-white/40 font-medium">Stage</th>
                    <th className="pb-2 text-right text-white/40 font-medium">Count</th>
                    <th className="pb-2 text-right text-white/40 font-medium">% of Total</th>
                    <th className="pb-2 text-right text-white/40 font-medium">Stage Conv.</th>
                  </tr>
                </thead>
                <tbody>
                  {steps.map((step, i) => {
                    const prevCount = i > 0 ? steps[i - 1].count : step.count;
                    const stageConv = prevCount
                      ? Math.round((step.count / prevCount) * 100)
                      : 100;
                    return (
                      <tr key={step.label} className="border-b border-white/[0.03]">
                        <td className="py-2.5 text-white/70">{step.label}</td>
                        <td className={cn("py-2.5 text-right font-medium", STEP_TEXT_COLORS[i])}>
                          {step.count.toLocaleString()}
                        </td>
                        <td className="py-2.5 text-right text-white/45">{step.pct}%</td>
                        <td className="py-2.5 text-right text-white/45">
                          {i === 0 ? "—" : `${stageConv}%`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Overall conversion */}
          {steps.length >= 2 && (
            <div className="rounded-[10px] border border-white/[0.06] bg-white/[0.015] p-4">
              <div className="text-[11px] text-white/40 uppercase tracking-wider">
                Overall Conversion
              </div>
              <div className="text-[32px] font-bold text-emerald-400 mt-1">
                {steps[steps.length - 1].pct}%
              </div>
              <div className="text-[12px] text-white/40">
                {steps[0].label} → {steps[steps.length - 1].label}
              </div>
              <div className="mt-3 h-1.5 w-full rounded-full bg-white/[0.05] overflow-hidden">
                <div
                  className="h-full rounded-full bg-emerald-500/70"
                  style={{ width: `${steps[steps.length - 1].pct}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
