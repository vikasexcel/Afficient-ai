import { Handle, Position, type NodeProps } from "@xyflow/react";
import { StopCircle } from "lucide-react";
import BaseNode from "./BaseNode";
import type { NodeData } from "@/types/workflow";

export default function StopNode({ data, selected }: NodeProps<NodeData>) {
  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-rose-400 !border-rose-600" />
      <BaseNode
        header={
          <>
            <StopCircle size={13} className="text-rose-300" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-rose-200">
              Stop
            </span>
          </>
        }
        headerClass="bg-rose-950/70 border-b border-rose-800/60"
        borderClass="border-rose-700/60"
        label={data.label as string | undefined}
        selected={selected}
      />
      {/* No source handle — STOP is a terminal node */}
    </>
  );
}
