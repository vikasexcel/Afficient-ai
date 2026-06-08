import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import type { MonitorExecution } from "@/types/monitor";
import { parseUtcDate } from "@/lib/utils";

const STATUS_TABS = ["all", "queued", "running", "completed", "failed"] as const;
type StatusTab = typeof STATUS_TABS[number];

const STATUS_BADGE: Record<string, string> = {
  queued:    "bg-sky-500/10 text-sky-300 border-sky-500/20",
  running:   "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
  completed: "bg-violet-500/10 text-violet-300 border-violet-500/20",
  failed:    "bg-rose-500/10 text-rose-300 border-rose-500/20",
};

const NODE_COLORS: Record<string, string> = {
  EMAIL: "text-violet-400", CALL: "text-indigo-400", WAIT: "text-amber-400",
  CONDITION: "text-yellow-400", LINKEDIN: "text-sky-400", STOP: "text-rose-400",
};

function timeAgo(iso: string) {
  const s = Math.floor((Date.now() - parseUtcDate(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

interface Props {
  executions: MonitorExecution[];
  nodeTypeMap: Record<string, string>;
  onSelect: (ex: MonitorExecution) => void;
}

export default function LeadExecutionTable({ executions, nodeTypeMap, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<StatusTab>("all");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return executions.filter((ex) => {
      if (tab !== "all" && ex.status !== tab) return false;
      if (!q) return true;
      return (
        (ex.lead_name ?? "").toLowerCase().includes(q) ||
        (ex.lead_email ?? "").toLowerCase().includes(q)
      );
    });
  }, [executions, tab, query]);

  return (
    <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-white/[0.06]">
        <h3 className="text-[12px] font-semibold text-white/50 uppercase tracking-widest">
          Executions
          <span className="ml-2 text-white/30 font-normal">({filtered.length})</span>
        </h3>
        <div className="relative ml-auto w-52">
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name or email…"
            className="pl-8 bg-white/5 border-white/10 text-white placeholder:text-white/20 text-[12px] h-7"
          />
        </div>
      </div>

      {/* Status tabs */}
      <div className="flex gap-1 px-4 py-2 border-b border-white/[0.04]">
        {STATUS_TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1 rounded text-[11px] font-medium capitalize transition-colors ${
              tab === t
                ? "bg-violet-600/30 text-violet-300 border border-violet-600/40"
                : "text-white/35 hover:text-white/60"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-white/[0.05] text-white/30 text-[10px] uppercase tracking-widest">
              <th className="px-4 py-2.5 text-left font-medium">Lead</th>
              <th className="px-4 py-2.5 text-left font-medium">Status</th>
              <th className="px-4 py-2.5 text-left font-medium">Node</th>
              <th className="px-4 py-2.5 text-left font-medium hidden md:table-cell">Attempt</th>
              <th className="px-4 py-2.5 text-left font-medium hidden lg:table-cell">Retry</th>
              <th className="px-4 py-2.5 text-left font-medium hidden lg:table-cell">Updated</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-white/25">
                  No executions match your search.
                </td>
              </tr>
            )}
            {filtered.map((ex) => {
              const nodeType = ex.current_node_id ? (nodeTypeMap[ex.current_node_id] ?? "—") : "—";
              const nodeColor = NODE_COLORS[nodeType] ?? "text-white/40";
              const badgeCls = STATUS_BADGE[ex.status] ?? "bg-white/5 text-white/40 border-white/10";
              return (
                <tr
                  key={ex.id}
                  onClick={() => onSelect(ex)}
                  className="border-b border-white/[0.04] hover:bg-white/[0.03] cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3">
                    <p className="text-white/80 font-medium">{ex.lead_name ?? "—"}</p>
                    <p className="text-white/30 text-[11px]">{ex.lead_email ?? ""}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-[10px] px-2 py-0.5 rounded border capitalize ${badgeCls}`}>
                      {ex.status}
                    </span>
                  </td>
                  <td className={`px-4 py-3 font-mono text-[11px] ${nodeColor}`}>{nodeType}</td>
                  <td className="px-4 py-3 text-white/40 hidden md:table-cell">#{ex.attempt_number}</td>
                  <td className="px-4 py-3 text-white/35 hidden lg:table-cell capitalize">
                    {ex.retry_status ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-white/25 hidden lg:table-cell">
                    {timeAgo(ex.updated_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
