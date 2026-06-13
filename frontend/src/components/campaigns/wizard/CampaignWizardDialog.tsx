import { Dialog, DialogContent } from "@/components/ui/dialog";
import CampaignWizard from "./CampaignWizard";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export default function CampaignWizardDialog({ open, onClose, onCreated }: Props) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="max-w-3xl w-full h-[90vh] flex flex-col p-0 bg-[#0a0a12] border border-white/[0.08] text-white [&>button]:hidden shadow-2xl shadow-black/60 rounded-2xl overflow-hidden">
        <CampaignWizard onClose={onClose} onCreated={onCreated} />
      </DialogContent>
    </Dialog>
  );
}
