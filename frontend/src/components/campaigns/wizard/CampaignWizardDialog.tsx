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
      <DialogContent className="max-w-2xl h-[85vh] flex flex-col p-0 bg-[#0d0d14] border-white/[0.08] text-white [&>button]:hidden">
        <CampaignWizard onClose={onClose} onCreated={onCreated} />
      </DialogContent>
    </Dialog>
  );
}
