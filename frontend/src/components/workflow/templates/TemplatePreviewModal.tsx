import { Loader2, ArrowRight } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { WorkflowTemplate } from "@/types/workflow";

const NODE_COLORS: Record<string, { dot: string; text: string; bg: string }> = {
  EMAIL:     { dot: "bg-violet-500",  text: "text-violet-200",  bg: "bg-violet-900/40 border-violet-700/50" },
  CALL:      { dot: "bg-indigo-500",  text: "text-indigo-200",  bg: "bg-indigo-900/40 border-indigo-700/50" },
  WAIT:      { dot: "bg-amber-500",   text: "text-amber-200",   bg: "bg-amber-900/40 border-amber-700/50" },
  CONDITION: { dot: "bg-yellow-500",  text: "text-yellow-200",  bg: "bg-yellow-900/40 border-yellow-700/50" },
  LINKEDIN:  { dot: "bg-sky-500",     text: "text-sky-200",     bg: "bg-sky-900/40 border-sky-700/50" },
  STOP:      { dot: "bg-rose-500",    text: "text-rose-200",    bg: "bg-rose-900/40 border-rose-700/50" },
};

function NodeFlowPreview({ nodes }: { nodes: WorkflowTemplate["nodes"] }) {
  return (
    <div className="flex items-center flex-wrap gap-2 p-4 rounded-lg bg-white/[0.03] border border-white/[0.07]">
      {nodes.map((n, i) => {
        const type = (n.type as string).toUpperCase();
        const colors = NODE_COLORS[type] ?? {
          dot: "bg-white/30",
          text: "text-white/60",
          bg: "bg-white/5 border-white/10",
        };
        return (
          <span key={n.id as string} className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded border text-[11px] font-mono font-medium ${colors.bg} ${colors.text}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} />
              {type}
            </span>
            {i < nodes.length - 1 && (
              <ArrowRight size={12} className="text-white/20 shrink-0" />
            )}
          </span>
        );
      })}
    </div>
  );
}

interface Props {
  template: WorkflowTemplate;
  applying: boolean;
  onUse: () => void;
  onCancel: () => void;
}

export default function TemplatePreviewModal({ template, applying, onUse, onCancel }: Props) {
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onCancel(); }}>
      <DialogContent className="max-w-lg bg-[#0d0d14] border-white/[0.08] text-white">
        <DialogHeader>
          <div className="flex items-center gap-2 mb-1">
            {template.category && (
              <span className="text-[10px] px-2 py-0.5 rounded border border-white/10 bg-white/5 text-white/40 uppercase tracking-widest">
                {template.category}
              </span>
            )}
            {template.is_system && (
              <span className="text-[10px] px-2 py-0.5 rounded border border-violet-700/40 bg-violet-900/30 text-violet-400 uppercase tracking-widest">
                System
              </span>
            )}
          </div>
          <DialogTitle className="text-white text-lg">{template.name}</DialogTitle>
          {template.description && (
            <DialogDescription className="text-white/50 text-sm leading-relaxed">
              {template.description}
            </DialogDescription>
          )}
        </DialogHeader>

        {/* Node flow preview */}
        <div className="my-2 flex flex-col gap-2">
          <p className="text-[11px] text-white/30 uppercase tracking-widest">Workflow preview</p>
          <NodeFlowPreview nodes={template.nodes} />
        </div>

        {/* Stats */}
        <div className="flex gap-4 text-[12px] text-white/40">
          <span>{template.nodes.length} nodes</span>
          <span>{template.edges.length} connections</span>
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="ghost"
            onClick={onCancel}
            className="text-white/50 hover:text-white"
          >
            Cancel
          </Button>
          <Button
            onClick={onUse}
            disabled={applying}
            className="bg-violet-600 hover:bg-violet-500 text-white"
          >
            {applying ? (
              <>
                <Loader2 size={13} className="animate-spin mr-1.5" />
                Applying…
              </>
            ) : (
              "Use Template"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
