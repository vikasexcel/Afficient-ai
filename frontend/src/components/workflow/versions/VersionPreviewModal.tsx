import { ArrowRight, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { WorkflowVersionDetail } from "@/types/workflow";
import { timeAgo } from "./VersionCard";

const NODE_COLORS: Record<string, { dot: string; text: string; bg: string }> = {
  EMAIL:     { dot: "bg-violet-500", text: "text-violet-200", bg: "bg-violet-900/40 border-violet-700/50" },
  CALL:      { dot: "bg-indigo-500", text: "text-indigo-200", bg: "bg-indigo-900/40 border-indigo-700/50" },
  WAIT:      { dot: "bg-amber-500",  text: "text-amber-200",  bg: "bg-amber-900/40 border-amber-700/50" },
  CONDITION: { dot: "bg-yellow-500", text: "text-yellow-200", bg: "bg-yellow-900/40 border-yellow-700/50" },
  LINKEDIN:  { dot: "bg-sky-500",    text: "text-sky-200",    bg: "bg-sky-900/40 border-sky-700/50" },
  STOP:      { dot: "bg-rose-500",   text: "text-rose-200",   bg: "bg-rose-900/40 border-rose-700/50" },
};

function NodeFlowPreview({ nodes }: { nodes: WorkflowVersionDetail["nodes"] }) {
  if (nodes.length === 0) {
    return <p className="text-white/30 text-[12px]">No nodes in this version.</p>;
  }
  return (
    <div className="flex items-center flex-wrap gap-2 p-3 rounded-lg bg-white/[0.03] border border-white/[0.07]">
      {nodes.map((n, i) => {
        const type = (n.type as string).toUpperCase();
        const c = NODE_COLORS[type] ?? { dot: "bg-white/30", text: "text-white/50", bg: "bg-white/5 border-white/10" };
        return (
          <span key={n.id as string} className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[11px] font-mono ${c.bg} ${c.text}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
              {type}
            </span>
            {i < nodes.length - 1 && <ArrowRight size={11} className="text-white/20 shrink-0" />}
          </span>
        );
      })}
    </div>
  );
}

interface Props {
  detail: WorkflowVersionDetail;
  loadingDetail: boolean;
  restoring: boolean;
  onRestore: () => void;
  onCancel: () => void;
}

export default function VersionPreviewModal({
  detail,
  loadingDetail,
  restoring,
  onRestore,
  onCancel,
}: Props) {
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onCancel(); }}>
      <DialogContent className="max-w-lg bg-[#0d0d14] border-white/[0.08] text-white">
        <DialogHeader>
          <DialogTitle className="text-white">
            Version {detail.version}
          </DialogTitle>
        </DialogHeader>

        {loadingDetail ? (
          <div className="flex items-center justify-center h-32 gap-2 text-white/35">
            <Loader2 size={16} className="animate-spin" />
            <span className="text-sm">Loading snapshot…</span>
          </div>
        ) : (
          <>
            {/* Meta */}
            <div className="flex gap-6 text-[12px] text-white/40">
              <span>Created {timeAgo(detail.created_at)}</span>
              <span>{detail.nodes.length} nodes</span>
              <span>{detail.edges.length} edges</span>
            </div>
            {detail.created_by && (
              <p className="text-[11px] text-white/25 font-mono -mt-2">
                By {detail.created_by.slice(0, 8)}
              </p>
            )}

            {/* Node preview */}
            <div className="flex flex-col gap-2 mt-1">
              <p className="text-[11px] text-white/30 uppercase tracking-widest">Graph snapshot</p>
              <NodeFlowPreview nodes={detail.nodes} />
            </div>
          </>
        )}

        <DialogFooter className="gap-2">
          <Button
            variant="ghost"
            onClick={onCancel}
            className="text-white/50 hover:text-white"
          >
            Cancel
          </Button>
          <Button
            onClick={onRestore}
            disabled={restoring || loadingDetail}
            className="bg-amber-600 hover:bg-amber-500 text-white"
          >
            {restoring ? (
              <>
                <Loader2 size={13} className="animate-spin mr-1.5" />
                Restoring…
              </>
            ) : (
              `Restore Version ${detail.version}`
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
