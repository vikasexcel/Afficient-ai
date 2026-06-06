import { useMemo } from "react";
import type { CampaignMonitorPayload, MonitorExecution } from "@/types/monitor";

const NODE_COLORS: Record<string, string> = {
  EMAIL: "text-violet-300",
  CALL: "text-indigo-300",
  WAIT: "text-amber-300",
  CONDITION: "text-yellow-300",
  LINKEDIN: "text-sky-300",
  STOP: "text-rose-300",
};

const NODE_DOT: Record<string, string> = {
  EMAIL: "bg-violet-500",
  CALL: "bg-indigo-500",
  WAIT: "bg-amber-500",
  CONDITION: "bg-yellow-500",
  LINKEDIN: "bg-sky-500",
  STOP: "bg-rose-500",
};

interface NodeStat {
  type: string;
  nodeId: string;
  label: string;
  queued: number;
  running: number;
  completed: number;
  failed: number;
}

export default function NodeMetrics({ data }: { data: CampaignMonitorPayload }) {
  const stats = useMemo<NodeStat[]>(() => {
    const byNodeId: Record<string, NodeStat> = {};

    // Build a nodeId → type map from workflow nodes
    const nodeTypeMap: Record<string, string> = {};
    const nodeLabelMap: Record<string, string> = {};
    for (const n of data.workflow_nodes) {
      const type = (n.type ?? "UNKNOWN").toUpperCase();
      nodeTypeMap[n.id] = type;
      nodeLabelMap[n.id] = (n.label as string | undefined) ?? type;
    }

    for (const ex of data.executions) {
      const nid = ex.current_node_id;
      if (!nid) continue;
      if (!byNodeId[nid]) {
        byNodeId[nid] = {
          type: nodeTypeMap[nid] ?? "UNKNOWN",
          nodeId: nid,
          label: nodeLabelMap[nid] ?? nid,
          queued: 0, running: 0, completed: 0, failed: 0,
        };
      }
      const stat = byNodeId[nid];
      if (ex.status === "queued")    stat.queued++;
      if (ex.status === "running")   stat.running++;
      if (ex.status === "completed") stat.completed++;
      if (ex.status === "failed")    stat.failed++;
    }

    return Object.values(byNodeId).sort((a, b) => a.type.localeCompare(b.type));
  }, [data]);

  if (stats.length === 0) {
    return (
      <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
        <h3 className="text-[12px] font-semibold text-white/50 uppercase tracking-widest mb-2">Node Metrics</h3>
        <p className="text-[12px] text-white/25">No node-level data yet — executions will populate this section.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-5">
      <h3 className="text-[12px] font-semibold text-white/50 uppercase tracking-widest mb-4">Node Metrics</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {stats.map((s) => {
          const total = s.queued + s.running + s.completed + s.failed;
          const color = NODE_COLORS[s.type] ?? "text-white/60";
          const dot = NODE_DOT[s.type] ?? "bg-white/30";
          return (
            <div key={s.nodeId} className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3 flex flex-col gap-2">
              <div className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${dot}`} />
                <span className={`text-[11px] font-bold uppercase tracking-widest ${color}`}>{s.type}</span>
              </div>
              <p className="text-[10px] text-white/30 font-mono truncate">{s.label}</p>
              <div className="flex flex-col gap-0.5 text-[11px]">
                {s.running > 0  && <span className="text-emerald-400">{s.running} running</span>}
                {s.queued > 0   && <span className="text-sky-400">{s.queued} queued</span>}
                {s.completed > 0 && <span className="text-white/40">{s.completed} completed</span>}
                {s.failed > 0   && <span className="text-rose-400">{s.failed} failed</span>}
                {total === 0    && <span className="text-white/20">0 executions</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
