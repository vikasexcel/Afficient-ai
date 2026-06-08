import { Mail, MailX, Percent } from "lucide-react";
import type { EmailAnalyticsData } from "@/services/analytics";

interface Props {
  data: EmailAnalyticsData;
}

export default function EmailAnalytics({ data }: Props) {
  const { sent, failed, success_rate, daily_trend } = data;
  const maxVal = Math.max(...daily_trend.map((d) => d.sent + d.failed), 1);

  return (
    <div className="space-y-5">
      {/* KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[
          { label: "Emails Sent", value: sent, icon: Mail, color: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20" },
          { label: "Emails Failed", value: failed, icon: MailX, color: "text-rose-300 bg-rose-500/10 border-rose-500/20" },
          { label: "Success Rate", value: `${success_rate}%`, icon: Percent, color: "text-violet-300 bg-violet-500/10 border-violet-500/20" },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] p-5">
            <div className={`h-9 w-9 rounded-[8px] border flex items-center justify-center ${color}`}>
              <Icon size={14} />
            </div>
            <div className="mt-3 text-[11px] text-white/45 uppercase tracking-wider">{label}</div>
            <div className="text-[28px] font-semibold text-white mt-0.5">{value}</div>
          </div>
        ))}
      </div>

      {/* Daily trend chart */}
      <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-[14px] font-medium text-white">Daily Email Trend</h2>
            <p className="text-[12px] text-white/40">Sent vs failed emails per day</p>
          </div>
          <div className="flex items-center gap-4 text-[11px] text-white/50">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-emerald-500/70" /> Sent
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-rose-500/70" /> Failed
            </span>
          </div>
        </div>

        <div className="mt-5 flex items-end gap-1.5 h-40">
          {daily_trend.length === 0 ? (
            <p className="text-[12px] text-white/30 w-full text-center self-center">
              No email activity in selected period
            </p>
          ) : (
            daily_trend.map((d) => (
              <div key={d.date} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                <div className="w-full flex items-end justify-center gap-0.5 h-full">
                  <div
                    className="flex-1 rounded-t-[2px] bg-emerald-500/70"
                    style={{ height: `${(d.sent / maxVal) * 100}%` }}
                    title={`${d.date}: ${d.sent} sent`}
                  />
                  <div
                    className="flex-1 rounded-t-[2px] bg-rose-500/70"
                    style={{ height: `${(d.failed / maxVal) * 100}%` }}
                    title={`${d.date}: ${d.failed} failed`}
                  />
                </div>
                <span className="text-[9px] text-white/30 truncate max-w-full">
                  {d.date.slice(5)}
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Breakdown table */}
      {daily_trend.length > 0 && (
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] overflow-hidden">
          <div className="p-4 border-b border-white/[0.04]">
            <h2 className="text-[13px] font-medium text-white">Daily Breakdown</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-white/[0.04]">
                  <th className="px-4 py-2.5 text-left text-white/40 font-medium">Date</th>
                  <th className="px-4 py-2.5 text-right text-white/40 font-medium">Sent</th>
                  <th className="px-4 py-2.5 text-right text-white/40 font-medium">Failed</th>
                  <th className="px-4 py-2.5 text-right text-white/40 font-medium">Rate</th>
                </tr>
              </thead>
              <tbody>
                {daily_trend.map((d) => {
                  const total = d.sent + d.failed;
                  const rate = total ? Math.round((d.sent / total) * 100) : 0;
                  return (
                    <tr key={d.date} className="border-b border-white/[0.03] hover:bg-white/[0.015]">
                      <td className="px-4 py-2 text-white/70">{d.date}</td>
                      <td className="px-4 py-2 text-right text-emerald-300">{d.sent}</td>
                      <td className="px-4 py-2 text-right text-rose-300">{d.failed}</td>
                      <td className="px-4 py-2 text-right text-white/55">{rate}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
