import { useState } from "react";
import { GitBranch, LayoutTemplate, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import TemplateSelector from "@/components/workflow/templates/TemplateSelector";
import type { WorkflowTemplate } from "@/types/workflow";
import type { WizardDraft } from "../types";

const NODE_COLORS: Record<string, string> = {
  EMAIL: "bg-violet-500",
  CALL: "bg-indigo-500",
  WAIT: "bg-amber-500",
  CONDITION: "bg-yellow-500",
  LINKEDIN: "bg-sky-500",
  STOP: "bg-rose-500",
};

interface Props {
  draft: WizardDraft;
  onChange: (partial: Partial<WizardDraft>) => void;
}

export default function WorkflowStep({ draft, onChange }: Props) {
  const [templateSelectorOpen, setTemplateSelectorOpen] = useState(false);

  const hasWorkflow = draft.workflow_nodes.length > 0;

  function applyTemplate(template: WorkflowTemplate) {
    onChange({
      workflow_nodes: template.nodes as unknown[],
      workflow_edges: template.edges as unknown[],
      workflow_template_name: template.name,
    });
  }

  function clearWorkflow() {
    onChange({
      workflow_nodes: [],
      workflow_edges: [],
      workflow_template_name: null,
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-base font-semibold text-white">Workflow</h2>
        <p className="text-[13px] text-white/40 mt-0.5">
          Choose a template to pre-populate the campaign workflow, or skip to build from scratch in the Workflow Builder.
        </p>
      </div>

      {!hasWorkflow ? (
        <div className="flex flex-col items-center gap-5 py-10 rounded-lg border border-white/[0.07] bg-white/[0.02]">
          <div className="h-12 w-12 rounded-full bg-white/5 border border-white/10 flex items-center justify-center">
            <GitBranch size={20} className="text-white/30" />
          </div>
          <div className="text-center">
            <p className="text-white/60 text-sm">No workflow selected</p>
            <p className="text-white/30 text-[12px] mt-0.5">
              You can build the workflow in the Workflow Builder after creation.
            </p>
          </div>
          <div className="flex gap-3">
            <Button
              variant="ghost"
              className="text-white/50 hover:text-white border border-white/10"
              onClick={() => onChange({ workflow_nodes: [], workflow_edges: [], workflow_template_name: "Blank" })}
            >
              Start Blank
            </Button>
            <Button
              onClick={() => setTemplateSelectorOpen(true)}
              className="bg-violet-600 hover:bg-violet-500 text-white"
            >
              <LayoutTemplate size={14} className="mr-2" />
              Use Template
            </Button>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-violet-700/40 bg-violet-900/10 p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <GitBranch size={14} className="text-violet-300" />
              <span className="text-[13px] font-medium text-white">
                {draft.workflow_template_name ?? "Custom workflow"}
              </span>
            </div>
            <button
              onClick={clearWorkflow}
              className="text-white/30 hover:text-rose-400 transition-colors"
              title="Remove workflow"
            >
              <Trash2 size={13} />
            </button>
          </div>

          {/* Node preview */}
          <div className="flex items-center flex-wrap gap-1.5">
            {(draft.workflow_nodes as Array<{ type?: string; id?: string }>)
              .slice(0, 8)
              .map((n, i) => {
                const type = (n.type ?? "").toUpperCase();
                const dot = NODE_COLORS[type] ?? "bg-white/30";
                return (
                  <span key={n.id ?? i} className="flex items-center gap-1">
                    <span className={`w-2 h-2 rounded-full ${dot}`} />
                    <span className="text-[10px] text-white/50 font-mono">{type}</span>
                    {i < Math.min(draft.workflow_nodes.length, 8) - 1 && (
                      <span className="text-white/20 text-[10px]">→</span>
                    )}
                  </span>
                );
              })}
            {draft.workflow_nodes.length > 8 && (
              <span className="text-[10px] text-white/30">
                +{draft.workflow_nodes.length - 8} more
              </span>
            )}
          </div>

          <div className="flex items-center justify-between text-[11px] text-white/35">
            <span>{draft.workflow_nodes.length} nodes · {draft.workflow_edges.length} connections</span>
            <button
              onClick={() => setTemplateSelectorOpen(true)}
              className="text-violet-400/70 hover:text-violet-300 transition-colors"
            >
              Change template
            </button>
          </div>
        </div>
      )}

      <TemplateSelector
        open={templateSelectorOpen}
        hasExistingNodes={hasWorkflow}
        onClose={() => setTemplateSelectorOpen(false)}
        onApply={(template) => {
          applyTemplate(template);
          setTemplateSelectorOpen(false);
        }}
      />
    </div>
  );
}
