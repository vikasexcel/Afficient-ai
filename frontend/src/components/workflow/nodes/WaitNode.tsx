import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Clock } from "lucide-react";
import BaseNode from "./BaseNode";
import type { NodeData, WaitConfig } from "@/types/workflow";

export default function WaitNode({ data, selected }: NodeProps<NodeData>) {
  // Read from data.config first (live updates), fall back to legacy flat fields.
  const cfg = data.config as WaitConfig | undefined;
  const duration = cfg?.duration ?? (data.duration as number | undefined);
  const unit = cfg?.unit ?? (data.unit as string | undefined);
  const sublabel =
    duration && unit ? `${duration} ${unit}` : undefined;

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-amber-400 !border-amber-600" />
      <BaseNode
        header={
          <>
            <Clock size={13} className="text-amber-300" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-amber-200">
              Wait
            </span>
          </>
        }
        headerClass="bg-amber-950/70 border-b border-amber-800/60"
        borderClass="border-amber-700/60"
        label={data.label as string | undefined}
        selected={selected}
      >
        {sublabel && (
          <p className="text-[11px] text-amber-400/70 font-mono">{sublabel}</p>
        )}
      </BaseNode>
      <Handle type="source" position={Position.Bottom} className="!bg-amber-400 !border-amber-600" />
    </>
  );
}
