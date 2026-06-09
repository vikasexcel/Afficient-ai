/**
 * WorkflowToolbar — top bar with Save / Validate actions and status display.
 */
import { CheckCircle2, History, LayoutTemplate, Loader2, Save, ShieldCheck, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ValidationState {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

interface WorkflowToolbarProps {
  campaignName?: string;
  saving: boolean;
  validating: boolean;
  validation: ValidationState | null;
  hasUnsavedChanges: boolean;
  readOnly?: boolean;
  onSave: () => void;
  onValidate: () => void;
  onOpenTemplates: () => void;
  onOpenHistory: () => void;
}

/**
 * Renders as a React fragment — embed inside any flex container.
 * WorkflowBuilder owns the outer div / height / border.
 */
export default function WorkflowToolbar({
  campaignName,
  saving,
  validating,
  validation,
  hasUnsavedChanges,
  readOnly = false,
  onSave,
  onValidate,
  onOpenTemplates,
  onOpenHistory,
}: WorkflowToolbarProps) {
  return (
    <>
      {/* Campaign context */}
      {campaignName && (
        <span className="text-[13px] text-white/50 truncate max-w-[200px]">
          {campaignName}
        </span>
      )}
      {campaignName && <span className="text-white/20 text-xs">/</span>}
      <span className="text-[13px] text-white/80 font-medium">
        Workflow Builder
      </span>

      {!readOnly && hasUnsavedChanges && (
        <span className="text-[10px] text-amber-400/70 font-medium ml-1">
          unsaved changes
        </span>
      )}

      <div className="ml-auto flex items-center gap-2">
        {/* Validation badge */}
        {validation && (
          <div className="flex items-center gap-1.5 mr-2">
            {validation.valid ? (
              <span className="flex items-center gap-1 text-[11px] text-emerald-400">
                <CheckCircle2 size={12} /> Valid
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[11px] text-rose-400">
                <XCircle size={12} />
                {validation.errors.length} error
                {validation.errors.length !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        )}

        {/* Templates */}
        <Button
          variant="ghost"
          size="sm"
          onClick={onOpenTemplates}
          className="text-white/60 hover:text-white text-[12px] h-7"
        >
          <LayoutTemplate size={12} className="mr-1" />
          Templates
        </Button>

        {/* History */}
        <Button
          variant="ghost"
          size="sm"
          onClick={onOpenHistory}
          className="text-white/60 hover:text-white text-[12px] h-7"
        >
          <History size={12} className="mr-1" />
          History
        </Button>

        {/* Validate */}
        <Button
          variant="ghost"
          size="sm"
          onClick={onValidate}
          disabled={validating || saving}
          className="text-white/60 hover:text-white text-[12px] h-7"
        >
          {validating ? (
            <Loader2 size={12} className="animate-spin mr-1" />
          ) : (
            <ShieldCheck size={12} className="mr-1" />
          )}
          Validate
        </Button>

        {/* Save */}
        <Button
          size="sm"
          onClick={onSave}
          disabled={saving || validating || readOnly}
          title={readOnly ? "Campaign is completed — workflow is read-only" : undefined}
          className="bg-violet-600 hover:bg-violet-500 text-white text-[12px] h-7 px-3 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? (
            <Loader2 size={12} className="animate-spin mr-1" />
          ) : (
            <Save size={12} className="mr-1" />
          )}
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </>
  );
}

/** Expandable validation error panel shown below the toolbar. */
export function ValidationPanel({
  validation,
  onDismiss,
}: {
  validation: ValidationState;
  onDismiss: () => void;
}) {
  if (!validation.errors.length && !validation.warnings.length) return null;

  return (
    <div className="border-b border-white/[0.07] bg-[#0f0f17] px-4 py-2 space-y-1 shrink-0">
      {validation.errors.map((e, i) => (
        <div key={i} className="flex items-start gap-1.5 text-[12px] text-rose-400">
          <XCircle size={12} className="mt-0.5 shrink-0" />
          {e}
        </div>
      ))}
      {validation.warnings.map((w, i) => (
        <div key={i} className="flex items-start gap-1.5 text-[12px] text-amber-400">
          <CheckCircle2 size={12} className="mt-0.5 shrink-0" />
          {w}
        </div>
      ))}
      <button
        onClick={onDismiss}
        className="text-[11px] text-white/30 hover:text-white/60 mt-0.5"
      >
        Dismiss
      </button>
    </div>
  );
}
