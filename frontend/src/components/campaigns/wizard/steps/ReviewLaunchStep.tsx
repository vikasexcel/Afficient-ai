import {
  Megaphone,
  Users,
  GitBranch,
  CalendarClock,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Globe,
  Workflow,
} from "lucide-react";
import type { WizardDraft } from "../types";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface CardProps {
  icon: React.ElementType;
  iconColor: string;
  iconBg: string;
  title: string;
  status?: "ok" | "warn" | "empty";
  children: React.ReactNode;
}

function ReviewCard({ icon: Icon, iconColor, iconBg, title, status = "ok", children }: CardProps) {
  return (
    <div className="relative rounded-lg border border-white/[0.07] bg-white/[0.02] overflow-hidden transition-all duration-150 hover:border-white/[0.12]">
      {/* Left accent bar */}
      <div className={`absolute left-0 top-0 bottom-0 w-[3px] ${
        status === "warn" ? "bg-amber-500/50" : status === "empty" ? "bg-white/[0.08]" : "bg-violet-600/50"
      }`} />

      <div className="flex gap-3 px-4 py-3 pl-5">
        {/* Icon bubble */}
        <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${iconBg}`}>
          <Icon size={13} className={iconColor} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1.5">
            <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-white/30">
              {title}
            </span>
            {status === "ok" && <CheckCircle2 size={10} className="text-emerald-400/70" />}
            {status === "warn" && <AlertTriangle size={10} className="text-amber-400/70" />}
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-1 last:mb-0">
      <span className="text-[11px] text-white/25 shrink-0 w-16">{label}</span>
      <span className="text-[12px] text-white/80 min-w-0">{value}</span>
    </div>
  );
}

function Tag({ children, color = "violet" }: { children: React.ReactNode; color?: "violet" | "emerald" | "sky" }) {
  const colors = {
    violet: "bg-violet-900/40 text-violet-300 border-violet-700/30",
    emerald: "bg-emerald-900/30 text-emerald-300 border-emerald-700/30",
    sky: "bg-sky-900/30 text-sky-300 border-sky-700/30",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${colors[color]}`}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  draft: WizardDraft;
}

export default function ReviewLaunchStep({ draft }: Props) {
  const scheduleStr = draft.start_immediately
    ? "Immediately on launch"
    : [draft.scheduled_date, draft.scheduled_time].filter(Boolean).join(" at ") || "Not configured";

  const dayLabels = draft.business_hours.days.map(
    (d) => d.charAt(0).toUpperCase() + d.slice(1, 3)
  );

  const hasName = draft.name.trim().length > 0;
  const hasLeadList = !!draft.lead_list_id;
  const hasWorkflow = draft.workflow_nodes.length > 0;

  return (
    <div className="flex flex-col gap-2.5">
      {/* Campaign details */}
      <ReviewCard
        icon={Megaphone}
        iconBg="bg-violet-900/40"
        iconColor="text-violet-300"
        title="Campaign"
        status={hasName ? "ok" : "warn"}
      >
        {hasName ? (
          <Field label="Name" value={<span className="font-semibold text-white">{draft.name}</span>} />
        ) : (
          <p className="text-[12px] text-rose-400/80">Campaign name is required</p>
        )}
        <div className="flex items-center gap-1 mt-0.5">
          <Globe size={10} className="text-white/20" />
          <span className="text-[11px] text-white/35">{draft.timezone}</span>
        </div>
      </ReviewCard>

      {/* Lead list */}
      <ReviewCard
        icon={Users}
        iconBg="bg-sky-900/40"
        iconColor="text-sky-300"
        title="Lead List"
        status={hasLeadList ? "ok" : "warn"}
      >
        {hasLeadList ? (
          <Field
            label="List"
            value={<Tag color="sky">{draft.lead_list_name ?? draft.lead_list_id}</Tag>}
          />
        ) : (
          <p className="text-[12px] text-amber-400/80 flex items-center gap-1.5">
            <AlertTriangle size={11} /> No lead list selected
          </p>
        )}
      </ReviewCard>

      {/* Workflow */}
      <ReviewCard
        icon={hasWorkflow ? Workflow : GitBranch}
        iconBg={hasWorkflow ? "bg-emerald-900/40" : "bg-white/[0.03]"}
        iconColor={hasWorkflow ? "text-emerald-300" : "text-white/20"}
        title="Workflow"
        status={hasWorkflow ? "ok" : "empty"}
      >
        {hasWorkflow ? (
          <>
            {draft.workflow_template_name && (
              <Field label="Template" value={<Tag color="emerald">{draft.workflow_template_name}</Tag>} />
            )}
            <span className="text-[11px] text-white/35">
              {draft.workflow_nodes.length} nodes · {draft.workflow_edges.length} connections
            </span>
          </>
        ) : (
          <p className="text-[11px] text-white/25 italic">
            No workflow — you can build one after creation.
          </p>
        )}
      </ReviewCard>

      {/* Schedule */}
      <ReviewCard
        icon={CalendarClock}
        iconBg="bg-orange-900/40"
        iconColor="text-orange-300"
        title="Schedule"
        status="ok"
      >
        <div className="flex items-center gap-2 mb-1">
          {draft.start_immediately ? (
            <Tag color="violet">Immediate</Tag>
          ) : (
            <span className="text-[12px] text-white/75">{scheduleStr}</span>
          )}
        </div>
        {dayLabels.length > 0 ? (
          <div className="flex items-center gap-1">
            <Clock size={10} className="text-white/20" />
            <span className="text-[11px] text-white/35">
              {dayLabels.join(", ")} · {draft.business_hours.start}–{draft.business_hours.end}
            </span>
          </div>
        ) : (
          <span className="text-[11px] text-white/20 italic">No business hours set</span>
        )}
      </ReviewCard>
    </div>
  );
}
