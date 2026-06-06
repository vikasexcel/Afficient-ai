import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Phone } from "lucide-react";
import BaseNode from "./BaseNode";
import type { NodeData } from "@/types/workflow";

export default function CallNode({ data, selected }: NodeProps<NodeData>) {
  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-indigo-400 !border-indigo-600" />
      <BaseNode
        header={
          <>
            <Phone size={13} className="text-indigo-300" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-indigo-200">
              Call
            </span>
          </>
        }
        headerClass="bg-indigo-950/70 border-b border-indigo-800/60"
        borderClass="border-indigo-700/60"
        label={data.label as string | undefined}
        selected={selected}
      />
      <Handle type="source" position={Position.Bottom} className="!bg-indigo-400 !border-indigo-600" />
    </>
  );
}
