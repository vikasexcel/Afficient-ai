import type { CampaignMonitorPayload } from "@/types/monitor";
import { parseUtcDate } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-amber-500/10 text-amber-300 border-amber-500/20",
  scheduled: "bg-sky-500/10 text-sky-300 border-sky-500/20",
  active: "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
  paused: "bg-white/10 text-white/60 border-white/20",
  completed: "bg-violet-500/10 text-violet-300 border-violet-500/20",
  archived: "bg-white/5 text-white/40 border-white/10",
};

function formatDate(iso: string) {
  return parseUtcDate(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function CampaignOverview({ data }: { data: CampaignMonitorPayload }) {
  const { metrics } = data;
  const progress = metrics.progress_percent ?? 0;
  const statusCls = STATUS_STYLES[data.campaign_status] ?? STATUS_STYLES.draft;

  return (
    <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-5 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white">{data.campaign_name}</h2>
          <p className="text-[12px] text-white/35 mt-0.5">
            Created {formatDate(data.campaign_created_at)}
          </p>
        </div>
        <span className={`text-[11px] px-2.5 py-1 rounded border font-medium capitalize ${statusCls}`}>
          {data.campaign_status}
        </span>
      </div>

      {/* Progress bar */}
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-[11px] text-white/40">
          <span>{metrics.total_leads.toLocaleString()} total leads</span>
          <span>{progress.toFixed(1)}% complete</span>
        </div>
        <div className="h-2 w-full bg-white/5 rounded-full overflow-hidden">
          <div
            className="h-full bg-violet-500 rounded-full transition-all duration-500"
            style={{ width: `${Math.min(100, progress)}%` }}
          />
        </div>
        <div className="flex justify-between text-[11px] text-white/30">
          <span>{metrics.completed_calls + metrics.failed_calls} processed</span>
          <span>{metrics.pending_leads} pending</span>
        </div>
      </div>
    </div>
  );
}
