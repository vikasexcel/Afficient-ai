/**
 * TemplateSelector — full-screen dialog that wraps the gallery.
 *
 * Flow:
 *   open → load templates → select card → preview modal
 *     → [confirm replace if canvas has nodes] → clone → apply → close
 */
import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { listTemplates, cloneTemplate } from "@/services/workflow";
import type { WorkflowTemplate } from "@/types/workflow";
import TemplateGallery from "./TemplateGallery";
import TemplatePreviewModal from "./TemplatePreviewModal";

interface Props {
  open: boolean;
  hasExistingNodes: boolean;
  onClose: () => void;
  onApply: (template: WorkflowTemplate) => void;
}

type Stage = "gallery" | "preview" | "confirm";

export default function TemplateSelector({ open, hasExistingNodes, onClose, onApply }: Props) {
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selected, setSelected] = useState<WorkflowTemplate | null>(null);
  const [stage, setStage] = useState<Stage>("gallery");
  const [applying, setApplying] = useState(false);

  // Load templates when dialog opens.
  useEffect(() => {
    if (!open) return;
    setLoadingTemplates(true);
    setLoadError(null);
    listTemplates()
      .then((res) => setTemplates(res.templates))
      .catch(() => setLoadError("Failed to load templates. Check your connection."))
      .finally(() => setLoadingTemplates(false));
  }, [open]);

  function handleSelectCard(template: WorkflowTemplate) {
    setSelected(template);
    setStage("preview");
  }

  function handleUseTemplate() {
    if (hasExistingNodes) {
      setStage("confirm");
    } else {
      void applyTemplate();
    }
  }

  async function applyTemplate() {
    if (!selected) return;
    setApplying(true);
    try {
      const cloned = await cloneTemplate(selected.id);
      onApply(cloned);
      onClose();
    } catch {
      // Surface error without crashing — user can retry.
      setApplying(false);
    }
  }

  function handleConfirmReplace() {
    void applyTemplate();
  }

  function handleBackToGallery() {
    setSelected(null);
    setStage("gallery");
  }

  return (
    <>
      {/* Main gallery dialog */}
      <Dialog
        open={open && stage !== "preview" && stage !== "confirm"}
        onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}
      >
        <DialogContent className="max-w-3xl h-[80vh] flex flex-col bg-[#0d0d14] border-white/[0.08] text-white">
          <DialogHeader className="shrink-0">
            <DialogTitle className="text-white text-base">
              Workflow Templates
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-hidden">
            <TemplateGallery
              templates={templates}
              loading={loadingTemplates}
              error={loadError}
              onSelect={handleSelectCard}
            />
          </div>
        </DialogContent>
      </Dialog>

      {/* Template preview modal — sits on top of gallery */}
      {stage === "preview" && selected && (
        <TemplatePreviewModal
          template={selected}
          applying={applying}
          onUse={handleUseTemplate}
          onCancel={handleBackToGallery}
        />
      )}

      {/* Confirm replace dialog */}
      <AlertDialog open={stage === "confirm"}>
        <AlertDialogContent className="bg-[#0d0d14] border-white/[0.08] text-white">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">Replace current workflow?</AlertDialogTitle>
            <AlertDialogDescription className="text-white/50">
              This will replace all existing nodes and connections with the template.
              You can still cancel without saving.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={handleBackToGallery}
              className="bg-transparent border-white/10 text-white/60 hover:text-white hover:bg-white/5"
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmReplace}
              className="bg-violet-600 hover:bg-violet-500 text-white border-0"
            >
              Replace
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
