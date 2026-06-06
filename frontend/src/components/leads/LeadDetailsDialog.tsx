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
import { getLead } from "@/services/lead";
import { leadFullName } from "@/types/lead";
import type { Lead, LeadStatus } from "@/types/lead";

const STATUS_STYLES: Record<LeadStatus, { label: string; className: string }> =
  {
    new: {
      label: "New",
      className: "bg-sky-500/10 text-sky-300 border-sky-500/20",
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

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead: Lead | null;
  refreshKey?: number;
  callDisabled?: boolean;
  onEdit?: (lead: Lead) => void;
  onStartCall?: (lead: Lead) => void;
};

export default function LeadDetailsDialog({
  open,
  onOpenChange,
  lead: initialLead,
  refreshKey,
  callDisabled,
  onEdit,
  onStartCall,
}: Props) {
  const [lead, setLead] = useState<Lead | null>(initialLead);
  const [loading, setLoading] = useState(false);

  const fetchLead = useCallback(async () => {
    if (!initialLead) return;
    setLoading(true);
    try {
      const fresh = await getLead(initialLead.id);
      setLead(fresh);
    } catch (err) {
      toast.error(formatApiError(err, "Could not load lead details"));
    } finally {
      setLoading(false);
    }
  }, [initialLead]);

  useEffect(() => {
    if (open && initialLead) void fetchLead();
  }, [open, initialLead, refreshKey, fetchLead]);

  if (!lead) return null;

  const status = STATUS_STYLES[lead.status];
  const fullName = leadFullName(lead);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md p-0 gap-0 bg-[#0c0c10] border border-white/[0.08]"
        showCloseButton
      >
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <div className="flex items-start gap-3">
            <div className="h-10 w-10 shrink-0 rounded-full bg-white/[0.06] border border-white/[0.08] flex items-center justify-center text-[13px] font-medium text-white/80">
              {fullName
                .split(" ")
                .map((p) => p[0])
                .join("")
                .slice(0, 2)
                .toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-[15px] text-white truncate">
                {fullName}
              </DialogTitle>
              <div className="flex items-center gap-2 mt-1">
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
            {loading && (
              <Loader2 size={14} className="animate-spin text-white/40 mt-1" />
            )}
          </div>
          <DialogDescription className="sr-only">
            Lead details for {fullName}
          </DialogDescription>
        </DialogHeader>

        <div className="px-5 py-4 space-y-3">
          <InfoRow icon={Phone} label="Phone" value={lead.phone} />
          <InfoRow icon={Mail} label="Email" value={lead.email ?? "—"} />
          <InfoRow
            icon={Briefcase}
            label="Job title"
            value={lead.job_title ?? "—"}
          />
          <InfoRow
            icon={Building2}
            label="Company"
            value={lead.company ?? "—"}
          />

          {lead.linkedin_url && (
            <div className="flex items-start gap-2.5">
              <div className="mt-0.5 h-7 w-7 shrink-0 rounded-[7px] bg-white/[0.04] border border-white/[0.06] flex items-center justify-center">
                <ExternalLink size={12} className="text-white/45" />
              </div>
              <div className="min-w-0">
                <div className="text-[10.5px] text-white/40 uppercase tracking-wider mb-0.5">
                  LinkedIn
                </div>
                <a
                  href={lead.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[12px] text-violet-300 hover:text-violet-200 truncate block"
                >
                  {lead.linkedin_url}
                </a>
              </div>
            </div>
          )}

          {lead.tags && lead.tags.length > 0 && (
            <div className="flex items-start gap-2.5">
              <div className="mt-0.5 h-7 w-7 shrink-0 rounded-[7px] bg-white/[0.04] border border-white/[0.06] flex items-center justify-center">
                <Tag size={12} className="text-white/45" />
              </div>
              <div>
                <div className="text-[10.5px] text-white/40 uppercase tracking-wider mb-1">
                  Tags
                </div>
                <div className="flex flex-wrap gap-1">
                  {lead.tags.map((tag) => (
                    <span
                      key={tag}
                      className="inline-flex items-center h-5 px-2 rounded-full bg-white/[0.05] border border-white/[0.08] text-[11px] text-white/70"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="text-[11px] text-white/35 pt-1">
            Added {new Date(lead.created_at).toLocaleDateString()}
          </div>
        </div>

        <div className="px-5 pb-5 flex items-center gap-2">
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
            disabled={callDisabled}
            className="flex-1 bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
            onClick={() => {
              onStartCall?.(lead);
              onOpenChange(false);
            }}
          >
            <PhoneCall size={13} />
            Call
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Phone;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-2.5">
      <div className="mt-0.5 h-7 w-7 shrink-0 rounded-[7px] bg-white/[0.04] border border-white/[0.06] flex items-center justify-center">
        <Icon size={12} className="text-white/45" />
      </div>
      <div className="min-w-0">
        <div className="text-[10.5px] text-white/40 uppercase tracking-wider mb-0.5">
          {label}
        </div>
        <div className="text-[13px] text-white/85 truncate">{value}</div>
      </div>
    </div>
  );
}
