import { useState, useMemo } from "react";
import { Search, Loader2, AlertCircle } from "lucide-react";
import { Input } from "@/components/ui/input";
import type { WorkflowTemplate } from "@/types/workflow";
import TemplateCard from "./TemplateCard";

const TABS = ["All", "Cold Outreach", "Follow-Up", "LinkedIn", "Qualification", "Demo Booking"];

function normalise(s: string) {
  return s.toLowerCase().replace(/[-_\s]+/g, " ").trim();
}

function categoryMatches(template: WorkflowTemplate, tab: string) {
  if (tab === "All") return true;
  const cat = normalise(template.category ?? "");
  return cat === normalise(tab);
}

interface Props {
  templates: WorkflowTemplate[];
  loading: boolean;
  error: string | null;
  onSelect: (template: WorkflowTemplate) => void;
}

export default function TemplateGallery({ templates, loading, error, onSelect }: Props) {
  const [activeTab, setActiveTab] = useState("All");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return templates.filter((t) => {
      if (!categoryMatches(t, activeTab)) return false;
      if (!q) return true;
      return (
        t.name.toLowerCase().includes(q) ||
        (t.description ?? "").toLowerCase().includes(q)
      );
    });
  }, [templates, activeTab, query]);

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Search */}
      <div className="relative shrink-0">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search templates…"
          className="pl-8 bg-white/5 border-white/10 text-white placeholder:text-white/25 text-sm"
        />
      </div>

      {/* Category tabs */}
      <div className="flex gap-1 flex-wrap shrink-0">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1 rounded text-[11px] font-medium transition-colors ${
              activeTab === tab
                ? "bg-violet-600 text-white"
                : "text-white/40 hover:text-white/70 hover:bg-white/5"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center h-40 gap-2 text-white/40">
            <Loader2 size={16} className="animate-spin" />
            <span className="text-sm">Loading templates…</span>
          </div>
        )}

        {!loading && error && (
          <div className="flex items-center justify-center h-40 gap-2 text-rose-400/70">
            <AlertCircle size={16} />
            <span className="text-sm">{error}</span>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="flex items-center justify-center h-40 text-white/30 text-sm">
            No templates match your search.
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pb-4">
            {filtered.map((t) => (
              <TemplateCard key={t.id} template={t} onClick={() => onSelect(t)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
