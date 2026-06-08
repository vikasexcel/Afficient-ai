import { PhoneCall, PhoneMissed, PhoneOff, Voicemail } from "lucide-react";
import type { CallAnalyticsData } from "@/services/analytics";

interface Props {
  data: CallAnalyticsData;
}

export default function CallAnalytics({ data }: Props) {
  const { attempted, completed, failed, voicemail, daily_trend } = data;
  const maxVal = Math.max(...daily_trend.map((d) => d.attempted), 1);

  const kpis = [
    { label: "Calls Attempted", value: attempted, icon: PhoneCall, color: "text-sky-300 bg-sky-500/10 border-sky-500/20" },
    { label: "Calls Completed", value: completed, icon: PhoneCall, color: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20" },
    { label: "Calls Failed", value: failed, icon: PhoneOff, color: "text-rose-300 bg-rose-500/10 border-rose-500/20" },
    { label: "Voicemail", value: voicemail, icon: Voicemail, color: "text-amber-300 bg-amber-500/10 border-amber-500/20" },
  ];

  const connectRate = attempted ? Math.round((completed / attempted) * 100) : 0;

  return (
    <div className="space-y-5">
      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {kpis.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] p-4">
            <div className={`h-8 w-8 rounded-[8px] border flex items-center justify-center ${color}`}>
              <Icon size={13} />
            </div>
            <div className="mt-3 text-[11px] text-white/45 uppercase tracking-wider">{label}</div>
            <div className="text-[22px] font-semibold text-white mt-0.5">{value.toLocaleString()}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Daily call trend */}
        <div className="lg:col-span-2 rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-[14px] font-medium text-white">Daily Call Trend</h2>
              <p className="text-[12px] text-white/40">Attempted, completed, voicemail per day</p>
            </div>
            <div className="flex items-center gap-3 text-[11px] text-white/50">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-sky-500/70" /> Attempted
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-emerald-500/70" /> Completed
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-amber-500/70" /> Voicemail
              </span>
            </div>
          </div>

          <div className="mt-5 flex items-end gap-1.5 h-40">
            {daily_trend.length === 0 ? (
              <p className="text-[12px] text-white/30 w-full text-center self-center">
                No call activity in selected period
              </p>
            ) : (
              daily_trend.map((d) => (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1 min-w-0">
                  <div className="w-full flex items-end justify-center gap-0.5 h-full">
                    <div
                      className="flex-1 rounded-t-[2px] bg-sky-500/70"
                      style={{ height: `${(d.attempted / maxVal) * 100}%` }}
                      title={`${d.date}: ${d.attempted} attempted`}
                    />
                    <div
                      className="flex-1 rounded-t-[2px] bg-emerald-500/70"
                      style={{ height: `${(d.completed / maxVal) * 100}%` }}
                      title={`${d.completed} completed`}
                    />
                    <div
                      className="flex-1 rounded-t-[2px] bg-amber-500/70"
                      style={{ height: `${(d.voicemail / maxVal) * 100}%` }}
                      title={`${d.voicemail} voicemail`}
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

        {/* Connect rate panel */}
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <h2 className="text-[14px] font-medium text-white">Connect Rate</h2>
          <p className="text-[12px] text-white/40">Completed / attempted</p>

          <div className="mt-6 text-center">
            <div className="text-[44px] font-bold text-emerald-400">{connectRate}%</div>
            <div className="text-[12px] text-white/40 mt-1">of {attempted.toLocaleString()} attempts</div>
          </div>

          <div className="mt-5 h-2 w-full rounded-full bg-white/[0.05] overflow-hidden">
            <div
              className="h-full rounded-full bg-emerald-500/70"
              style={{ width: `${connectRate}%` }}
            />
          </div>

          <div className="mt-5 space-y-2.5">
            {[
              ["Completed", completed, "text-emerald-300"],
              ["Failed", failed, "text-rose-300"],
              ["Voicemail", voicemail, "text-amber-300"],
            ].map(([label, val, cls]) => (
              <div key={label as string} className="flex justify-between text-[12px]">
                <span className="text-white/55">{label}</span>
                <span className={cls as string}>{(val as number).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Missed calls insight */}
      {attempted > 0 && (
        <div className="rounded-[10px] border border-white/[0.06] bg-white/[0.015] p-4 flex items-center gap-3">
          <PhoneMissed size={14} className="text-rose-300 shrink-0" />
          <p className="text-[12px] text-white/60">
            <span className="text-white">{failed.toLocaleString()} calls</span> could not be connected —
            consider reviewing retry configurations or lead data quality.
          </p>
        </div>
      )}
    </div>
  );
}
