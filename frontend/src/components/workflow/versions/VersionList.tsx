import { useState, useMemo } from "react";
import { Search, Loader2, AlertCircle, Clock } from "lucide-react";
import { Input } from "@/components/ui/input";
import type { WorkflowVersionSummary } from "@/types/workflow";
import VersionCard from "./VersionCard";

interface Props {
  versions: WorkflowVersionSummary[];
  loading: boolean;
  error: string | null;
  currentVersion?: number;
  onSelect: (version: WorkflowVersionSummary) => void;
}

export default function VersionList({
  versions,
  loading,
  error,
  currentVersion,
  onSelect,
}: Props) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return versions;
    return versions.filter(
      (v) =>
        String(v.version).includes(q) ||
        (v.created_by ?? "").toLowerCase().includes(q)
    );
  }, [versions, query]);

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="px-4 py-3 border-b border-white/[0.06] shrink-0">
        <div className="relative">
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by version or author…"
            className="pl-8 bg-white/5 border-white/10 text-white placeholder:text-white/25 text-[12px] h-8"
          />
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center h-32 gap-2 text-white/35">
            <Loader2 size={14} className="animate-spin" />
            <span className="text-[12px]">Loading history…</span>
          </div>
        )}

        {!loading && error && (
          <div className="flex items-center justify-center h-32 gap-2 text-rose-400/70">
            <AlertCircle size={14} />
            <span className="text-[12px]">{error}</span>
          </div>
        )}

        {!loading && !error && versions.length === 0 && (
          <div className="flex flex-col items-center justify-center h-40 gap-2 text-white/25 px-6 text-center">
            <Clock size={22} className="text-white/15" />
            <p className="text-[12px]">No versions available.</p>
            <p className="text-[11px] text-white/20">
              Versions are created automatically after each workflow save.
            </p>
          </div>
        )}

        {!loading && !error && versions.length > 0 && filtered.length === 0 && (
          <div className="flex items-center justify-center h-24 text-white/25 text-[12px]">
            No versions match your search.
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <div>
            {filtered.map((v) => (
              <VersionCard
                key={v.version}
                version={v}
                isCurrent={v.version === currentVersion}
                onClick={() => onSelect(v)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
