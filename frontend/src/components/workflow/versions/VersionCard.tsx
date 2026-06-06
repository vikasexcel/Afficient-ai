import { GitCommitHorizontal } from "lucide-react";
import type { WorkflowVersionSummary } from "@/types/workflow";

/** Format an ISO date string as a human-readable relative time. */
export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} minute${m !== 1 ? "s" : ""} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h !== 1 ? "s" : ""} ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d} day${d !== 1 ? "s" : ""} ago`;
  const mo = Math.floor(d / 30);
  return `${mo} month${mo !== 1 ? "s" : ""} ago`;
}

function shortId(uuid: string | null): string {
  if (!uuid) return "System";
  return uuid.slice(0, 8);
}

interface Props {
  version: WorkflowVersionSummary;
  isCurrent?: boolean;
  onClick: () => void;
}

export default function VersionCard({ version, isCurrent, onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className="group w-full text-left flex items-start gap-3 px-4 py-3 border-b border-white/[0.05] hover:bg-white/[0.04] transition-colors"
    >
      {/* Timeline dot */}
      <div className="flex flex-col items-center gap-1 pt-0.5 shrink-0">
        <div
          className={`w-2 h-2 rounded-full mt-1 ${
            isCurrent ? "bg-violet-400" : "bg-white/20 group-hover:bg-white/40"
          }`}
        />
        <div className="w-px flex-1 bg-white/[0.06]" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-[12px] font-semibold text-white/80">
            <GitCommitHorizontal size={11} className="text-white/30 shrink-0" />
            Version {version.version}
          </span>
          {isCurrent && (
            <span className="text-[9px] px-1.5 py-0.5 rounded border border-violet-700/40 bg-violet-900/30 text-violet-400 uppercase tracking-widest">
              Current
            </span>
          )}
        </div>
        <p className="text-[11px] text-white/35 mt-0.5">{timeAgo(version.created_at)}</p>
        <p className="text-[10px] text-white/25 font-mono mt-0.5">
          By {shortId(version.created_by)}
        </p>
      </div>

      {/* Hover arrow */}
      <span className="text-white/20 group-hover:text-white/50 text-xs self-center">›</span>
    </button>
  );
}
