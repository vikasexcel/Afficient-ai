import { useEffect, useState } from "react";
import { Loader2, Phone, Mail, CalendarClock, StickyNote } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { formatApiError } from "@/lib/apiError";
import { logLeadActivity } from "@/services/lead";
import type { ActivityType, Lead, LeadActivity } from "@/types/lead";

const ACTIVITY_TYPES: {
  value: ActivityType;
  label: string;
  icon: typeof Phone;
}[] = [
  { value: "call", label: "Call", icon: Phone },
  { value: "email", label: "Email", icon: Mail },
  { value: "meeting", label: "Meeting", icon: CalendarClock },
  { value: "note", label: "Note", icon: StickyNote },
];

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lead: Lead | null;
  onLogged?: (activity: LeadActivity) => void;
};

export default function LogActivityDialog({
  open,
  onOpenChange,
  lead,
  onLogged,
}: Props) {
  const [type, setType] = useState<ActivityType>("call");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setType("call");
      setNotes("");
    }
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!lead) return;
    setSubmitting(true);
    try {
      const activity = await logLeadActivity(lead.id, {
        activity_type: type,
        notes: notes.trim() || null,
      });
      toast.success("Activity logged");
      onLogged?.(activity);
      onOpenChange(false);
    } catch (err) {
      toast.error(formatApiError(err, "Failed to log activity"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md p-0 gap-0 bg-[#0c0c10] border border-white/[0.08]"
        showCloseButton
      >
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <DialogTitle className="text-[15px] text-white">
            Log activity
          </DialogTitle>
          <DialogDescription className="text-[12px] text-white/45 mt-0.5">
            {lead ? `Record a touchpoint with ${lead.name}.` : ""}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="px-5 py-4 space-y-4">
          <div>
            <Label className="text-[11px] font-medium text-white/55 mb-1.5 block">
              Type
            </Label>
            <div className="grid grid-cols-4 gap-1.5">
              {ACTIVITY_TYPES.map((t) => {
                const Icon = t.icon;
                const active = type === t.value;
                return (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => setType(t.value)}
                    className={cn(
                      "flex flex-col items-center gap-1 py-2 rounded-[8px] border text-[11px] transition-colors",
                      active
                        ? "bg-violet-500/15 text-violet-200 border-violet-500/30"
                        : "text-white/55 hover:text-white hover:bg-white/[0.04] border-white/[0.08]"
                    )}
                  >
                    <Icon size={15} />
                    {t.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <Label className="text-[11px] font-medium text-white/55 mb-1.5 block">
              Notes
            </Label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="What happened on this touchpoint?"
              className="min-h-24 bg-white/[0.03] border-white/[0.09] text-[13px]"
              autoFocus
            />
          </div>

          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onOpenChange(false)}
              className="text-white/60 hover:text-white"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={submitting}
              className="bg-violet-600 hover:bg-violet-500 text-white"
            >
              {submitting && <Loader2 size={13} className="animate-spin" />}
              Log activity
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
