import {
  Megaphone,
  Users,
  GitBranch,
  Clock,
  CheckCircle2,
} from "lucide-react";
import type { WizardDraft } from "../types";

interface SectionProps {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}

function Section({ icon: Icon, title, children }: SectionProps) {
  return (
    <div className="flex gap-3 p-4 rounded-lg border border-white/[0.07] bg-white/[0.03]">
      <Icon size={15} className="text-white/30 shrink-0 mt-0.5" />
      <div className="flex flex-col gap-1.5 min-w-0">
        <p className="text-[11px] text-white/35 uppercase tracking-widest">{title}</p>
        {children}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2 items-baseline">
      <span className="text-[12px] text-white/40 shrink-0">{label}:</span>
      <span className="text-[13px] text-white/80 truncate">{value}</span>
    </div>
  );
}

interface Props {
  draft: WizardDraft;
}

export default function ReviewLaunchStep({ draft }: Props) {
  const scheduleStr = draft.start_immediately
    ? "Immediately on launch"
    : [draft.scheduled_date, draft.scheduled_time].filter(Boolean).join(" ") ||
      "Not configured";

  const bhStr = draft.business_hours.days.length
    ? `${draft.business_hours.days.map((d) => d.charAt(0).toUpperCase() + d.slice(1)).join(", ")} · ${draft.business_hours.start}–${draft.business_hours.end}`
    : "No days selected";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-base font-semibold text-white">Review &amp; Launch</h2>
        <p className="text-[13px] text-white/40 mt-0.5">
          Review your campaign settings before saving or launching.
        </p>
      </div>

      <div className="flex flex-col gap-3">
        {/* Campaign Details */}
        <Section icon={Megaphone} title="Campaign">
          <Row label="Name" value={draft.name || <span className="text-rose-400/70">Not set</span>} />
          <Row label="Timezone" value={draft.timezone} />
        </Section>

        {/* Lead List */}
        <Section icon={Users} title="Lead List">
          {draft.lead_list_id ? (
            <>
              <Row label="Name" value={draft.lead_list_name ?? draft.lead_list_id} />
              {draft.lead_count != null && (
                <Row
                  label="Estimated leads"
                  value={
                    <span className="flex items-center gap-1 text-emerald-400">
                      <CheckCircle2 size={11} />
                      {draft.lead_count.toLocaleString()}
                    </span>
                  }
                />
              )}
            </>
          ) : (
            <p className="text-[12px] text-amber-400/70">No lead list selected</p>
          )}
        </Section>

        {/* Workflow */}
        <Section icon={GitBranch} title="Workflow">
          {draft.workflow_nodes.length > 0 ? (
            <>
              {draft.workflow_template_name && (
                <Row label="Template" value={draft.workflow_template_name} />
              )}
              <Row label="Nodes" value={draft.workflow_nodes.length} />
              <Row label="Connections" value={draft.workflow_edges.length} />
            </>
          ) : (
            <p className="text-[12px] text-white/35">
              No workflow — you can build it in Workflow Builder after creation.
            </p>
          )}
        </Section>

        {/* Schedule */}
        <Section icon={Clock} title="Schedule">
          <Row label="Start" value={scheduleStr} />
          <Row label="Business hours" value={bhStr} />
        </Section>
      </div>
    </div>
  );
}
