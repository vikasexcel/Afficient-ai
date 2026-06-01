import { useCallback, useMemo, useState } from "react";
import {
  CalendarClock,
  Clock,
  FileText,
  Megaphone,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import CreateCampaignDialog from "@/components/campaign/CreateCampaignDialog";
import { Button } from "@/components/ui/button";
import { listDrafts, removeDraft, type StoredDraft } from "@/services/campaign";
import { useMe, canUseCampaigns } from "@/store/me";
import { WEEKDAYS, type Weekday } from "@/types/campaign";

export default function Campaigns() {
  const me = useMe((s) => s.data);
  const canCreate = canUseCampaigns(me?.role);

  const [drafts, setDrafts] = useState<StoredDraft[]>(() => listDrafts());

  const refreshDrafts = useCallback(() => {
    setDrafts(listDrafts());
  }, []);

  function handleDelete(id: string) {
    removeDraft(id);
    toast.success("Draft removed");
    refreshDrafts();
  }

  return (
    <AppLayout>
      <div className="max-w-6xl space-y-6">
        <div className="flex justify-between items-start gap-4">
          <div>
            <h1 className="text-2xl font-medium text-white">Campaigns</h1>
            <p className="text-[13px] text-white/40 mt-1">
              {canCreate
                ? "Configure AI outbound campaigns, schedule them, and launch when ready"
                : "View-only access — contact an admin to create campaigns"}
            </p>
          </div>

          {canCreate && (
            <CreateCampaignDialog
              onCreated={refreshDrafts}
              onDraftSaved={refreshDrafts}
            />
          )}
        </div>

        {drafts.length === 0 ? (
          <EmptyState canCreate={canCreate} />
        ) : (
          <DraftsList drafts={drafts} onDelete={handleDelete} />
        )}
      </div>
    </AppLayout>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] py-16 flex flex-col items-center text-center">
      <div className="h-11 w-11 rounded-full bg-violet-500/10 border border-violet-500/20 flex items-center justify-center mb-3">
        <Megaphone size={18} className="text-violet-300" />
      </div>
      <div className="text-[14px] text-white font-medium">
        No campaigns yet
      </div>
      <p className="text-[12px] text-white/45 mt-1 max-w-sm">
        {canCreate
          ? "Create your first campaign to assign a playbook, pick a lead list, and start dialing."
          : "Once an admin creates a campaign it'll show up here."}
      </p>
    </div>
  );
}

function DraftsList({
  drafts,
  onDelete,
}: {
  drafts: StoredDraft[];
  onDelete: (id: string) => void;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <FileText size={13} className="text-white/45" />
        <h2 className="text-[12px] font-medium text-white/55 uppercase tracking-wider">
          Drafts · {drafts.length}
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {drafts.map((draft) => (
          <DraftCard key={draft.id} draft={draft} onDelete={onDelete} />
        ))}
      </div>
    </section>
  );
}

function DraftCard({
  draft,
  onDelete,
}: {
  draft: StoredDraft;
  onDelete: (id: string) => void;
}) {
  const scheduleLabel = useMemo(() => {
    const { schedule } = draft.data;
    if (schedule.start_immediately) return "Starts immediately";
    if (!schedule.date || !schedule.time) return "No start time set";
    return `${schedule.date} · ${schedule.time} (${schedule.timezone})`;
  }, [draft]);

  const hoursLabel = useMemo(() => {
    const bh = draft.data.business_hours;
    const order: Weekday[] = WEEKDAYS.map((w) => w.id);
    const sorted = order.filter((d) => bh.days.includes(d));
    const days = sorted
      .map((d) => WEEKDAYS.find((w) => w.id === d)?.short ?? d)
      .join(", ");
    return `${days || "No days"} · ${bh.start} – ${bh.end}`;
  }, [draft]);

  return (
    <div className="rounded-[12px] border border-white/[0.07] bg-white/[0.02] p-4 hover:bg-white/[0.03] transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[14px] text-white font-medium truncate">
            {draft.data.name || "Untitled draft"}
          </div>
          <div className="text-[11px] text-white/40 mt-0.5">
            Saved {new Date(draft.saved_at).toLocaleString()}
          </div>
        </div>
        <span className="text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20">
          Draft
        </span>
      </div>

      <div className="mt-3 space-y-1.5 text-[12px] text-white/65">
        <DraftLine icon={<Users size={11} />}>
          {draft.data.lead_list_id
            ? `Lead list: ${draft.data.lead_list_id}`
            : "No lead list selected"}
        </DraftLine>
        <DraftLine icon={<CalendarClock size={11} />}>{scheduleLabel}</DraftLine>
        <DraftLine icon={<Clock size={11} />}>{hoursLabel}</DraftLine>
      </div>

      <div className="mt-3 flex justify-end">
        <Button
          variant="ghost"
          size="xs"
          onClick={() => onDelete(draft.id)}
          className="text-white/45 hover:text-red-300"
        >
          <Trash2 size={12} />
          Discard
        </Button>
      </div>
    </div>
  );
}

function DraftLine({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-white/35 shrink-0">{icon}</span>
      <span className="truncate">{children}</span>
    </div>
  );
}
