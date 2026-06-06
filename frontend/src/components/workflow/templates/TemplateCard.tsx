import type { WorkflowTemplate } from "@/types/workflow";

const NODE_COLORS: Record<string, string> = {
  EMAIL: "bg-violet-500",
  CALL: "bg-indigo-500",
  WAIT: "bg-amber-500",
  CONDITION: "bg-yellow-500",
  LINKEDIN: "bg-sky-500",
  STOP: "bg-rose-500",
};

const CATEGORY_COLORS: Record<string, string> = {
  "cold outreach": "bg-violet-900/50 text-violet-300 border-violet-700/40",
  "follow-up": "bg-indigo-900/50 text-indigo-300 border-indigo-700/40",
  linkedin: "bg-sky-900/50 text-sky-300 border-sky-700/40",
  qualification: "bg-amber-900/50 text-amber-300 border-amber-700/40",
  "demo booking": "bg-emerald-900/50 text-emerald-300 border-emerald-700/40",
};

function categoryBadge(category: string | null) {
  if (!category) return null;
  const key = category.toLowerCase();
  const cls =
    CATEGORY_COLORS[key] ??
    "bg-white/5 text-white/40 border-white/10";
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded border font-medium ${cls}`}>
      {category}
    </span>
  );
}

/** Render a compact node-chain preview: NODE → NODE → NODE */
function NodeChain({ nodes }: { nodes: WorkflowTemplate["nodes"] }) {
  const visible = nodes.slice(0, 6);
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {visible.map((n, i) => {
        const type = (n.type as string).toUpperCase();
        const dot = NODE_COLORS[type] ?? "bg-white/30";
        return (
          <span key={n.id as string} className="flex items-center gap-1">
            <span className={`w-2 h-2 rounded-full ${dot}`} />
            <span className="text-[10px] text-white/50 font-mono">{type}</span>
            {i < visible.length - 1 && (
              <span className="text-white/20 text-[10px]">→</span>
            )}
          </span>
        );
      })}
      {nodes.length > 6 && (
        <span className="text-[10px] text-white/30">+{nodes.length - 6}</span>
      )}
    </div>
  );
}

interface Props {
  template: WorkflowTemplate;
  onClick: () => void;
}

export default function TemplateCard({ template, onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className="group w-full text-left rounded-lg border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:border-white/[0.15] transition-all duration-150 p-4 flex flex-col gap-3"
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <span className="text-[13px] font-semibold text-white/90 leading-snug">
          {template.name}
        </span>
        {template.is_system && (
          <span className="shrink-0 text-[9px] px-1.5 py-0.5 rounded border border-white/10 bg-white/5 text-white/30 uppercase tracking-widest">
            System
          </span>
        )}
      </div>

      {/* Description */}
      {template.description && (
        <p className="text-[12px] text-white/40 leading-relaxed line-clamp-2">
          {template.description}
        </p>
      )}

      {/* Node chain */}
      <NodeChain nodes={template.nodes} />

      {/* Footer */}
      <div className="flex items-center justify-between mt-auto pt-1 border-t border-white/[0.05]">
        {categoryBadge(template.category)}
        <span className="text-[10px] text-white/25">
          {template.nodes.length} nodes · {template.edges.length} edges
        </span>
      </div>
    </button>
  );
}
