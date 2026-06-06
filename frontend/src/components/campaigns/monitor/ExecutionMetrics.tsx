import type { CampaignMonitorPayload } from "@/types/monitor";

interface StatCardProps {
  label: string;
  value: number;
  color: string;
  pulse?: boolean;
}

function StatCard({ label, value, color, pulse }: StatCardProps) {
  return (
    <div className="flex-1 rounded-xl border border-white/[0.08] bg-white/[0.03] p-4 flex flex-col gap-2">
      <div className="flex items-center gap-1.5">
        <span className={`w-2 h-2 rounded-full ${color} ${pulse ? "animate-pulse" : ""}`} />
        <span className="text-[11px] text-white/40 uppercase tracking-widest">{label}</span>
      </div>
      <span className="text-2xl font-bold text-white">{value.toLocaleString()}</span>
    </div>
  );
}

export default function ExecutionMetrics({ data }: { data: CampaignMonitorPayload }) {
  const m = data.metrics;
  const retrying = (m.scheduled_retries as number | undefined) ?? 0;

  return (
    <div className="flex gap-3 flex-wrap">
      <StatCard label="Queued"    value={m.queued_leads}      color="bg-sky-500" />
      <StatCard label="Running"   value={m.active_calls}      color="bg-emerald-500" pulse={m.active_calls > 0} />
      <StatCard label="Completed" value={m.completed_calls}   color="bg-violet-500" />
      <StatCard label="Failed"    value={m.failed_executions} color="bg-rose-500" />
      <StatCard label="Retrying"  value={retrying}            color="bg-amber-500" pulse={retrying > 0} />
    </div>
  );
}
