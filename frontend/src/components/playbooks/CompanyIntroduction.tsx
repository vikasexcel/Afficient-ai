import type { ReactNode } from "react";
import { Building2 } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  AGENT_NAME_LIMITS,
  COMPANY_LIMITS,
  previewOpeningLine,
} from "@/lib/playbookCompany";
import type { PlaybookDetail } from "@/services/playbook";

export type CompanyPatch = Partial<
  Pick<
    PlaybookDetail,
    | "agent_name"
    | "company_name"
    | "company_intro"
    | "company_description"
    | "value_proposition"
    | "opening_line"
  >
>;

const fieldClass =
  "w-full bg-white/[0.04] border border-white/[0.09] rounded-[8px] text-[13px] text-white disabled:opacity-50";

function CharCount({ value, max }: { value: string; max: number }) {
  const n = value.length;
  return (
    <p
      className={`text-[10px] mt-1 ${n > max ? "text-red-400" : "text-white/40"}`}
    >
      {n}/{max}
    </p>
  );
}

export default function CompanyIntroduction({
  detail,
  canEdit,
  onChange,
}: {
  detail: PlaybookDetail;
  canEdit: boolean;
  onChange: (patch: CompanyPatch) => void;
}) {
  const openingPreview = previewOpeningLine(detail);

  return (
    <div className="space-y-4">
      <Field
        label="Agent Name"
        required
        hint="This name will be used when the AI introduces itself during phone calls."
      >
        <Input
          disabled={!canEdit}
          className={fieldClass}
          value={detail.agent_name ?? ""}
          minLength={AGENT_NAME_LIMITS.min}
          maxLength={AGENT_NAME_LIMITS.max}
          onChange={(e) => onChange({ agent_name: e.target.value || null })}
          placeholder="Enter the name the AI should use during calls"
        />
        <CharCount
          value={detail.agent_name ?? ""}
          max={AGENT_NAME_LIMITS.max}
        />
      </Field>

      <Field
        label="Company Name"
        required
        hint="Legal or brand name the agent says on calls."
      >
        <Input
          disabled={!canEdit}
          className={fieldClass}
          value={detail.company_name ?? ""}
          maxLength={COMPANY_LIMITS.company_name}
          onChange={(e) =>
            onChange({ company_name: e.target.value || null })
          }
          placeholder="Tellaigent"
        />
        <CharCount
          value={detail.company_name ?? ""}
          max={COMPANY_LIMITS.company_name}
        />
      </Field>

      <Field
        label="Company Introduction"
        required
        hint="One sentence: what you do and who you help."
      >
        <Textarea
          disabled={!canEdit}
          className={`${fieldClass} min-h-[72px]`}
          rows={2}
          value={detail.company_intro ?? ""}
          maxLength={COMPANY_LIMITS.company_intro}
          onChange={(e) =>
            onChange({ company_intro: e.target.value || null })
          }
          placeholder="We help businesses generate more qualified meetings using AI-powered outbound calling."
        />
        <CharCount
          value={detail.company_intro ?? ""}
          max={COMPANY_LIMITS.company_intro}
        />
      </Field>

      <Field
        label="Company Description"
        hint="Short product or service description."
      >
        <Textarea
          disabled={!canEdit}
          className={`${fieldClass} min-h-[72px]`}
          rows={2}
          value={detail.company_description ?? ""}
          maxLength={COMPANY_LIMITS.company_description}
          onChange={(e) =>
            onChange({ company_description: e.target.value || null })
          }
          placeholder="AI-powered sales development platform that automates prospect outreach and meeting booking."
        />
        <CharCount
          value={detail.company_description ?? ""}
          max={COMPANY_LIMITS.company_description}
        />
      </Field>

      <Field
        label="Value Proposition"
        hint="The outcome or benefit you lead with."
      >
        <Textarea
          disabled={!canEdit}
          className={`${fieldClass} min-h-[72px]`}
          rows={2}
          value={detail.value_proposition ?? ""}
          maxLength={COMPANY_LIMITS.value_proposition}
          onChange={(e) =>
            onChange({ value_proposition: e.target.value || null })
          }
          placeholder="Increase meetings by 3–4× without increasing SDR headcount."
        />
        <CharCount
          value={detail.value_proposition ?? ""}
          max={COMPANY_LIMITS.value_proposition}
        />
      </Field>

      <Field
        label="Custom opening line (optional)"
        hint='Leave blank to auto-generate: "Hi, this is {agent_name} from {company_name}." plus your introduction.'
      >
        <Input
          disabled={!canEdit}
          className={fieldClass}
          value={detail.opening_line ?? ""}
          onChange={(e) =>
            onChange({ opening_line: e.target.value || null })
          }
          placeholder="Hi, this is {agent_name} from {company_name}."
        />
      </Field>

      {openingPreview && (
        <div className="rounded-[8px] border border-white/[0.08] bg-white/[0.02] px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-white/40 mb-1">
            <Building2 size={12} />
            Call opening preview
          </div>
          <p className="text-[12px] text-white/75 leading-relaxed">
            {openingPreview}
          </p>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="text-[12px] text-white/70 block mb-1.5">
        {label}
        {required && <span className="text-red-400/90 ml-0.5">*</span>}
      </label>
      {children}
      {hint && (
        <p className="text-[10px] text-white/40 mt-1 leading-snug">{hint}</p>
      )}
    </div>
  );
}
