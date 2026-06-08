import type { MonitorExecution } from "@/types/monitor";
import { parseUtcDate } from "@/lib/utils";

function formatNext(iso: string | null) {
  if (!iso) return "—";
  const d = parseUtcDate(iso);
  const diff = d.getTime() - Date.now();
  if (diff <= 0) return "due now";
  const m = Math.floor(diff / 60000);
  if (m < 60) return `in ${m}m`;
  return `in ${Math.floor(m / 60)}h ${m % 60}m`;
}

interface Props {
  executions: MonitorExecution[];
  nodeTypeMap: Record<string, string>;
  onSelect: (ex: MonitorExecution) => void;
}

export default function RetryMonitor({ executions, nodeTypeMap, onSelect }: Props) {
  const retrying = executions.filter((ex) => ex.retry_status && ex.retry_status !== "completed");

  if (retrying.length === 0) return null;

  return (
    <div className="rounded-xl border border-amber-800/30 bg-amber-900/5 overflow-hidden">
      <div className="px-4 py-3 border-b border-amber-800/20">
        <h3 className="text-[12px] font-semibold text-amber-400/80 uppercase tracking-widest">
          Retry Queue ({retrying.length})
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-amber-800/10 text-amber-400/40 text-[10px] uppercase tracking-widest">
              <th className="px-4 py-2 text-left font-medium">Lead</th>
              <th className="px-4 py-2 text-left font-medium">Node</th>
              <th className="px-4 py-2 text-left font-medium">Attempt</th>
              <th className="px-4 py-2 text-left font-medium">Next Retry</th>
              <th className="px-4 py-2 text-left font-medium">Status</th>
              <th className="px-4 py-2 text-left font-medium hidden md:table-cell">Reason</th>
            </tr>
          </thead>
          <tbody>
            {retrying.map((ex) => {
              const nodeType = ex.current_node_id ? (nodeTypeMap[ex.current_node_id] ?? "—") : "—";
              return (
                <tr
                  key={ex.id}
                  onClick={() => onSelect(ex)}
                  className="border-b border-amber-800/[0.07] hover:bg-amber-900/10 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3">
                    <p className="text-white/75">{ex.lead_name ?? "—"}</p>
                    <p className="text-white/30 text-[11px]">{ex.lead_email ?? ""}</p>
                  </td>
                  <td className="px-4 py-3 font-mono text-amber-400/70">{nodeType}</td>
                  <td className="px-4 py-3 text-white/50">#{ex.attempt_number}</td>
                  <td className="px-4 py-3 text-amber-400/70">{formatNext(ex.next_retry_at)}</td>
                  <td className="px-4 py-3 text-white/40 capitalize">{ex.retry_status}</td>
                  <td className="px-4 py-3 text-white/30 hidden md:table-cell max-w-xs truncate">
                    {ex.last_failure_reason ?? "—"}
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
