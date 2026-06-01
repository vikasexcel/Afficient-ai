import type {
  PlaybookFramework,
  PlaybookStatus,
} from "@/services/playbook";

export const FRAMEWORK_META: Record<
  PlaybookFramework,
  { label: string; tagline: string; subtitle: string; accent: string }
> = {
  BANT: {
    label: "BANT",
    tagline: "Budget · Authority · Need · Timeline",
    subtitle: "Lightweight 4-field qualification for outbound SDRs.",
    accent: "violet",
  },
  MEDDICC: {
    label: "MEDDICC",
    tagline: "Metrics · Economic Buyer · Pain · Champion · …",
    subtitle: "Rigorous 7-field framework for enterprise sales.",
    accent: "sky",
  },
  CUSTOM: {
    label: "Custom",
    tagline: "Your own fields",
    subtitle: "Bring-your-own qualification for support, intake, recruiting, etc.",
    accent: "emerald",
  },
};

export const FRAMEWORK_PILL_CLASS: Record<PlaybookFramework, string> = {
  BANT: "bg-violet-500/10 text-violet-200 border-violet-400/25",
  MEDDICC: "bg-sky-500/10 text-sky-200 border-sky-400/25",
  CUSTOM: "bg-emerald-500/10 text-emerald-200 border-emerald-400/25",
};

export const STATUS_META: Record<
  PlaybookStatus,
  { label: string; pill: string; description: string }
> = {
  draft: {
    label: "Draft",
    pill: "bg-amber-500/10 text-amber-200 border-amber-400/25",
    description: "Editable. Not yet used by any call.",
  },
  active: {
    label: "Live",
    pill: "bg-emerald-500/10 text-emerald-200 border-emerald-400/25",
    description: "Published version is being used by calls.",
  },
  archived: {
    label: "Archived",
    pill: "bg-white/10 text-white/50 border-white/15",
    description: "Hidden from default lists. Calls already in flight keep using their snapshot.",
  },
};

export const QUAL_STATUS_META: Record<
  string,
  { label: string; pill: string }
> = {
  not_started: {
    label: "Not started",
    pill: "bg-white/10 text-white/60 border-white/15",
  },
  in_progress: {
    label: "In progress",
    pill: "bg-amber-500/10 text-amber-200 border-amber-400/25",
  },
  qualified: {
    label: "Qualified",
    pill: "bg-emerald-500/10 text-emerald-200 border-emerald-400/25",
  },
  disqualified: {
    label: "Disqualified",
    pill: "bg-rose-500/10 text-rose-200 border-rose-400/25",
  },
};

const PERSONA_LABELS: Record<string, string> = {
  outbound_sdr: "Outbound SDR",
  appointment_setter: "Appointment Setter",
  support_triage: "Support Triage",
};

export function personaLabel(name: string): string {
  return (
    PERSONA_LABELS[name] ??
    name
      .split("_")
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ")
  );
}

/** Slugify a display name into a stable field key. */
export function deriveFieldKey(displayName: string): string {
  const slug = displayName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_\s-]+/g, "")
    .replace(/[\s-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug || "field";
}
