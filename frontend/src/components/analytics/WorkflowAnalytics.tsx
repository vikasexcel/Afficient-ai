import { GitBranch, Layers, Workflow } from "lucide-react";
import { cn } from "@/lib/utils";
import type { WorkflowAnalyticsData } from "@/services/analytics";

interface Props {
  data: WorkflowAnalyticsData;
}

const NODE_COLORS: Record<string, string> = {
  email: "bg-sky-500/60 text-sky-300",
  call: "bg-emerald-500/60 text-emerald-300",
  linkedin: "bg-violet-500/60 text-violet-300",
  wait: "bg-amber-500/60 text-amber-300",
  condition: "bg-indigo-500/60 text-indigo-300",
  sms: "bg-teal-500/60 text-teal-300",
  unknown: "bg-white/20 text-white/50",
};

function getNodeColor(type: string) {
  return NODE_COLORS[type.toLowerCase()] ?? NODE_COLORS.unknown;
}

export default function WorkflowAnalytics({ data }: Props) {
  const {
    most_used_workflows,
    node_type_distribution,
    total_workflows,
    total_executions_in_period,
  } = data;

  const maxNodeCount = Math.max(...node_type_distribution.map((n) => n.count), 1);
  const maxExecCount = Math.max(...most_used_workflows.map((w) => w.execution_count), 1);

  return (
    <div className="space-y-5">
      {/* Summary KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[
          { label: "Total Workflows", value: total_workflows, icon: Workflow, color: "text-violet-300 bg-violet-500/10 border-violet-500/20" },
          { label: "Executions (Period)", value: total_executions_in_period, icon: Layers, color: "text-sky-300 bg-sky-500/10 border-sky-500/20" },
          { label: "Node Types Used", value: node_type_distribution.length, icon: GitBranch, color: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20" },
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Most used workflows */}
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <h2 className="text-[14px] font-medium text-white">Most Used Workflows</h2>
          <p className="text-[12px] text-white/40 mt-0.5">By execution count in selected period</p>

          {most_used_workflows.length === 0 ? (
            <p className="text-[12px] text-white/30 mt-6">No executions in selected period.</p>
          ) : (
            <div className="mt-5 space-y-3">
              {most_used_workflows.map((wf, i) => {
                const pct = Math.round((wf.execution_count / maxExecCount) * 100);
                return (
                  <div key={wf.workflow_id} className="space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-[10px] text-white/30 w-4 shrink-0">#{i + 1}</span>
                        <span className="text-[13px] text-white truncate">{wf.campaign_name}</span>
                      </div>
                      <span className="text-[12px] text-violet-300 shrink-0 font-medium">
                        {wf.execution_count.toLocaleString()}
                      </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-white/[0.05] overflow-hidden ml-6">
                      <div
                        className="h-full rounded-full bg-violet-500/60"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Node type distribution */}
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
          <h2 className="text-[14px] font-medium text-white">Node Usage Distribution</h2>
          <p className="text-[12px] text-white/40 mt-0.5">Node types across all org workflows</p>

          {node_type_distribution.length === 0 ? (
            <p className="text-[12px] text-white/30 mt-6">No workflow nodes found.</p>
          ) : (
            <div className="mt-5 space-y-3">
              {node_type_distribution.map((n) => {
                const pct = Math.round((n.count / maxNodeCount) * 100);
                const colorClass = getNodeColor(n.node_type);
                const [bg] = colorClass.split(" ");
                return (
                  <div key={n.node_type}>
                    <div className="flex items-center justify-between text-[12px] mb-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium capitalize",
                            colorClass,
                          )}
                        >
                          {n.node_type}
                        </span>
                      </div>
                      <span className="text-white/55">{n.count} nodes</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-white/[0.05] overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", bg)}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
