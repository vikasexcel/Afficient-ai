import { Link2, MessageSquare, XCircle } from "lucide-react";
import type { LinkedInAnalyticsData } from "@/services/analytics";

interface Props {
  data: LinkedInAnalyticsData;
}

export default function LinkedInAnalytics({ data }: Props) {
  const { connections_sent, messages_sent, failed, daily_trend } = data;
  const maxVal = Math.max(
    ...daily_trend.map((d) => d.connections + d.messages + d.failed),
    1,
  );
  const total = connections_sent + messages_sent + failed;

  return (
    <div className="space-y-5">
      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[
          {
            label: "Connection Requests Sent",
            value: connections_sent,
            icon: Link2,
            color: "text-sky-300 bg-sky-500/10 border-sky-500/20",
          },
          {
            label: "Messages Sent",
            value: messages_sent,
            icon: MessageSquare,
            color: "text-violet-300 bg-violet-500/10 border-violet-500/20",
          },
          {
            label: "Failures",
            value: failed,
            icon: XCircle,
            color: "text-rose-300 bg-rose-500/10 border-rose-500/20",
          },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] p-5">
            <div className={`h-9 w-9 rounded-[8px] border flex items-center justify-center ${color}`}>
              <Icon size={14} />
            </div>
            <div className="mt-3 text-[11px] text-white/45 uppercase tracking-wider">{label}</div>
            <div className="text-[28px] font-semibold text-white mt-0.5">{value.toLocaleString()}</div>
            <div className="text-[11px] text-white/30 mt-0.5">
              {total ? Math.round((value / total) * 100) : 0}% of total
            </div>
          </div>
        ))}
      </div>

      {/* Daily trend */}
      <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-[14px] font-medium text-white">Daily LinkedIn Trend</h2>
            <p className="text-[12px] text-white/40">Connection requests, messages, and failures</p>
          </div>
          <div className="flex items-center gap-3 text-[11px] text-white/50">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-sky-500/70" /> Connections
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-violet-500/70" /> Messages
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-rose-500/60" /> Failed
            </span>
          </div>
        </div>

        <div className="mt-5 flex items-end gap-1.5 h-40">
          {daily_trend.length === 0 ? (
            <p className="text-[12px] text-white/30 w-full text-center self-center">
              No LinkedIn activity in selected period
            </p>
          ) : (
            daily_trend.map((d) => {
              const total = d.connections + d.messages + d.failed;
              return (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                  <div className="w-full flex items-end justify-center gap-0.5 h-full">
                    <div
                      className="flex-1 rounded-t-[2px] bg-sky-500/70"
                      style={{ height: `${(d.connections / maxVal) * 100}%` }}
                      title={`${d.date}: ${d.connections} connections`}
                    />
                    <div
                      className="flex-1 rounded-t-[2px] bg-violet-500/70"
                      style={{ height: `${(d.messages / maxVal) * 100}%` }}
                      title={`${d.messages} messages`}
                    />
                    <div
                      className="flex-1 rounded-t-[2px] bg-rose-500/60"
                      style={{ height: `${(d.failed / maxVal) * 100}%` }}
                      title={`${d.failed} failed`}
                    />
                  </div>
                  <span className="text-[9px] text-white/30 truncate max-w-full">
                    {d.date.slice(5)}
                  </span>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Success summary */}
      <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
        <h2 className="text-[14px] font-medium text-white">LinkedIn Success Summary</h2>
        <p className="text-[12px] text-white/40 mt-0.5">Across the selected period</p>

        <div className="mt-4 space-y-3">
          {[
            ["Connection Requests", connections_sent, "bg-sky-500/60"],
            ["Direct Messages", messages_sent, "bg-violet-500/60"],
            ["Failures", failed, "bg-rose-500/60"],
          ].map(([label, count, color]) => {
            const pct = total ? Math.round(((count as number) / total) * 100) : 0;
            return (
              <div key={label as string}>
                <div className="flex justify-between text-[12px] mb-1">
                  <span className="text-white/65">{label}</span>
                  <span className="text-white/45">
                    {(count as number).toLocaleString()} ({pct}%)
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-white/[0.05] overflow-hidden">
                  <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
