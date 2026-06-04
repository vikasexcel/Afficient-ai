import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  CalendarClock,
  Loader2,
  Megaphone,
  Pencil,
  Rocket,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import CreateCampaignDialog from "@/components/campaign/CreateCampaignDialog";
import { Button } from "@/components/ui/button";
import {
  activateCampaign,
  deleteCampaign,
  listCampaigns,
} from "@/services/campaign";
import { useMe, canUseCampaigns } from "@/store/me";
import type { CampaignOut } from "@/types/campaign";

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-amber-500/10 text-amber-300 border-amber-500/20",
  scheduled: "bg-sky-500/10 text-sky-300 border-sky-500/20",
  active: "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
  paused: "bg-white/10 text-white/60 border-white/20",
  completed: "bg-violet-500/10 text-violet-300 border-violet-500/20",
  archived: "bg-white/5 text-white/40 border-white/10",
};

export default function Campaigns() {
  const me = useMe((s) => s.data);
  const canCreate = canUseCampaigns(me?.role);

  const [campaigns, setCampaigns] = useState<CampaignOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<CampaignOut | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { campaigns } = await listCampaigns();
      setCampaigns(campaigns);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to load campaigns"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleDelete(id: string) {
    setBusyId(id);
    try {
      await deleteCampaign(id);
      toast.success("Campaign deleted");
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusyId(null);
    }
  }

  async function handleLaunch(c: CampaignOut) {
    setBusyId(c.id);
    try {
      const res = await activateCampaign(c.id);
      if (res.scheduled) {
        toast.success(res.message ?? `"${c.name}" scheduled`);
      } else {
        const n = res.enqueued_leads ?? 0;
        toast.success(
          `"${c.name}" launched` +
            (n ? ` · ${n} lead${n === 1 ? "" : "s"} queued` : "")
        );
      }
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Launch failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AppLayout>
      <div className="max-w-6xl space-y-6">
        <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-3">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-medium text-white">
              Campaigns
            </h1>
            <p className="text-[13px] text-white/40 mt-1">
              {canCreate
                ? "Configure AI outbound campaigns, schedule them, and launch when ready"
                : "View-only access — contact an admin to create campaigns"}
            </p>
          </div>

          {canCreate && (
            <div className="self-start sm:self-auto">
              <CreateCampaignDialog onCreated={refresh} onSaved={refresh} />
            </div>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20 text-white/45">
            <Loader2 size={18} className="animate-spin mr-2" />
            Loading campaigns…
          </div>
        ) : campaigns.length === 0 ? (
          <EmptyState canCreate={canCreate} />
        ) : (
          <CampaignsList
            campaigns={campaigns}
            canCreate={canCreate}
            busyId={busyId}
            onEdit={setEditing}
            onDelete={handleDelete}
            onLaunch={handleLaunch}
          />
        )}
      </div>

      {/* Controlled edit dialog (no trigger of its own). */}
      {editing && (
        <CreateCampaignDialog
          campaign={editing}
          open={Boolean(editing)}
          onOpenChange={(o) => {
            if (!o) setEditing(null);
          }}
          onCreated={refresh}
          onSaved={refresh}
        />
      )}
    </AppLayout>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] py-16 flex flex-col items-center text-center">
      <div className="h-11 w-11 rounded-full bg-violet-500/10 border border-violet-500/20 flex items-center justify-center mb-3">
        <Megaphone size={18} className="text-violet-300" />
      </div>
      <div className="text-[14px] text-white font-medium">No campaigns yet</div>
      <p className="text-[12px] text-white/45 mt-1 max-w-sm">
        {canCreate
          ? "Create your first campaign to assign a playbook, pick a lead list, and start dialing."
          : "Once an admin creates a campaign it'll show up here."}
      </p>
    </div>
  );
}

function CampaignsList({
  campaigns,
  canCreate,
  busyId,
  onEdit,
  onDelete,
  onLaunch,
}: {
  campaigns: CampaignOut[];
  canCreate: boolean;
  busyId: string | null;
  onEdit: (c: CampaignOut) => void;
  onDelete: (id: string) => void;
  onLaunch: (c: CampaignOut) => void;
}) {
  return (
    <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {campaigns.map((c) => (
        <CampaignCard
          key={c.id}
          campaign={c}
          canCreate={canCreate}
          busy={busyId === c.id}
          onEdit={onEdit}
          onDelete={onDelete}
          onLaunch={onLaunch}
        />
      ))}
    </section>
  );
}

function CampaignCard({
  campaign,
  canCreate,
  busy,
  onEdit,
  onDelete,
  onLaunch,
}: {
  campaign: CampaignOut;
  canCreate: boolean;
  busy: boolean;
  onEdit: (c: CampaignOut) => void;
  onDelete: (id: string) => void;
  onLaunch: (c: CampaignOut) => void;
}) {
  const scheduleLabel = useMemo(() => {
    if (campaign.scheduled_at) {
      const d = new Date(campaign.scheduled_at);
      return `${d.toLocaleString()}${
        campaign.timezone ? ` (${campaign.timezone})` : ""
      }`;
    }
    return "Starts immediately";
  }, [campaign]);

  const created = campaign.created_at
    ? new Date(campaign.created_at).toLocaleDateString()
    : "—";

  const statusStyle =
    STATUS_STYLES[campaign.status] ?? STATUS_STYLES["draft"];

  const canLaunch =
    canCreate && ["draft", "scheduled", "paused"].includes(campaign.status);

  return (
    <div className="rounded-[12px] border border-white/[0.07] bg-white/[0.02] p-4 hover:bg-white/[0.03] transition-colors flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[14px] text-white font-medium truncate">
            {campaign.name || "Untitled campaign"}
          </div>
          <div className="text-[11px] text-white/40 mt-0.5">
            Created {created}
          </div>
        </div>
        <span
          className={`text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded-full border ${statusStyle}`}
        >
          {campaign.status}
        </span>
      </div>

      <div className="mt-3 space-y-1.5 text-[12px] text-white/65">
        <CardLine icon={<BookOpen size={11} />}>
          {campaign.playbook_name
            ? `Playbook: ${campaign.playbook_name}`
            : "No playbook assigned"}
        </CardLine>
        <CardLine icon={<Users size={11} />}>
          {campaign.lead_list_name
            ? `Leads: ${campaign.lead_list_name}` +
              (campaign.lead_count != null
                ? ` (${campaign.lead_count.toLocaleString()})`
                : "")
            : "No lead list selected"}
        </CardLine>
        <CardLine icon={<CalendarClock size={11} />}>{scheduleLabel}</CardLine>
      </div>

      {canCreate && (
        <div className="mt-3 pt-3 border-t border-white/[0.05] flex justify-end gap-1.5">
          {canLaunch && (
            <Button
              variant="ghost"
              size="xs"
              disabled={busy}
              onClick={() => onLaunch(campaign)}
              className="text-emerald-300/80 hover:text-emerald-200"
            >
              {busy ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Rocket size={12} />
              )}
              Launch
            </Button>
          )}
          <Button
            variant="ghost"
            size="xs"
            disabled={busy}
            onClick={() => onEdit(campaign)}
            className="text-white/55 hover:text-white"
          >
            <Pencil size={12} />
            Edit
          </Button>
          <Button
            variant="ghost"
            size="xs"
            disabled={busy}
            onClick={() => onDelete(campaign.id)}
            className="text-white/45 hover:text-red-300"
          >
            <Trash2 size={12} />
            Delete
          </Button>
        </div>
      )}
    </div>
  );
}

function CardLine({
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
