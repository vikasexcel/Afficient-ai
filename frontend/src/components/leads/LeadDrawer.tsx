import { useCallback, useEffect, useState } from "react";
import {
  Briefcase,
  Building2,
  ExternalLink,
  Loader2,
  Mail,
  Pencil,
  Phone,
  PhoneCall,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatLeadError, getLead } from "@/services/leads";
import { leadFullName } from "@/types/lead";
import type { Lead, LeadList, LeadStatus } from "@/types/lead";

// ---------------------------------------------------------------------------
// Status config
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<
  LeadStatus,
  { label: string; className: string }
> = {
  new: {
    label: "New",
    className: "bg-sky-500/10 text-sky-300 border-sky-500/25",
  },
  contacted: {
    label: "Contacted",
    className: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  },
  qualified: {
    label: "Qualified",
    className: "bg-violet-500/10 text-violet-300 border-violet-500/25",
  },
  converted: {
    label: "Converted",
    className: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  },
  lost: {
    label: "Lost",
    className: "bg-red-500/10 text-red-300 border-red-500/25",
  },
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type Props = {
  lead: Lead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** All lead lists for the org — used to display list names. */
  leadLists?: LeadList[];
  onEdit?: (lead: Lead) => void;
  onDelete?: (lead: Lead) => void;
  onCall?: (lead: Lead) => void;
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LeadDrawer({
  lead: initialLead,
  open,
  onOpenChange,
  leadLists = [],
  onEdit,
  onDelete,
  onCall,
}: Props) {
  const [lead, setLead] = useState<Lead | null>(initialLead);
  const [loading, setLoading] = useState(false);

  const fetchLead = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const fresh = await getLead(id);
      setLead(fresh);
    } catch (err) {
      toast.error(formatLeadError(err, "Could not load lead"));
    } finally {
      setLoading(false);
    }
  }, []);

  // Refresh from API when the drawer opens. The parent passes key={lead.id}
  // so this component remounts on lead change; useState is already initialised
  // from the prop. fetchLead updates state in its async callback, not
  // synchronously — disable directive kept for the transitive static analysis.
  useEffect(() => {
    if (!open || !initialLead) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchLead(initialLead.id);
  }, [open, initialLead, fetchLead]);

  if (!lead) return null;

  const fullName = leadFullName(lead);
  const status = STATUS_CONFIG[lead.status];
  const initials = fullName
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  const memberLists = leadLists.filter((ll) =>
    lead.lead_list_ids.includes(ll.id)
  );

  const extraEntries = lead.extra_data
    ? Object.entries(lead.extra_data).filter(([, v]) => v !== null && v !== "")
    : [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        showCloseButton={false}
        className="w-full sm:max-w-md bg-[#0c0c10] border-l border-white/[0.08] flex flex-col p-0 gap-0"
      >
        {/* Header */}
        <SheetHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06] flex-none">
          <div className="flex items-start gap-3">
            <div className="h-11 w-11 shrink-0 rounded-full bg-white/[0.06] border border-white/[0.08] flex items-center justify-center text-[14px] font-semibold text-white/80">
              {initials}
            </div>

            <div className="min-w-0 flex-1">
              <SheetTitle className="text-[16px] font-medium text-white leading-tight truncate">
                {fullName}
              </SheetTitle>
              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                <span
                  className={cn(
                    "inline-flex items-center h-5 px-2 rounded-full border text-[11px] font-medium",
                    status.className
                  )}
                >
                  {status.label}
                </span>
                {lead.company && (
                  <span className="text-[12px] text-white/45 truncate">
                    {lead.company}
                  </span>
                )}
              </div>
            </div>

            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => onOpenChange(false)}
              className="shrink-0 text-white/40 hover:text-white mt-0.5"
            >
              <X size={15} />
            </Button>
          </div>
          <SheetDescription className="sr-only">
            Details for {fullName}
          </SheetDescription>
        </SheetHeader>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center py-4 text-white/35">
              <Loader2 size={14} className="animate-spin mr-2" />
              <span className="text-[12px]">Refreshing…</span>
            </div>
          )}

          {/* Contact info */}
          <section className="px-5 py-4 space-y-3 border-b border-white/[0.05]">
            <SectionLabel>Contact</SectionLabel>

            <InfoRow icon={Phone} label="Phone">
              <a
                href={`tel:${lead.phone}`}
                className="text-[13px] text-white/85 hover:text-white transition-colors"
              >
                {lead.phone}
              </a>
            </InfoRow>

            {lead.email ? (
              <InfoRow icon={Mail} label="Email">
                <a
                  href={`mailto:${lead.email}`}
                  className="text-[13px] text-white/85 hover:text-white transition-colors truncate"
                >
                  {lead.email}
                </a>
              </InfoRow>
            ) : (
              <InfoRow icon={Mail} label="Email">
                <span className="text-[13px] text-white/35">—</span>
              </InfoRow>
            )}

            {lead.linkedin_url && (
              <InfoRow icon={ExternalLink} label="LinkedIn">
                <a
                  href={lead.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[13px] text-violet-300 hover:text-violet-200 transition-colors truncate block"
                >
                  {lead.linkedin_url.replace(/^https?:\/\/(www\.)?/, "")}
                </a>
              </InfoRow>
            )}
          </section>

          {/* Work info */}
          <section className="px-5 py-4 space-y-3 border-b border-white/[0.05]">
            <SectionLabel>Work</SectionLabel>

            <InfoRow icon={Building2} label="Company">
              <span className="text-[13px] text-white/85">
                {lead.company ?? <span className="text-white/35">—</span>}
              </span>
            </InfoRow>

            <InfoRow icon={Briefcase} label="Job title">
              <span className="text-[13px] text-white/85">
                {lead.job_title ?? (
                  <span className="text-white/35">—</span>
                )}
              </span>
            </InfoRow>
          </section>

          {/* Tags */}
          {lead.tags && lead.tags.length > 0 && (
            <section className="px-5 py-4 border-b border-white/[0.05]">
              <SectionLabel className="mb-2">Tags</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {lead.tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 h-5 px-2 rounded-full bg-white/[0.05] border border-white/[0.08] text-[11px] text-white/65"
                  >
                    <Tag size={9} className="text-white/40" />
                    {tag}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Lead list memberships */}
          {memberLists.length > 0 && (
            <section className="px-5 py-4 border-b border-white/[0.05]">
              <SectionLabel className="mb-2">Lead lists</SectionLabel>
              <div className="flex flex-col gap-1.5">
                {memberLists.map((ll) => (
                  <div
                    key={ll.id}
                    className="text-[12px] text-white/70 flex items-center gap-1.5"
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-violet-400/60 shrink-0" />
                    {ll.name}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Extra data */}
          {extraEntries.length > 0 && (
            <section className="px-5 py-4 border-b border-white/[0.05]">
              <SectionLabel className="mb-2">Extra data</SectionLabel>
              <div className="space-y-1.5">
                {extraEntries.map(([key, value]) => (
                  <div key={key} className="flex items-baseline gap-2">
                    <span className="text-[11px] text-white/40 capitalize min-w-[80px] shrink-0">
                      {key.replace(/_/g, " ")}
                    </span>
                    <span className="text-[12px] text-white/70 break-all">
                      {String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Metadata */}
          <section className="px-5 py-4">
            <div className="flex items-center justify-between text-[11px] text-white/30">
              <span>Created</span>
              <span>{new Date(lead.created_at).toLocaleDateString()}</span>
            </div>
            <div className="flex items-center justify-between text-[11px] text-white/30 mt-1">
              <span>Updated</span>
              <span>{new Date(lead.updated_at).toLocaleDateString()}</span>
            </div>
          </section>
        </div>

        {/* Footer actions */}
        <div className="flex-none px-5 py-4 border-t border-white/[0.06] flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="flex-1 border-white/[0.08] text-white/70 hover:text-white hover:bg-white/[0.04]"
            onClick={() => {
              onEdit?.(lead);
              onOpenChange(false);
            }}
          >
            <Pencil size={13} />
            Edit
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="flex-1 border-red-500/20 text-red-400 hover:text-red-300 hover:bg-red-500/10"
            onClick={() => {
              onDelete?.(lead);
              onOpenChange(false);
            }}
          >
            <Trash2 size={13} />
            Delete
          </Button>
          <Button
            size="sm"
            className="flex-1 bg-violet-600 hover:bg-violet-500 text-white"
            onClick={() => onCall?.(lead)}
          >
            <PhoneCall size={13} />
            Call
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p
      className={cn(
        "text-[10px] font-semibold text-white/35 uppercase tracking-widest",
        className
      )}
    >
      {children}
    </p>
  );
}

function InfoRow({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof Phone;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2.5">
      <div className="mt-0.5 h-7 w-7 shrink-0 rounded-[7px] bg-white/[0.04] border border-white/[0.06] flex items-center justify-center">
        <Icon size={12} className="text-white/40" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] text-white/35 uppercase tracking-wide mb-0.5">
          {label}
        </p>
        {children}
      </div>
    </div>
  );
}
