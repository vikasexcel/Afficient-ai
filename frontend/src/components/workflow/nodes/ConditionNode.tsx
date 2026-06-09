/**
 * CONDITION node — two source handles (TRUE / FALSE).
 *
 * When a user drags from the TRUE handle, the resulting edge gets
 * sourceHandle="TRUE"; when from FALSE, sourceHandle="FALSE".
 * The WorkflowCanvas.onConnect handler copies this into the edge label.
 */
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { GitBranch } from "lucide-react";
import BaseNode from "./BaseNode";
import type { NodeData, ConditionConfig } from "@/types/workflow";

const CONDITION_LABELS: Record<string, string> = {
  EMAIL_SENT: "Email sent?",
  EMAIL_FAILED: "Email failed?",
  EMAIL_REPLIED: "Replied within window?",
  NEGATIVE_REPLY: "Negative / opt-out reply?",
  CALL_COMPLETED: "Call completed?",
  CALL_FAILED: "Call failed?",
};

export default function ConditionNode({ data, selected }: NodeProps<NodeData>) {
  const cfg = data.config as ConditionConfig | undefined;
  const conditionLabel = cfg?.condition_type ? CONDITION_LABELS[cfg.condition_type] : undefined;

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-yellow-400 !border-yellow-600" />
      <BaseNode
        header={
          <>
            <GitBranch size={13} className="text-yellow-300" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-yellow-200">
              Condition
            </span>
          </>
        }
        headerClass="bg-yellow-950/60 border-b border-yellow-800/50"
        borderClass="border-yellow-700/60"
        label={data.label as string | undefined}
        selected={selected}
      >
        {conditionLabel && (
          <p className="text-[10px] text-yellow-400/70 font-mono mb-1">{conditionLabel}</p>
        )}
        {/* Two labelled source handles side by side */}
        <div className="flex justify-between mt-1 text-[10px] text-white/40 font-mono">
          <span>TRUE</span>
          <span>FALSE</span>
        </div>
      </BaseNode>

      {/* TRUE branch — left-ish */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="TRUE"
        style={{ left: "30%" }}
        className="!bg-emerald-400 !border-emerald-600"
      />
      {/* FALSE branch — right-ish */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="FALSE"
        style={{ left: "70%" }}
        className="!bg-red-400 !border-red-600"
      />
    </>
  );
}
