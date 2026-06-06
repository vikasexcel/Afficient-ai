/**
 * WorkflowCanvas — the React Flow canvas.
 *
 * Responsibilities:
 *  - Render nodes + edges with custom node types.
 *  - Accept drop events from WorkflowSidebar.
 *  - Expose keyboard-delete for selected nodes/edges.
 *  - Show MiniMap, Controls, and a dotted Background.
 *
 * onConnect / onConnectStart / onConnectEnd are owned by WorkflowBuilderInner
 * (where useEdgesState lives) and passed down as props.  This avoids the
 * StoreUpdater sync delay that occurs when setEdges crosses a component
 * boundary before reaching the ReactFlow controlled-mode pipeline.
 */
import { useCallback } from "react";
import { LayoutTemplate, Plus } from "lucide-react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type Connection,
  type NodeTypes,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnectStart,
  type OnConnectEnd,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import CallNode from "./nodes/CallNode";
import EmailNode from "./nodes/EmailNode";
import WaitNode from "./nodes/WaitNode";
import ConditionNode from "./nodes/ConditionNode";
import LinkedinNode from "./nodes/LinkedinNode";
import StopNode from "./nodes/StopNode";
import type { NodeData } from "@/types/workflow";

// Registered once outside the component to keep the reference stable.
const NODE_TYPES: NodeTypes = {
  CALL: CallNode,
  EMAIL: EmailNode,
  WAIT: WaitNode,
  CONDITION: ConditionNode,
  LINKEDIN: LinkedinNode,
  STOP: StopNode,
};

interface WorkflowCanvasProps {
  nodes: Node<NodeData>[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  /** Owned by WorkflowBuilderInner — calls setEdges where state lives. */
  onConnect: (params: Connection) => void;
  onConnectStart: OnConnectStart;
  onConnectEnd: OnConnectEnd;
  onNodeClick: (event: React.MouseEvent, node: Node<NodeData>) => void;
  onPaneClick?: () => void;
  onDrop: (event: React.DragEvent<HTMLDivElement>) => void;
  onOpenTemplates?: () => void;
  isLoading?: boolean;
}

export default function WorkflowCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onConnectStart,
  onConnectEnd,
  onNodeClick,
  onPaneClick,
  onDrop,
  onOpenTemplates,
  isLoading = false,
}: WorkflowCanvasProps) {
  const onDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#0a0a0f]">
        <div className="flex flex-col items-center gap-3 text-white/40">
          <div className="h-8 w-8 rounded-full border-2 border-white/20 border-t-white/60 animate-spin" />
          <span className="text-sm">Loading workflow…</span>
        </div>
      </div>
    );
  }

  const isEmpty = !isLoading && nodes.length === 0;

  return (
    <div className="flex-1 relative" onDrop={onDrop} onDragOver={onDragOver}>
      {/* Empty canvas CTA — shown only when there are no nodes yet */}
      {isEmpty && (
        <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
          <div className="flex flex-col items-center gap-5 pointer-events-auto">
            <p className="text-white/30 text-sm">Start building your workflow</p>
            <div className="flex gap-3">
              <button
                onClick={() => {/* Drag nodes from sidebar */}}
                className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-white/[0.10] bg-white/[0.04] hover:bg-white/[0.08] text-white/60 hover:text-white text-[13px] transition-all"
              >
                <Plus size={14} />
                Start Blank
              </button>
              {onOpenTemplates && (
                <button
                  onClick={onOpenTemplates}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-violet-700/50 bg-violet-900/30 hover:bg-violet-900/50 text-violet-300 hover:text-violet-200 text-[13px] transition-all"
                >
                  <LayoutTemplate size={14} />
                  Use Template
                </button>
              )}
            </div>
            <p className="text-white/20 text-xs">or drag a node from the left panel</p>
          </div>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onConnectStart={onConnectStart}
        onConnectEnd={onConnectEnd}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={NODE_TYPES}
        deleteKeyCode={["Backspace", "Delete"]}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
        defaultEdgeOptions={{ type: "smoothstep" }}
        connectionRadius={30}
        colorMode="dark"
        className="bg-[#0a0a0f]"
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1.2}
          color="#ffffff18"
        />
        <Controls
          className="!bg-[#18181f] !border-white/10 !shadow-xl [&_button]:!bg-[#18181f] [&_button]:!border-white/10 [&_button]:!text-white/60 [&_button:hover]:!bg-white/10"
        />
        <MiniMap
          nodeColor={(n) => {
            const type = n.type ?? "";
            const map: Record<string, string> = {
              CALL: "#6366f1",
              EMAIL: "#8b5cf6",
              WAIT: "#f59e0b",
              CONDITION: "#eab308",
              LINKEDIN: "#0ea5e9",
              STOP: "#f43f5e",
            };
            return map[type] ?? "#6b7280";
          }}
          className="!bg-[#18181f] !border-white/10"
          maskColor="#00000088"
        />
      </ReactFlow>
    </div>
  );
}
