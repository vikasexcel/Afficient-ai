import { useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { deleteLead, formatLeadError } from "@/services/leads";
import { leadFullName } from "@/types/lead";
import type { Lead } from "@/types/lead";

type Props = {
  lead: Lead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted?: (lead: Lead) => void;
};

export default function LeadDeleteDialog({
  lead,
  open,
  onOpenChange,
  onDeleted,
}: Props) {
  const [deleting, setDeleting] = useState(false);

  if (!lead) return null;

  const fullName = leadFullName(lead);

  async function handleConfirm() {
    setDeleting(true);
    try {
      await deleteLead(lead!.id);
      toast.success(`${fullName} deleted`);
      onDeleted?.(lead!);
      onOpenChange(false);
    } catch (err) {
      toast.error(formatLeadError(err, "Could not delete lead"));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent
        size="sm"
        className="bg-[#0c0c10] border border-white/[0.08] gap-4"
      >
        <AlertDialogHeader>
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 shrink-0 rounded-[10px] bg-red-500/10 border border-red-500/25 flex items-center justify-center">
              <Trash2 size={15} className="text-red-400" />
            </div>
            <div>
              <AlertDialogTitle className="text-[15px] font-medium text-white text-left">
                Delete lead
              </AlertDialogTitle>
              <AlertDialogDescription className="text-[12px] text-white/45 mt-0.5 text-left">
                This will permanently remove{" "}
                <span className="text-white/80 font-medium">{fullName}</span>{" "}
                and cannot be undone.
              </AlertDialogDescription>
            </div>
          </div>
        </AlertDialogHeader>

        <AlertDialogFooter className="bg-transparent border-t border-white/[0.06] -mx-4 -mb-4 px-4 py-3">
          <AlertDialogCancel
            size="sm"
            variant="ghost"
            className="text-white/60 hover:text-white border-0"
          >
            Cancel
          </AlertDialogCancel>
          <Button
            size="sm"
            disabled={deleting}
            onClick={handleConfirm}
            className="bg-red-600 hover:bg-red-500 text-white min-w-[80px]"
          >
            {deleting ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              "Delete"
            )}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
