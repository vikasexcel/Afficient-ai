/**
 * VersionHistoryDrawer — right-side overlay panel showing the version history
 * for the current workflow.
 *
 * Flow:
 *   open → GET /versions (list)
 *   click card → GET /versions/{n} (detail) → VersionPreviewModal
 *   click Restore → RestoreVersionDialog confirm
 *   confirm → POST /versions/{n}/restore → onRestored(response) → close
 */
import { useEffect, useState } from "react";
import { History, X } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  listWorkflowVersions,
  getWorkflowVersion,
  restoreWorkflowVersion,
} from "@/services/workflow";
import type {
  WorkflowVersionSummary,
  WorkflowVersionDetail,
  WorkflowRestoreResponse,
} from "@/types/workflow";
import VersionList from "./VersionList";
import VersionPreviewModal from "./VersionPreviewModal";
import RestoreVersionDialog from "./RestoreVersionDialog";

interface Props {
  open: boolean;
  campaignId: string;
  onClose: () => void;
  onRestored: (response: WorkflowRestoreResponse) => void;
}

export default function VersionHistoryDrawer({
  open,
  campaignId,
  onClose,
  onRestored,
}: Props) {
  // ── List state ──────────────────────────────────────────────────────────────
  const [versions, setVersions] = useState<WorkflowVersionSummary[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  // ── Preview state ────────────────────────────────────────────────────────────
  const [selectedSummary, setSelectedSummary] = useState<WorkflowVersionSummary | null>(null);
  const [detail, setDetail] = useState<WorkflowVersionDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // ── Restore state ────────────────────────────────────────────────────────────
  const [showConfirm, setShowConfirm] = useState(false);
  const [restoring, setRestoring] = useState(false);

  // Load version list whenever drawer opens.
  useEffect(() => {
    if (!open) return;
    setLoadingList(true);
    setListError(null);
    listWorkflowVersions(campaignId)
      .then((res) => setVersions(res.versions))
      .catch(() => setListError("Failed to load version history."))
      .finally(() => setLoadingList(false));
  }, [open, campaignId]);

  // When a version card is clicked, fetch the full detail.
  function handleSelectVersion(summary: WorkflowVersionSummary) {
    setSelectedSummary(summary);
    setDetail(null);
    setLoadingDetail(true);
    getWorkflowVersion(campaignId, summary.version)
      .then((d) => setDetail(d))
      .catch(() => {
        setSelectedSummary(null);
      })
      .finally(() => setLoadingDetail(false));
  }

  function handleRestoreClick() {
    setShowConfirm(true);
  }

  async function handleConfirmRestore() {
    if (!selectedSummary) return;
    setShowConfirm(false);
    setRestoring(true);
    try {
      const response = await restoreWorkflowVersion(campaignId, selectedSummary.version);
      onRestored(response);
      handleClosePreview();
      onClose();
    } catch {
      setRestoring(false);
    }
  }

  function handleClosePreview() {
    setSelectedSummary(null);
    setDetail(null);
    setLoadingDetail(false);
    setShowConfirm(false);
    setRestoring(false);
  }

  // The current version is the one with the highest version number.
  const currentVersion = versions.length > 0 ? versions[0].version : undefined;

  return (
    <>
      <Sheet open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
        <SheetContent
          side="right"
          className="w-80 p-0 bg-[#0d0d14] border-l border-white/[0.07] text-white flex flex-col gap-0 [&>button]:hidden"
        >
          <SheetHeader className="flex-row items-center gap-2 px-4 py-3 border-b border-white/[0.07] shrink-0 space-y-0">
            <History size={14} className="text-white/40" />
            <SheetTitle className="text-[12px] font-bold uppercase tracking-widest text-white/70 flex-1">
              Version History
            </SheetTitle>
            <button
              onClick={onClose}
              className="text-white/30 hover:text-white/70 transition-colors p-0.5 rounded"
              aria-label="Close"
            >
              <X size={14} />
            </button>
          </SheetHeader>

          <div className="flex-1 overflow-hidden">
            <VersionList
              versions={versions}
              loading={loadingList}
              error={listError}
              currentVersion={currentVersion}
              onSelect={handleSelectVersion}
            />
          </div>

          <div className="px-4 py-3 border-t border-white/[0.05] shrink-0">
            <p className="text-white/20 text-[11px]">
              Versions are created automatically on each save.
            </p>
          </div>
        </SheetContent>
      </Sheet>

      {/* Version preview modal — opens on top of the Sheet */}
      {selectedSummary && (detail || loadingDetail) && (
        <VersionPreviewModal
          detail={
            detail ?? {
              version: selectedSummary.version,
              workflow_id: "",
              nodes: [],
              edges: [],
              created_at: selectedSummary.created_at,
              created_by: selectedSummary.created_by,
            }
          }
          loadingDetail={loadingDetail}
          restoring={restoring}
          onRestore={handleRestoreClick}
          onCancel={handleClosePreview}
        />
      )}

      {/* Confirm restore dialog */}
      <RestoreVersionDialog
        version={selectedSummary?.version ?? 0}
        open={showConfirm}
        onConfirm={handleConfirmRestore}
        onCancel={() => setShowConfirm(false)}
      />
    </>
  );
}
