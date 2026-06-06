import { useEffect, useState } from "react";
import { Check, Loader2, Users, AlertCircle } from "lucide-react";
import { listLeadLists, type LeadList } from "@/services/leadList";
import type { WizardDraft } from "../types";

interface Props {
  draft: WizardDraft;
  onChange: (partial: Partial<WizardDraft>) => void;
}

export default function LeadListStep({ draft, onChange }: Props) {
  const [lists, setLists] = useState<LeadList[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listLeadLists()
      .then(setLists)
      .catch(() => setError("Failed to load lead lists."))
      .finally(() => setLoading(false));
  }, []);

  function select(list: LeadList) {
    onChange({
      lead_list_id: list.id,
      lead_list_name: list.name,
      lead_count: null, // LeadList type does not expose lead_count
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-base font-semibold text-white">Select Lead List</h2>
        <p className="text-[13px] text-white/40 mt-0.5">
          Choose the list of contacts this campaign will reach out to.
        </p>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-white/40 py-8 justify-center">
          <Loader2 size={16} className="animate-spin" />
          <span className="text-sm">Loading lead lists…</span>
        </div>
      )}

      {!loading && error && (
        <div className="flex items-center gap-2 text-rose-400/70 py-8 justify-center">
          <AlertCircle size={16} />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {!loading && !error && lists.length === 0 && (
        <div className="flex flex-col items-center py-12 text-center gap-2 text-white/30">
          <Users size={28} className="text-white/15 mb-1" />
          <p className="text-sm">No lead lists found.</p>
          <p className="text-xs">Upload a lead list from the Leads page first.</p>
        </div>
      )}

      {!loading && !error && lists.length > 0 && (
        <div className="flex flex-col gap-2">
          {lists.map((list) => {
            const selected = draft.lead_list_id === list.id;
            return (
              <button
                key={list.id}
                onClick={() => select(list)}
                className={`w-full text-left flex items-center gap-3 px-4 py-3 rounded-lg border transition-all ${
                  selected
                    ? "border-violet-600/60 bg-violet-900/20"
                    : "border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:border-white/[0.15]"
                }`}
              >
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                  selected ? "bg-violet-600/30" : "bg-white/5"
                }`}>
                  <Users size={14} className={selected ? "text-violet-300" : "text-white/40"} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`text-[13px] font-medium ${selected ? "text-white" : "text-white/80"}`}>
                    {list.name}
                  </p>
                  {list.description && (
                    <p className="text-[11px] text-white/35 truncate">{list.description}</p>
                  )}
                </div>
                {selected && <Check size={16} className="text-violet-400 shrink-0" />}
              </button>
            );
          })}
        </div>
      )}

      {!draft.lead_list_id && !loading && lists.length > 0 && (
        <p className="text-[11px] text-amber-400/60">Select a lead list to continue.</p>
      )}
    </div>
  );
}
