import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Mail } from "lucide-react";
import BaseNode from "./BaseNode";
import type { NodeData } from "@/types/workflow";

export default function EmailNode({ data, selected }: NodeProps<NodeData>) {
  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-violet-400 !border-violet-600" />
      <BaseNode
        header={
          <>
            <Mail size={13} className="text-violet-300" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-violet-200">
              Email
            </span>
          </>
        }
        headerClass="bg-violet-950/70 border-b border-violet-800/60"
        borderClass="border-violet-700/60"
        label={data.label as string | undefined}
        selected={selected}
      />
      <Handle type="source" position={Position.Bottom} className="!bg-violet-400 !border-violet-600" />
    </>
  );
}
