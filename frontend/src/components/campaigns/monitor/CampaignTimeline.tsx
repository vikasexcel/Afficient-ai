import { useMemo } from "react";
import type { MonitorExecution, CampaignMonitorPayload } from "@/types/monitor";
import { parseUtcDate } from "@/lib/utils";

const NODE_DOT: Record<string, string> = {
  EMAIL: "bg-violet-500", CALL: "bg-indigo-500", WAIT: "bg-amber-500",
  CONDITION: "bg-yellow-500", LINKEDIN: "bg-sky-500", STOP: "bg-rose-500",
};

function statusIcon(status: MonitorExecution["status"]) {
  switch (status) {
    case "completed": return "✓";
    case "failed":    return "✗";
    case "running":   return "●";
    default:          return "○";
  }
}

function statusColor(status: MonitorExecution["status"]) {
  switch (status) {
    case "completed": return "text-violet-400";
    case "failed":    return "text-rose-400";
    case "running":   return "text-emerald-400";
    default:          return "text-white/30";
  }
}

function formatTs(iso: string) {
  return parseUtcDate(iso).toLocaleTimeString("en-US", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function activityMessage(ex: MonitorExecution, nodeType: string): string {
  const name = ex.lead_name ?? "Lead";
  switch (nodeType) {
    case "EMAIL":
      return ex.status === "failed" ? `Email failed for ${name}` : `Email sent to ${name}`;
    case "CALL":
      return ex.status === "failed" ? `Call failed for ${name}` : `Call completed with ${name}`;
    case "LINKEDIN":
      return ex.status === "failed" ? `LinkedIn action failed for ${name}` : `LinkedIn message sent to ${name}`;
    case "WAIT":
      return `Waiting for ${name}`;
    case "CONDITION":
      return `Condition evaluated for ${name}`;
    case "STOP":
      return `Workflow completed for ${name}`;
    default:
      if (ex.retry_status === "scheduled") return `Retry scheduled for ${name}`;
      return `Execution ${ex.status} for ${name}`;
  }
}

interface Props {
  data: CampaignMonitorPayload;
}

export default function CampaignTimeline({ data }: Props) {
  const nodeTypeMap = useMemo<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    for (const n of data.workflow_nodes) m[n.id] = (n.type ?? "UNKNOWN").toUpperCase();
    return m;
  }, [data.workflow_nodes]);

  const activities = useMemo(() => {
    return [...data.executions]
      .sort((a, b) => parseUtcDate(b.updated_at).getTime() - parseUtcDate(a.updated_at).getTime())
      .slice(0, 20)
      .map((ex) => {
        const nodeType = ex.current_node_id ? (nodeTypeMap[ex.current_node_id] ?? "UNKNOWN") : "UNKNOWN";
        return {
          id: ex.id,
          ts: ex.updated_at,
          nodeType,
          status: ex.status,
          message: activityMessage(ex, nodeType),
        };
      });
  }, [data.executions, nodeTypeMap]);

  if (activities.length === 0) {
    return (
      <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
        <h3 className="text-[12px] font-semibold text-white/50 uppercase tracking-widest mb-2">Activity</h3>
        <p className="text-[12px] text-white/25">No activity yet.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
      <h3 className="text-[12px] font-semibold text-white/50 uppercase tracking-widest mb-4">
        Recent Activity
      </h3>
      <div className="flex flex-col gap-0">
        {activities.map((a, i) => {
          const dot = NODE_DOT[a.nodeType] ?? "bg-white/20";
          const color = statusColor(a.status);
          return (
            <div key={a.id} className="flex gap-3 items-start">
              {/* Timeline */}
              <div className="flex flex-col items-center w-6 shrink-0 pt-1">
                <span className={`text-[11px] ${color}`}>{statusIcon(a.status)}</span>
                {i < activities.length - 1 && (
                  <div className="w-px flex-1 bg-white/[0.06] mt-1" style={{ minHeight: 16 }} />
                )}
              </div>
              {/* Content */}
              <div className="pb-3 flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
                  <p className="text-[12px] text-white/65 leading-snug">{a.message}</p>
                </div>
                <p className="text-[10px] text-white/25 mt-0.5 pl-3">{formatTs(a.ts)}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
