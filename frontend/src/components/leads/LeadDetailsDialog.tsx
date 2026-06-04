import { useCallback, useEffect, useState } from "react";
import {
  CalendarClock,
  Loader2,
  Mail,
  Pencil,
  Phone,
  PhoneCall,
  Plus,
  StickyNote,
} from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatApiError } from "@/lib/apiError";
import {
  getLead,
  listLeadActivities,
  listLeadLists,
} from "@/services/lead";
import type {
  ActivityType,
  Lead,
  LeadActivity,
  LeadStatus,
} from "@/types/lead";

const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  converted: "Converted",
  lost: "Lost",
};

const ACTIVITY_META: Record<
  ActivityType,
  { label: string; icon: typeof Phone }
> = {
  call: { label: "Call", icon: Phone },
  email: { label: "Email", icon: Mail },
  meeting: { label: "Meeting", icon: CalendarClock },
  note: { label: "Note", icon: StickyNote },
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead: Lead | null;
  /** Bump to force the activity timeline to refetch. */
  refreshKey?: number;
  callDisabled?: boolean;
  onEdit?: (lead: Lead) => void;
  onLogActivity?: (lead: Lead) => void;
  onStartCall?: (lead: Lead) => void;
};

function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

export default function LeadDetailsDialog({
  open,
  onOpenChange,
  lead,
  refreshKey = 0,
  callDisabled = false,
  onEdit,
  onLogActivity,
  onStartCall,
}: Props) {
  const [detail, setDetail] = useState<Lead | null>(lead);
  const [activities, setActivities] = useState<LeadActivity[]>([]);
  const [loading, setLoading] = useState(false);
  const [listName, setListName] = useState<string | null>(null);

  const loadDetails = useCallback(async () => {
    if (!lead) return;
    setLoading(true);
    try {
      const [fresh, acts] = await Promise.all([
        getLead(lead.id),
        listLeadActivities(lead.id),
      ]);
      setDetail(fresh);
      setActivities(acts);
    } catch (err) {
      setActivities([]);
      toast.error(formatApiError(err, "Could not load lead details"));
      onOpenChange(false);
    } finally {
      setLoading(false);
    }
  }, [lead, onOpenChange]);

  useEffect(() => {
    if (open && lead) {
      setDetail(lead);
      void loadDetails();
    }
  }, [open, lead, refreshKey, loadDetails]);

  // Resolve the lead list name for display.
  useEffect(() => {
    if (!open || !lead?.lead_list_id) {
      setListName(null);
      return;
    }
    void listLeadLists()
      .then((lists) => {
        const match = lists.find((l) => l.id === lead.lead_list_id);
        setListName(match?.name ?? null);
      })
      .catch(() => setListName(null));
  }, [open, lead]);

  const shown = detail ?? lead;
  if (!shown) return null;

  const lastActivity = activities[0]?.created_at ?? null;
  const customEntries = Object.entries(shown.custom_fields ?? {});

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-2xl p-0 gap-0 bg-[#0c0c10] border border-white/[0.08] max-h-[85vh] overflow-hidden flex flex-col"
        showCloseButton
      >
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <DialogTitle className="text-[16px] text-white">
            {shown.name}
          </DialogTitle>
          <DialogDescription className="text-[12px] text-white/45 mt-0.5">
            {shown.company ?? "No company"} · {STATUS_LABELS[shown.status]}
          </DialogDescription>

          <div className="flex flex-wrap items-center gap-2 mt-3">
            <Button
              size="xs"
              variant="outline"
              className="border-white/[0.1] bg-white/[0.02] text-white/85 hover:bg-white/[0.06]"
              onClick={() => onEdit?.(shown)}
            >
              <Pencil size={12} />
              Edit
            </Button>
            <Button
              size="xs"
              variant="outline"
              className="border-white/[0.1] bg-white/[0.02] text-white/85 hover:bg-white/[0.06]"
              onClick={() => onLogActivity?.(shown)}
            >
              <Plus size={12} />
              Log activity
            </Button>
            <Button
              size="xs"
              variant="outline"
              disabled={callDisabled}
              title={
                callDisabled ? "Calling functionality coming soon" : undefined
              }
              className="border-white/[0.1] bg-white/[0.02] text-white/85 hover:bg-white/[0.06]"
              onClick={() => onStartCall?.(shown)}
            >
              <PhoneCall size={12} />
              Start call
            </Button>
          </div>
        </DialogHeader>

        <div className="overflow-y-auto px-5 py-4 space-y-5">
          <section className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
            <Detail label="Name" value={shown.name} />
            <Detail label="Email" value={shown.email} />
            <Detail label="Phone" value={shown.phone} />
            <Detail label="Company" value={shown.company} />
            <Detail label="Industry" value={shown.industry} />
            <Detail label="Status" value={STATUS_LABELS[shown.status]} />
            <Detail label="Lead list" value={listName} />
            <Detail label="Created" value={fmtDate(shown.created_at)} />
            <Detail label="Last activity" value={fmtDate(lastActivity)} />
            <div className="sm:col-span-2">
              <FieldLabel>Tags</FieldLabel>
              {shown.tags && shown.tags.length > 0 ? (
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {shown.tags.map((t) => (
                    <span
                      key={t}
                      className="inline-flex items-center h-5 px-2 rounded-full border border-white/[0.1] bg-white/[0.04] text-[11px] text-white/75"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-[13px] text-white/45 mt-0.5">—</p>
              )}
            </div>
          </section>

          {customEntries.length > 0 && (
            <section>
              <FieldLabel>Custom fields</FieldLabel>
              <div className="mt-1.5 rounded-[8px] border border-white/[0.07] divide-y divide-white/[0.05]">
                {customEntries.map(([k, v]) => (
                  <div
                    key={k}
                    className="flex items-center justify-between gap-3 px-3 py-1.5"
                  >
                    <span className="text-[12px] text-white/50">{k}</span>
                    <span className="text-[12px] text-white/85 truncate">
                      {String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section>
            <FieldLabel>Activity history</FieldLabel>
            {loading ? (
              <div className="py-6 flex items-center justify-center text-white/45 text-[12px]">
                <Loader2 size={14} className="animate-spin mr-2" />
                Loading…
              </div>
            ) : activities.length === 0 ? (
              <p className="text-[12px] text-white/40 mt-2">
                No activity logged yet.
              </p>
            ) : (
              <ol className="mt-2 space-y-2.5">
                {activities.map((a) => {
                  const meta = ACTIVITY_META[a.activity_type];
                  const Icon = meta.icon;
                  return (
                    <li key={a.id} className="flex gap-2.5">
                      <div className="h-7 w-7 shrink-0 rounded-full bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-white/65">
                        <Icon size={12} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[12.5px] text-white font-medium">
                            {meta.label}
                          </span>
                          <span className="text-[11px] text-white/40">
                            {fmtDate(a.created_at)}
                          </span>
                        </div>
                        {a.notes && (
                          <p className="text-[12px] text-white/65 mt-0.5 whitespace-pre-wrap break-words">
                            {a.notes}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Detail({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <p className={cn("text-[13px] mt-0.5", value ? "text-white/85" : "text-white/45")}>
        {value || "—"}
      </p>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10.5px] font-medium text-white/45 uppercase tracking-wider">
      {children}
    </span>
  );
}
