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
import {
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  GitBranch,
  Loader2,
  Megaphone,
  Rocket,
  Save,
  Users,
  X,
} from "lucide-react";
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

function inferCampaignPlaybookId(nodes: unknown[]): string | null {
  for (const node of nodes) {
    if (!node || typeof node !== "object") continue;
    const record = node as Record<string, unknown>;
    if (record.type !== "CALL") continue;

    const config = record.config;
    if (config && typeof config === "object") {
      const playbookId = (config as Record<string, unknown>).playbook_id;
      if (typeof playbookId === "string" && playbookId.trim()) {
        return playbookId;
      }
    }

    const playbookId = record.playbook_id;
    if (typeof playbookId === "string" && playbookId.trim()) {
      return playbookId;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Step icons
// ---------------------------------------------------------------------------

const STEP_ICONS = [Megaphone, Users, GitBranch, CalendarClock, CheckCircle2];

// ---------------------------------------------------------------------------
// Progress indicator
// ---------------------------------------------------------------------------

function ProgressIndicator({ current }: { current: number }) {
  return (
    <div className="relative flex items-start justify-between w-full">
      {/* Background track */}
      <div className="absolute top-4 left-4 right-4 h-px bg-white/[0.07]" />
      {/* Filled track */}
      <div
        className="absolute top-4 left-4 h-px bg-violet-600/50 transition-all duration-500"
        style={{ width: `calc(${((current - 1) / (WIZARD_STEPS.length - 1)) * 100}% - 8px)` }}
      />

      {WIZARD_STEPS.map((step, i) => {
        const done = current > step.id;
        const active = current === step.id;
        const Icon = STEP_ICONS[i];
        return (
          <div key={step.id} className="relative flex flex-col items-center gap-2 z-10">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center transition-all duration-200 ${
                done
                  ? "bg-violet-600 shadow-md shadow-violet-900/60"
                  : active
                  ? "bg-violet-600/25 border-2 border-violet-500"
                  : "bg-[#13131f] border border-white/[0.10]"
              }`}
            >
              {done ? (
                <CheckCircle2 size={13} className="text-white" />
              ) : (
                <Icon size={13} className={active ? "text-violet-300" : "text-white/20"} />
              )}
            </div>
            <span
              className={`text-[10px] font-semibold whitespace-nowrap transition-colors ${
                active
                  ? "text-violet-300"
                  : done
                  ? "text-violet-400/50"
                  : "text-white/18"
              }`}
              style={{ color: active ? undefined : done ? "rgba(167,139,250,0.5)" : "rgba(255,255,255,0.18)" }}
            >
              {step.label}
            </span>
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
        playbook_id: inferCampaignPlaybookId(draft.workflow_nodes),
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

  const stepLabel = step === 5 ? "Review & Launch" : (WIZARD_STEPS[step - 1]?.label ?? "");

  return (
    <div className="flex flex-col h-full">
      {/* Gradient hero header */}
      <div className="relative shrink-0 bg-gradient-to-b from-violet-950/50 to-[#0a0a12] border-b border-white/[0.06]">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute right-4 top-4 text-white/25 hover:text-white/70 transition-colors p-1 rounded-md hover:bg-white/[0.06]"
        >
          <X size={15} />
        </button>

        {/* Title row */}
        <div className="px-7 pt-5 pb-1">
          <div className="flex items-center gap-1.5 mb-1">
            <Megaphone size={13} className="text-violet-400/80" />
            <span className="text-[10px] text-violet-400/60 uppercase tracking-widest font-bold">
              New Campaign · Step {step} of {WIZARD_STEPS.length}
            </span>
          </div>
          <h1 className="text-[18px] font-bold text-white tracking-tight leading-tight">
            {stepLabel}
          </h1>
        </div>

        {/* Progress steps */}
        <div className="px-7 pt-4 pb-5">
          <ProgressIndicator current={step} />
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-7 py-5">
        {step === 1 && <CampaignDetailsStep draft={draft} onChange={update} />}
        {step === 2 && <LeadListStep draft={draft} onChange={update} />}
        {step === 3 && <WorkflowStep draft={draft} onChange={update} />}
        {step === 4 && <ScheduleStep draft={draft} onChange={update} />}
        {step === 5 && <ReviewLaunchStep draft={draft} />}
      </div>

      {/* Footer */}
      {isLast ? (
        /* ── Review & Launch footer ── */
        <div className="shrink-0 border-t border-white/[0.06]">
          {/* Action row */}
          <div className="px-7 pt-4 pb-3 flex flex-col gap-3">
            {/* Primary CTA — Launch Campaign */}
            <button
              onClick={() => void submit(true)}
              disabled={submitting || !draft.name.trim() || !draft.lead_list_id}
              className={`
                relative w-full h-11 rounded-xl font-semibold text-[14px] tracking-wide
                flex items-center justify-center gap-2
                transition-all duration-150
                disabled:opacity-40 disabled:cursor-not-allowed disabled:pointer-events-none
                ${!submitting && draft.name.trim() && draft.lead_list_id
                  ? "bg-gradient-to-r from-violet-600 to-violet-500 hover:from-violet-500 hover:to-violet-400 active:from-violet-700 active:to-violet-600 text-white shadow-lg shadow-violet-900/50 hover:shadow-violet-700/40 hover:shadow-xl"
                  : "bg-violet-700/40 text-white/40"
                }
              `}
            >
              {submitting ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Rocket size={16} />
              )}
              {submitting ? "Launching…" : "Launch Campaign"}
            </button>

            {/* Secondary — Save Draft */}
            <button
              onClick={() => void submit(false)}
              disabled={submitting || !draft.name.trim() || !draft.lead_list_id}
              className="
                w-full h-10 rounded-xl font-medium text-[13px]
                flex items-center justify-center gap-2
                border border-white/[0.10] bg-white/[0.03]
                text-white/55 hover:text-white/85
                hover:border-white/[0.18] hover:bg-white/[0.06]
                active:bg-white/[0.03]
                transition-all duration-150
                disabled:opacity-40 disabled:cursor-not-allowed disabled:pointer-events-none
              "
            >
              {submitting ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Save size={14} className="text-white/40" />
              )}
              Save Draft
            </button>
          </div>

          {/* Back link + validation note */}
          <div className="px-7 pb-4 flex items-center justify-between">
            <button
              onClick={back}
              disabled={submitting}
              className="flex items-center gap-1.5 text-[12px] text-white/30 hover:text-white/60 transition-colors disabled:opacity-40"
            >
              <ArrowLeft size={12} /> Back to Schedule
            </button>
            {(!draft.name.trim() || !draft.lead_list_id) && (
              <span className="text-[11px] text-amber-400/60 flex items-center gap-1">
                <span className="w-1 h-1 rounded-full bg-amber-400/60 inline-block" />
                {!draft.name.trim() ? "Campaign name required" : "Lead list required"}
              </span>
            )}
          </div>
        </div>
      ) : (
        /* ── Steps 1–4 footer ── */
        <div className="flex items-center justify-between px-7 py-4 border-t border-white/[0.06] bg-white/[0.01] shrink-0">
          <Button
            variant="ghost"
            onClick={step === 1 ? onClose : back}
            disabled={submitting}
            className="text-white/35 hover:text-white/70 hover:bg-white/[0.05] h-9 px-3 gap-1.5 text-[13px]"
          >
            {step === 1 ? "Cancel" : <><ArrowLeft size={13} /> Back</>}
          </Button>

          {/* Step dots */}
          <div className="flex items-center gap-1.5">
            {WIZARD_STEPS.map((s) => (
              <div
                key={s.id}
                className={`rounded-full transition-all duration-200 ${
                  s.id === step
                    ? "w-5 h-1.5 bg-violet-500"
                    : s.id < step
                    ? "w-1.5 h-1.5 bg-violet-600/50"
                    : "w-1.5 h-1.5 bg-white/10"
                }`}
              />
            ))}
          </div>

          <Button
            onClick={next}
            disabled={!ok}
            className="bg-violet-600 hover:bg-violet-500 active:bg-violet-700 text-white h-9 px-5 gap-1.5 text-[13px] font-medium shadow-md shadow-violet-900/30 disabled:opacity-40 rounded-lg"
          >
            Continue <ArrowRight size={13} />
          </Button>
        </div>
      )}
    </div>
  );
}
