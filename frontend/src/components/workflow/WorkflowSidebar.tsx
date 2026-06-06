/**
 * WorkflowSidebar — left panel with a draggable node palette.
 *
 * Drag any node tile onto the canvas to create a new node of that type.
 * The drag event carries the node type string in the
 * "application/workflow-node-type" data slot.
 */
import {
  Briefcase,
  Clock,
  GitBranch,
  Mail,
  Phone,
  StopCircle,
} from "lucide-react";
import type { ReactNode } from "react";

interface PaletteItem {
  type: string;
  label: string;
  icon: ReactNode;
  colorClass: string; // border + text colour classes (static, no dynamic concat)
}

const COMMUNICATION_NODES: PaletteItem[] = [
  {
    type: "EMAIL",
    label: "Email",
    icon: <Mail size={14} />,
    colorClass: "border-violet-700/60 text-violet-300 hover:bg-violet-950/50",
  },
  {
    type: "CALL",
    label: "Call",
    icon: <Phone size={14} />,
    colorClass: "border-indigo-700/60 text-indigo-300 hover:bg-indigo-950/50",
  },
  {
    type: "LINKEDIN",
    label: "LinkedIn",
    icon: <Briefcase size={14} />,
    colorClass: "border-sky-700/60 text-sky-300 hover:bg-sky-950/50",
  },
];

const LOGIC_NODES: PaletteItem[] = [
  {
    type: "CONDITION",
    label: "Condition",
    icon: <GitBranch size={14} />,
    colorClass: "border-yellow-700/60 text-yellow-300 hover:bg-yellow-950/50",
  },
  {
    type: "WAIT",
    label: "Wait",
    icon: <Clock size={14} />,
    colorClass: "border-amber-700/60 text-amber-300 hover:bg-amber-950/50",
  },
  {
    type: "STOP",
    label: "Stop",
    icon: <StopCircle size={14} />,
    colorClass: "border-rose-700/60 text-rose-300 hover:bg-rose-950/50",
  },
];

function NodeTile({ item }: { item: PaletteItem }) {
  function onDragStart(event: React.DragEvent<HTMLDivElement>) {
    event.dataTransfer.setData("application/workflow-node-type", item.type);
    event.dataTransfer.effectAllowed = "move";
  }

  return (
    <div
      draggable
      onDragStart={onDragStart}
      className={`flex items-center gap-2 rounded-lg border px-3 py-2 cursor-grab active:cursor-grabbing select-none transition-colors text-[12px] font-medium bg-[#12121a] ${item.colorClass}`}
    >
      {item.icon}
      {item.label}
    </div>
  );
}

function SidebarSection({
  title,
  items,
}: {
  title: string;
  items: PaletteItem[];
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-white/30 px-1">
        {title}
      </p>
      {items.map((item) => (
        <NodeTile key={item.type} item={item} />
      ))}
    </div>
  );
}

export default function WorkflowSidebar() {
  return (
    <div className="w-52 shrink-0 border-r border-white/[0.07] bg-[#0d0d14] overflow-y-auto flex flex-col gap-5 px-3 py-4">
      <div>
        <p className="text-[11px] font-semibold text-white/50 mb-3">
          Drag nodes onto the canvas
        </p>
      </div>
      <SidebarSection title="Communication" items={COMMUNICATION_NODES} />
      <SidebarSection title="Logic" items={LOGIC_NODES} />

      <div className="mt-auto pt-4 border-t border-white/[0.05] text-[11px] text-white/25 leading-relaxed">
        <p>Connect nodes by dragging from a handle.</p>
        <p className="mt-1">Select and press Delete to remove.</p>
      </div>
    </div>
  );
}
