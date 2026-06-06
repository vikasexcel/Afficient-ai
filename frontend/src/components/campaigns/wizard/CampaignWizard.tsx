/**
 * CampaignWizard — multi-step campaign creation flow.
 *
 * Steps:
 *   1. Campaign Details  — name + timezone
 *   2. Lead List         — pick one lead list
 *   3. Workflow          — choose template or skip
 *   4. Schedule          — start time + business hours
 *   5. Review & Launch   — summary + Save Draft / Launch
 *
 * Draft is persisted to localStorage so closing and reopening restores progress.
 * Cleared after a successful save or launch.
 */
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Loader2, Rocket, Save } from "lucide-react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  createCampaign,
  activateCampaign,
} from "@/services/campaign";
import { saveWorkflow } from "@/services/workflow";
import type { WorkflowGraph } from "@/types/workflow";

import {
  defaultDraft,
  DRAFT_STORAGE_KEY,
  WIZARD_STEPS,
  type WizardDraft,
} from "./types";
import CampaignDetailsStep from "./steps/CampaignDetailsStep";
import LeadListStep from "./steps/LeadListStep";
import WorkflowStep from "./steps/WorkflowStep";
import ScheduleStep from "./steps/ScheduleStep";
import ReviewLaunchStep from "./steps/ReviewLaunchStep";

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

function canProceed(step: number, draft: WizardDraft): boolean {
  switch (step) {
    case 1:
      return draft.name.trim().length > 0;
    case 2:
      return draft.lead_list_id !== null;
    case 3:
      return true; // workflow is optional
    case 4: {
      if (draft.start_immediately) return true;
      if (!draft.scheduled_date) return false;
      const pastError = draft.scheduled_date < new Date().toISOString().slice(0, 10);
      return !pastError;
    }
    default:
      return true;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadDraft(): WizardDraft {
  try {
    const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
    if (raw) return { ...defaultDraft(), ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return defaultDraft();
}

function persistDraft(draft: WizardDraft) {
  try {
    localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
  } catch {
    /* ignore */
  }
}

function clearDraft() {
  try {
    localStorage.removeItem(DRAFT_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// Progress indicator
// ---------------------------------------------------------------------------

function ProgressIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-0 shrink-0">
      {WIZARD_STEPS.map((step, i) => {
        const done = current > step.id;
        const active = current === step.id;
        return (
          <div key={step.id} className="flex items-center">
            <div className="flex items-center gap-1.5">
              <div
                className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold transition-colors ${
                  done
                    ? "bg-violet-600 text-white"
                    : active
                    ? "bg-violet-600/30 border border-violet-500 text-violet-300"
                    : "bg-white/5 border border-white/10 text-white/25"
                }`}
              >
                {done ? "✓" : step.id}
              </div>
              <span
                className={`text-[11px] font-medium hidden sm:inline transition-colors ${
                  active ? "text-white/80" : done ? "text-violet-400/70" : "text-white/25"
                }`}
              >
                {step.label}
              </span>
            </div>
            {i < WIZARD_STEPS.length - 1 && (
              <div className={`w-6 h-px mx-1.5 ${done ? "bg-violet-600/50" : "bg-white/10"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main wizard
// ---------------------------------------------------------------------------

interface Props {
  onClose: () => void;
  onCreated: () => void;
}

export default function CampaignWizard({ onClose, onCreated }: Props) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState<WizardDraft>(loadDraft);
  const [submitting, setSubmitting] = useState(false);

  // Sync draft to localStorage on every change.
  useEffect(() => {
    persistDraft(draft);
  }, [draft]);

  function update(partial: Partial<WizardDraft>) {
    setDraft((d) => ({ ...d, ...partial }));
  }

  // ── Navigation ─────────────────────────────────────────────────────────────

  function next() {
    if (step < 5) setStep((s) => s + 1);
  }

  function back() {
    if (step > 1) setStep((s) => s - 1);
  }

  // ── API submission ─────────────────────────────────────────────────────────

  async function submit(launch: boolean) {
    if (submitting) return;
    setSubmitting(true);
    try {
      // 1. Create campaign (always as draft first so we can attach the workflow)
      const campaignPayload = {
        name: draft.name.trim(),
        playbook_id: null,
        lead_list_id: draft.lead_list_id,
        schedule: {
          start_immediately: draft.start_immediately,
          date: draft.scheduled_date,
          time: draft.scheduled_time,
          timezone: draft.timezone,
        },
        business_hours: draft.business_hours,
        launch: false, // always create as draft first
      };
      const created = await createCampaign(campaignPayload);
      const campaignId = created.id;

      // 2. Save workflow if nodes were selected.
      if (draft.workflow_nodes.length > 0) {
        await saveWorkflow(campaignId, {
          nodes: draft.workflow_nodes,
          edges: draft.workflow_edges,
        } as WorkflowGraph);
      }

      // 3. Activate if requested.
      if (launch) {
        const activation = await activateCampaign(campaignId);
        if (activation.scheduled) {
          toast.success(`Campaign scheduled`);
        } else {
          const n = activation.enqueued_leads ?? 0;
          toast.success(
            `"${draft.name}" launched` +
              (n ? ` · ${n} lead${n === 1 ? "" : "s"} queued` : "")
          );
        }
      } else {
        toast.success(`"${draft.name}" saved as draft`);
      }

      clearDraft();
      onCreated();
      onClose();
      navigate(`/campaigns`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const ok = canProceed(step, draft);
  const isLast = step === 5;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-white/[0.07] shrink-0">
        <ProgressIndicator current={step} />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {step === 1 && <CampaignDetailsStep draft={draft} onChange={update} />}
        {step === 2 && <LeadListStep draft={draft} onChange={update} />}
        {step === 3 && <WorkflowStep draft={draft} onChange={update} />}
        {step === 4 && <ScheduleStep draft={draft} onChange={update} />}
        {step === 5 && <ReviewLaunchStep draft={draft} />}
      </div>

      {/* Footer navigation */}
      <div className="flex items-center justify-between px-6 py-4 border-t border-white/[0.07] shrink-0">
        <Button
          variant="ghost"
          onClick={step === 1 ? onClose : back}
          disabled={submitting}
          className="text-white/50 hover:text-white"
        >
          {step === 1 ? "Cancel" : (
            <>
              <ArrowLeft size={13} className="mr-1" /> Back
            </>
          )}
        </Button>

        <div className="flex items-center gap-2">
          {isLast ? (
            <>
              <Button
                variant="ghost"
                onClick={() => void submit(false)}
                disabled={submitting || !draft.name.trim() || !draft.lead_list_id}
                className="text-white/60 hover:text-white border border-white/10 h-8 px-4"
              >
                {submitting ? (
                  <Loader2 size={13} className="animate-spin mr-1" />
                ) : (
                  <Save size={13} className="mr-1" />
                )}
                Save Draft
              </Button>
              <Button
                onClick={() => void submit(true)}
                disabled={submitting || !draft.name.trim() || !draft.lead_list_id}
                className="bg-violet-600 hover:bg-violet-500 text-white h-8 px-4"
              >
                {submitting ? (
                  <Loader2 size={13} className="animate-spin mr-1" />
                ) : (
                  <Rocket size={13} className="mr-1" />
                )}
                Launch Campaign
              </Button>
            </>
          ) : (
            <Button
              onClick={next}
              disabled={!ok}
              className="bg-violet-600 hover:bg-violet-500 text-white h-8 px-5 disabled:opacity-40"
            >
              Next <ArrowRight size={13} className="ml-1" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
