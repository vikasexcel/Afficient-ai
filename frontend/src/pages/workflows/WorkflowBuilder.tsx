/**
 * WorkflowBuilder — full-screen page for visually editing a campaign workflow.
 *
 * Layout:
 *   ┌───────────────────────────────────────────────────────┐
 *   │  ← Back  │  Campaign / Workflow Builder  │  Validate Save  │
 *   ├──────────┼────────────────────────────────────────────┤
 *   │ Sidebar  │                                            │
 *   │ (palette)│              React Flow Canvas             │
 *   │          │                                            │
 *   └──────────┴────────────────────────────────────────────┘
 *
 * Phase 4A scope: canvas only — no node config panels, no templates,
 * no version history UI.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
  addEdge,
  type Node,
  type Edge,
  type Connection,
} from "@xyflow/react";
import NodeConfigDrawer from "@/components/workflow/config/NodeConfigDrawer";
import TemplateSelector from "@/components/workflow/templates/TemplateSelector";
import VersionHistoryDrawer from "@/components/workflow/versions/VersionHistoryDrawer";
import type { NodeConfig, WorkflowTemplate, WorkflowRestoreResponse } from "@/types/workflow";
import { ArrowLeft } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import WorkflowCanvas from "@/components/workflow/WorkflowCanvas";
import WorkflowSidebar from "@/components/workflow/WorkflowSidebar";
import WorkflowToolbar, {
  ValidationPanel,
} from "@/components/workflow/WorkflowToolbar";
import { getWorkflow, saveWorkflow, validateWorkflow } from "@/services/workflow";
import { getCampaign } from "@/services/campaign";
import type { NodeData, WorkflowValidationResponse } from "@/types/workflow";

// ---------------------------------------------------------------------------
// Graph conversion helpers
// ---------------------------------------------------------------------------

/** Assign top-to-bottom tree positions when nodes have no saved position. */
function autoLayout(
  nodes: Array<{ id: string }>,
  edges: Array<{ source: string; target: string }>
): Record<string, { x: number; y: number }> {
  const inbound: Record<string, number> = {};
  edges.forEach((e) => {
    inbound[e.target] = (inbound[e.target] ?? 0) + 1;
  });

  // BFS from entry nodes (nodes with no inbound edges).
  const levels: Record<string, number> = {};
  const queue: Array<{ id: string; level: number }> = nodes
    .filter((n) => !inbound[n.id])
    .map((n) => ({ id: n.id, level: 0 }));

  if (!queue.length && nodes.length) {
    // Fallback: all nodes at level 0 (cycle detected or no entry).
    nodes.forEach((n) => (levels[n.id] = 0));
  }

  while (queue.length) {
    const { id, level } = queue.shift()!;
    if (id in levels) continue;
    levels[id] = level;
    edges
      .filter((e) => e.source === id)
      .forEach((e) => queue.push({ id: e.target, level: level + 1 }));
  }

  // Nodes not visited (orphans) fall back to level 0.
  nodes.forEach((n) => {
    if (!(n.id in levels)) levels[n.id] = 0;
  });

  const perLevel: Record<number, string[]> = {};
  nodes.forEach((n) => {
    const l = levels[n.id];
    (perLevel[l] ??= []).push(n.id);
  });

  const positions: Record<string, { x: number; y: number }> = {};
  Object.entries(perLevel).forEach(([lvl, ids]) => {
    const l = Number(lvl);
    ids.forEach((id, i) => {
      positions[id] = {
        x: (i - (ids.length - 1) / 2) * 260,
        y: l * 190 + 60,
      };
    });
  });

  return positions;
}

function backendToFlow(
  backendNodes: Array<Record<string, unknown>>,
  backendEdges: Array<Record<string, unknown>>
): { nodes: Node<NodeData>[]; edges: Edge[] } {
  // Assign auto-layout positions when nodes have none saved.
  const hasPositions = backendNodes.some((n) => n.position);
  const positions = hasPositions
    ? {}
    : autoLayout(
        backendNodes.map((n) => ({ id: n.id as string })),
        backendEdges.map((e) => ({
          source: e.source as string,
          target: e.target as string,
        }))
      );

  const nodes: Node<NodeData>[] = backendNodes.map((n) => ({
    id: n.id as string,
    type: (n.type as string).toUpperCase(),
    position:
      (n.position as { x: number; y: number } | undefined) ??
      positions[n.id as string] ??
      { x: 0, y: 0 },
    data: { ...(n as NodeData) },
  }));

  const edges: Edge[] = backendEdges.map((e) => ({
    id: e.id as string,
    source: e.source as string,
    target: e.target as string,
    sourceHandle:
      (e.condition as string | null | undefined) ?? undefined,
    label: (e.condition as string | null | undefined) ?? undefined,
    type: "smoothstep",
  }));

  return { nodes, edges };
}

function flowToBackend(
  rfNodes: Node<NodeData>[],
  rfEdges: Edge[]
): { nodes: unknown[]; edges: unknown[] } {
  const nodes = rfNodes.map((n) => ({
    ...n.data,
    id: n.id,
    type: n.type,          // already UPPERCASE
    position: n.position,  // persist position for next load
  }));

  const edges = rfEdges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    condition:
      (e.label as string | undefined) ??
      (e.sourceHandle ?? null),
  }));

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Inner component — must live inside ReactFlowProvider to use useReactFlow()
// ---------------------------------------------------------------------------

function WorkflowBuilderInner({ campaignId }: { campaignId: string }) {
  const navigate = useNavigate();
  const { screenToFlowPosition } = useReactFlow();

  const [nodes, setNodes, onNodesChange] = useNodesState<NodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<WorkflowValidationResponse | null>(null);
  const [campaignName, setCampaignName] = useState<string | undefined>();
  const [selectedNode, setSelectedNode] = useState<Node<NodeData> | null>(null);
  const [templateSelectorOpen, setTemplateSelectorOpen] = useState(false);
  const [historyDrawerOpen, setHistoryDrawerOpen] = useState(false);

  // Track the last-saved snapshot to detect unsaved changes.
  const savedSnapshotRef = useRef<string>("");
  const currentSnapshot = JSON.stringify({ nodes, edges });
  const hasUnsavedChanges =
    !loading && currentSnapshot !== savedSnapshotRef.current;

  // ── Load workflow ──────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        // Fetch campaign name (best-effort, non-blocking).
        getCampaign(campaignId)
          .then((c) => { if (!cancelled) setCampaignName(c.name); })
          .catch(() => {});

        // Fetch workflow (404 → empty canvas is fine).
        try {
          const wf = await getWorkflow(campaignId);
          if (cancelled) return;
          if (wf.nodes?.length) {
            const { nodes: rfNodes, edges: rfEdges } = backendToFlow(
              wf.nodes as Array<Record<string, unknown>>,
              wf.edges as Array<Record<string, unknown>>
            );
            setNodes(rfNodes);
            setEdges(rfEdges);
            savedSnapshotRef.current = JSON.stringify({ nodes: rfNodes, edges: rfEdges });
          } else {
            savedSnapshotRef.current = JSON.stringify({ nodes: [], edges: [] });
          }
        } catch (err: unknown) {
          const status = (err as { response?: { status?: number } }).response?.status;
          if (status !== 404) {
            toast.error("Failed to load workflow");
          }
          // 404 → empty canvas (workflow not yet created).
          savedSnapshotRef.current = JSON.stringify({ nodes: [], edges: [] });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => { cancelled = true; };
  }, [campaignId, setNodes, setEdges]);

  // ── Save ───────────────────────────────────────────────────────────────────
  const handleSave = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    try {
      const { nodes: bNodes, edges: bEdges } = flowToBackend(nodes, edges);
      await saveWorkflow(campaignId, {
        nodes: bNodes as never,
        edges: bEdges as never,
      });
      savedSnapshotRef.current = JSON.stringify({ nodes, edges });
      toast.success("Workflow saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [campaignId, nodes, edges, saving]);

  // ── Validate ───────────────────────────────────────────────────────────────
  const handleValidate = useCallback(async () => {
    if (validating) return;
    setValidating(true);
    try {
      const { nodes: bNodes, edges: bEdges } = flowToBackend(nodes, edges);
      const result = await validateWorkflow(campaignId, {
        nodes: bNodes as never,
        edges: bEdges as never,
      });
      setValidation(result);
      if (result.valid) {
        toast.success("Workflow is valid");
      } else {
        toast.error(`${result.errors.length} validation error(s)`);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Validation failed");
    } finally {
      setValidating(false);
    }
  }, [campaignId, nodes, edges, validating]);

  // ── Node selection / config ────────────────────────────────────────────────
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node<NodeData>) => {
      setSelectedNode(node);
    },
    []
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  const onNodeConfigChange = useCallback(
    (nodeId: string, config: NodeConfig) => {
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id !== nodeId) return n;
          const updated = { ...n, data: { ...n.data, config } };
          // Keep selectedNode in sync so the drawer reflects live changes.
          setSelectedNode(updated);
          return updated;
        })
      );
    },
    [setNodes]
  );

  // ── Template apply ─────────────────────────────────────────────────────────
  const applyTemplate = useCallback(
    (template: WorkflowTemplate) => {
      const { nodes: rfNodes, edges: rfEdges } = backendToFlow(
        template.nodes as Array<Record<string, unknown>>,
        template.edges as Array<Record<string, unknown>>
      );
      setNodes(rfNodes);
      setEdges(rfEdges);
      setSelectedNode(null);
      setValidation(null);
      toast.success(`Template "${template.name}" applied — click Save to persist`);
    },
    [setNodes, setEdges]
  );

  // ── Version restore ────────────────────────────────────────────────────────
  const onVersionRestored = useCallback(
    (response: WorkflowRestoreResponse) => {
      const { nodes: rfNodes, edges: rfEdges } = backendToFlow(
        response.nodes as Array<Record<string, unknown>>,
        response.edges as Array<Record<string, unknown>>
      );
      setNodes(rfNodes);
      setEdges(rfEdges);
      setSelectedNode(null);
      setValidation(null);
      // Mark as saved — the restore already persisted to the DB.
      savedSnapshotRef.current = JSON.stringify({ nodes: rfNodes, edges: rfEdges });
      toast.success(
        `Restored Version ${response.restored_from_version} → new Version ${response.new_version}`
      );
    },
    [setNodes, setEdges]
  );

  // ── Drag-and-drop from sidebar ─────────────────────────────────────────────
  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const type = event.dataTransfer.getData("application/workflow-node-type");
      if (!type) return;

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const id = `${type.toLowerCase()}_${Date.now()}`;
      const newNode: Node<NodeData> = {
        id,
        type: type.toUpperCase(),
        position,
        data: {
          type: type.toUpperCase(),
          label: type.charAt(0) + type.slice(1).toLowerCase(),
        },
      };

      setNodes((nds) => [...nds, newNode]);
      setValidation(null); // invalidate any prior validation result
    },
    [screenToFlowPosition, setNodes]
  );

  // ── Node connections ───────────────────────────────────────────────────────
  const onConnect = useCallback(
    (params: Connection) => {
      const edge: Edge = {
        ...params,
        id: `e-${params.source}-${params.sourceHandle ?? ""}-${params.target}`,
        // Carry the source handle id (TRUE / FALSE) as the edge label so
        // CONDITION branches are visible and saved to the backend.
        label: params.sourceHandle ?? undefined,
        type: "smoothstep",
        animated: false,
      };
      setEdges((eds) => addEdge(edge, eds));
    },
    [setEdges]
  );

  const onConnectStart = useCallback(
    (_: MouseEvent | TouchEvent) => { /* no-op — connection lifecycle */ },
    []
  );

  const onConnectEnd = useCallback(
    (_: MouseEvent | TouchEvent) => { /* no-op — connection lifecycle */ },
    []
  );

  return (
    <div className="flex flex-col h-screen bg-[#0a0a0f] text-white overflow-hidden">
      {/* Top header bar */}
      <div className="flex items-center h-12 shrink-0 border-b border-white/[0.07] bg-[#0d0d14] px-4 gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(-1)}
          className="text-white/50 hover:text-white h-7 px-2 gap-1.5"
        >
          <ArrowLeft size={13} />
          <span className="text-[12px]">Campaigns</span>
        </Button>
        <span className="text-white/20">│</span>
        <WorkflowToolbar
          campaignName={campaignName}
          saving={saving}
          validating={validating}
          validation={validation}
          hasUnsavedChanges={hasUnsavedChanges}
          onSave={handleSave}
          onValidate={handleValidate}
          onOpenTemplates={() => setTemplateSelectorOpen(true)}
          onOpenHistory={() => setHistoryDrawerOpen(true)}
        />
      </div>

      {/* Validation error panel */}
      {validation && (validation.errors.length > 0 || validation.warnings.length > 0) && (
        <ValidationPanel
          validation={validation}
          onDismiss={() => setValidation(null)}
        />
      )}

      {/* Main content: sidebar + canvas + config panel */}
      <div className="flex flex-1 overflow-hidden">
        <WorkflowSidebar />
        <WorkflowCanvas
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onConnectStart={onConnectStart}
          onConnectEnd={onConnectEnd}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onDrop={onDrop}
          onOpenTemplates={() => setTemplateSelectorOpen(true)}
          isLoading={loading}
        />
        {selectedNode && (
          <NodeConfigDrawer
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
            onConfigChange={onNodeConfigChange}
          />
        )}
      </div>

      {/* Template selector dialog */}
      <TemplateSelector
        open={templateSelectorOpen}
        hasExistingNodes={nodes.length > 0}
        onClose={() => setTemplateSelectorOpen(false)}
        onApply={applyTemplate}
      />

      {/* Version history drawer */}
      <VersionHistoryDrawer
        open={historyDrawerOpen}
        campaignId={campaignId}
        onClose={() => setHistoryDrawerOpen(false)}
        onRestored={onVersionRestored}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page export — wraps in ReactFlowProvider
// ---------------------------------------------------------------------------

export default function WorkflowBuilder() {
  const { campaignId } = useParams<{ campaignId: string }>();

  if (!campaignId) {
    return (
      <div className="flex h-screen items-center justify-center text-white/50">
        Campaign ID missing
      </div>
    );
  }

  return (
    <ReactFlowProvider>
      <WorkflowBuilderInner campaignId={campaignId} />
    </ReactFlowProvider>
  );
}
