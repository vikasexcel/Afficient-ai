import { X, ArrowRight } from "lucide-react";
import { parseUtcDate } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { MonitorExecution, CampaignMonitorPayload } from "@/types/monitor";

const STATUS_COLOR: Record<string, string> = {
  queued: "text-sky-300",
  running: "text-emerald-300",
  completed: "text-violet-300",
  failed: "text-rose-300",
};

const NODE_DOT: Record<string, string> = {
  EMAIL: "bg-violet-500", CALL: "bg-indigo-500", WAIT: "bg-amber-500",
  CONDITION: "bg-yellow-500", LINKEDIN: "bg-sky-500", STOP: "bg-rose-500",
};

function formatTs(iso: string) {
  return parseUtcDate(iso).toLocaleString("en-US", {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

interface Props {
  execution: MonitorExecution | null;
  data: CampaignMonitorPayload;
  onClose: () => void;
}

export default function ExecutionDetailsDrawer({ execution, data, onClose }: Props) {
  if (!execution) return null;

  // Build node type lookup
  const nodeTypeMap: Record<string, string> = {};
  const nodeLabelMap: Record<string, string> = {};
  for (const n of data.workflow_nodes) {
    nodeTypeMap[n.id] = (n.type ?? "UNKNOWN").toUpperCase();
    nodeLabelMap[n.id] = (n.label as string | undefined) ?? n.id;
  }

  const currentType = execution.current_node_id
    ? (nodeTypeMap[execution.current_node_id] ?? "UNKNOWN")
    : null;

  return (
    <Sheet open={!!execution} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent
        side="right"
        className="w-96 p-0 bg-[#0d0d14] border-l border-white/[0.07] text-white flex flex-col gap-0 [&>button]:hidden"
      >
        <SheetHeader className="flex-row items-center gap-2 px-4 py-3 border-b border-white/[0.07] space-y-0 shrink-0">
          <SheetTitle className="text-[12px] font-bold uppercase tracking-widest text-white/70 flex-1">
            Execution Details
          </SheetTitle>
          <button onClick={onClose} className="text-white/30 hover:text-white/70 p-0.5">
            <X size={14} />
          </button>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-5">
          {/* Lead */}
          <section className="flex flex-col gap-1.5">
            <p className="text-[10px] text-white/30 uppercase tracking-widest">Lead</p>
            <p className="text-[14px] font-semibold text-white">{execution.lead_name ?? "—"}</p>
            {execution.lead_email && <p className="text-[12px] text-white/45">{execution.lead_email}</p>}
            {execution.lead_phone && <p className="text-[12px] text-white/35">{execution.lead_phone}</p>}
          </section>

          {/* Status */}
          <section className="flex flex-col gap-2">
            <p className="text-[10px] text-white/30 uppercase tracking-widest">Status</p>
            <div className="flex gap-4 text-[12px]">
              <div>
                <span className="text-white/30">Status: </span>
                <span className={`font-medium capitalize ${STATUS_COLOR[execution.status] ?? "text-white/60"}`}>
                  {execution.status}
                </span>
              </div>
              <div>
                <span className="text-white/30">Attempt: </span>
                <span className="text-white/70">#{execution.attempt_number}</span>
              </div>
            </div>
            {execution.retry_status && (
              <div className="text-[12px]">
                <span className="text-white/30">Retry: </span>
                <span className="text-amber-400 capitalize">{execution.retry_status}</span>
              </div>
            )}
            {execution.outcome && (
              <div className="text-[12px]">
                <span className="text-white/30">Outcome: </span>
                <span className="text-white/60">{execution.outcome}</span>
              </div>
            )}
          </section>

          {/* Current node */}
          {currentType && (
            <section className="flex flex-col gap-2">
              <p className="text-[10px] text-white/30 uppercase tracking-widest">Current Node</p>
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                <span className={`w-2.5 h-2.5 rounded-full ${NODE_DOT[currentType] ?? "bg-white/30"}`} />
                <span className="text-[13px] font-mono font-medium text-white/80">{currentType}</span>
                {execution.current_node_id && (
                  <span className="text-[10px] text-white/25 ml-auto truncate font-mono">
                    {nodeLabelMap[execution.current_node_id] ?? execution.current_node_id}
                  </span>
                )}
              </div>
            </section>
          )}

          {/* Workflow path */}
          {data.workflow_nodes.length > 0 && (
            <section className="flex flex-col gap-2">
              <p className="text-[10px] text-white/30 uppercase tracking-widest">Workflow Path</p>
              <div className="flex items-center flex-wrap gap-1.5">
                {data.workflow_nodes.map((n, i) => {
                  const type = (n.type ?? "").toUpperCase();
                  const dot = NODE_DOT[type] ?? "bg-white/20";
                  const isCurrent = n.id === execution.current_node_id;
                  const hasOutput = execution.node_outputs && execution.node_outputs[n.id];
                  return (
                    <span key={n.id} className="flex items-center gap-1">
                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono border transition-all ${
                        isCurrent
                          ? "border-violet-500/60 bg-violet-900/30 text-violet-300"
                          : hasOutput
                          ? "border-white/10 bg-white/5 text-white/50"
                          : "border-white/[0.05] bg-transparent text-white/20"
                      }`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
                        {type}
                      </span>
                      {i < data.workflow_nodes.length - 1 && (
                        <ArrowRight size={9} className="text-white/15" />
                      )}
                    </span>
                  );
                })}
              </div>
              <p className="text-[10px] text-white/25">Current node is highlighted in violet.</p>
            </section>
          )}

          {/* Failure reason */}
          {execution.last_failure_reason && (
            <section className="flex flex-col gap-1.5">
              <p className="text-[10px] text-white/30 uppercase tracking-widest">Failure Reason</p>
              <p className="text-[12px] text-rose-400/80 leading-relaxed p-3 rounded-lg bg-rose-900/10 border border-rose-800/20">
                {execution.last_failure_reason}
              </p>
            </section>
          )}

          {/* Next retry */}
          {execution.next_retry_at && (
            <section className="flex flex-col gap-1.5">
              <p className="text-[10px] text-white/30 uppercase tracking-widest">Next Retry</p>
              <p className="text-[12px] text-amber-400/80">{formatTs(execution.next_retry_at)}</p>
            </section>
          )}

          {/* Node outputs */}
          {execution.node_outputs && Object.keys(execution.node_outputs).length > 0 && (
            <section className="flex flex-col gap-2">
              <p className="text-[10px] text-white/30 uppercase tracking-widest">Node Outputs</p>
              <div className="flex flex-col gap-1.5">
                {Object.entries(execution.node_outputs).map(([nodeId, output]) => {
                  const type = nodeTypeMap[nodeId] ?? nodeId;
                  return (
                    <div key={nodeId} className="px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.06]">
                      <p className="text-[10px] text-white/35 font-mono mb-1">{type}</p>
                      <pre className="text-[10px] text-white/50 whitespace-pre-wrap break-all">
                        {JSON.stringify(output, null, 2)}
                      </pre>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Timestamps */}
          <section className="flex flex-col gap-1 text-[11px] text-white/25">
            <p>Created: {formatTs(execution.created_at)}</p>
            <p>Updated: {formatTs(execution.updated_at)}</p>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}
