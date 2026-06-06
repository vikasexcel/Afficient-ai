import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Briefcase } from "lucide-react";
import BaseNode from "./BaseNode";
import type { NodeData } from "@/types/workflow";

export default function LinkedinNode({ data, selected }: NodeProps<NodeData>) {
  const action = data.action as string | undefined;

  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-sky-400 !border-sky-600" />
      <BaseNode
        header={
          <>
            <Briefcase size={13} className="text-sky-300" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-sky-200">
              LinkedIn
            </span>
          </>
        }
        headerClass="bg-sky-950/70 border-b border-sky-800/60"
        borderClass="border-sky-700/60"
        label={data.label as string | undefined}
        selected={selected}
      >
        {action && (
          <p className="text-[11px] text-sky-400/70 font-mono uppercase">{action}</p>
        )}
      </BaseNode>
      <Handle type="source" position={Position.Bottom} className="!bg-sky-400 !border-sky-600" />
    </>
  );
}
