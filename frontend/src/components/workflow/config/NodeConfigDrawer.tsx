/**
 * NodeConfigDrawer — right-side panel that opens when a workflow node is clicked.
 *
 * Renders inside the flex layout so the canvas remains fully visible.
 * Config changes are applied immediately via onConfigChange → setNodes in
 * WorkflowBuilderInner.  The Save button persists everything via PUT /workflow.
 */
import { X } from "lucide-react";
import {
  Mail,
  Phone,
  Clock,
  GitBranch,
  Briefcase,
  StopCircle,
} from "lucide-react";
import type { Node } from "@xyflow/react";
import type {
  NodeData,
  NodeConfig,
  EmailConfig,
  CallConfig,
  WaitConfig,
  ConditionConfig,
  LinkedinConfig,
} from "@/types/workflow";

import EmailConfigPanel from "./EmailConfig";
import CallConfigPanel from "./CallConfig";
import WaitConfigPanel from "./WaitConfig";
import ConditionConfigPanel from "./ConditionConfig";
import LinkedinConfigPanel from "./LinkedinConfig";
import StopConfigPanel from "./StopConfig";

// ---------------------------------------------------------------------------
// Defaults — applied when a node has no config yet
// ---------------------------------------------------------------------------

const DEFAULTS: Record<string, NodeConfig> = {
  EMAIL: { subject: "", body: "" } as EmailConfig,
  CALL: { playbook_id: "", retry_count: 3 } as CallConfig,
  WAIT: { duration: 1, unit: "hours" } as WaitConfig,
  CONDITION: { condition_type: "EMAIL_SENT" } as ConditionConfig,
  LINKEDIN: { action: "CONNECT", message: "" } as LinkedinConfig,
};

const NODE_META: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  EMAIL: { icon: Mail, label: "Email", color: "text-violet-300" },
  CALL: { icon: Phone, label: "Call", color: "text-indigo-300" },
  WAIT: { icon: Clock, label: "Wait", color: "text-amber-300" },
  CONDITION: { icon: GitBranch, label: "Condition", color: "text-yellow-300" },
  LINKEDIN: { icon: Briefcase, label: "LinkedIn", color: "text-sky-300" },
  STOP: { icon: StopCircle, label: "Stop", color: "text-rose-300" },
};

interface Props {
  node: Node<NodeData>;
  onClose: () => void;
  onConfigChange: (nodeId: string, config: NodeConfig) => void;
}

export default function NodeConfigDrawer({ node, onClose, onConfigChange }: Props) {
  const nodeType = (node.type ?? "").toUpperCase();
  const meta = NODE_META[nodeType];
  const Icon = meta?.icon ?? Mail;

  const config = (node.data.config ?? DEFAULTS[nodeType] ?? {}) as NodeConfig;

  function handleChange(next: NodeConfig) {
    onConfigChange(node.id, next);
  }

  return (
    <div className="w-80 shrink-0 flex flex-col border-l border-white/[0.07] bg-[#0d0d14] overflow-hidden animate-in slide-in-from-right-4 duration-200">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.07] shrink-0">
        <Icon size={14} className={meta?.color ?? "text-white/60"} />
        <span className="text-[12px] font-bold uppercase tracking-widest text-white/80 flex-1">
          {meta?.label ?? nodeType} Config
        </span>
        <button
          onClick={onClose}
          className="text-white/30 hover:text-white/70 transition-colors p-0.5 rounded"
          aria-label="Close config panel"
        >
          <X size={14} />
        </button>
      </div>

      {/* Node label */}
      <div className="px-4 py-2 border-b border-white/[0.05] shrink-0">
        <p className="text-white/40 text-[11px]">
          <span className="text-white/20">ID: </span>
          <span className="font-mono">{node.id}</span>
        </p>
      </div>

      {/* Config body */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {nodeType === "EMAIL" && (
          <EmailConfigPanel
            config={config as EmailConfig}
            onChange={handleChange}
          />
        )}
        {nodeType === "CALL" && (
          <CallConfigPanel
            config={config as CallConfig}
            onChange={handleChange}
          />
        )}
        {nodeType === "WAIT" && (
          <WaitConfigPanel
            config={config as WaitConfig}
            onChange={handleChange}
          />
        )}
        {nodeType === "CONDITION" && (
          <ConditionConfigPanel
            config={config as ConditionConfig}
            onChange={handleChange}
          />
        )}
        {nodeType === "LINKEDIN" && (
          <LinkedinConfigPanel
            config={config as LinkedinConfig}
            onChange={handleChange}
          />
        )}
        {nodeType === "STOP" && <StopConfigPanel />}
      </div>

      {/* Footer hint */}
      <div className="px-4 py-3 border-t border-white/[0.05] shrink-0">
        <p className="text-white/25 text-[11px]">
          Changes apply instantly. Use Save to persist to backend.
        </p>
      </div>
    </div>
  );
}
