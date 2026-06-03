import type { PlaybookDetail } from "@/services/playbook";

export const COMPANY_LIMITS = {
  company_name: 120,
  company_intro: 1000,
  company_description: 2000,
  value_proposition: 1000,
} as const;

export const AGENT_NAME_LIMITS = { min: 2, max: 50 } as const;

export const DEFAULT_AGENT_NAME = "AI Assistant";

export function resolveAgentName(detail: PlaybookDetail): string {
  return detail.agent_name?.trim() || DEFAULT_AGENT_NAME;
}

export function validateAgentName(detail: PlaybookDetail): string | null {
  const name = detail.agent_name?.trim() ?? "";
  if (!name) return "Agent Name is required.";
  if (name.length < AGENT_NAME_LIMITS.min) {
    return `Agent Name must be at least ${AGENT_NAME_LIMITS.min} characters.`;
  }
  if (name.length > AGENT_NAME_LIMITS.max) {
    return `Agent Name must be at most ${AGENT_NAME_LIMITS.max} characters.`;
  }
  return null;
}

export function companyFieldsTouched(detail: PlaybookDetail): boolean {
  return Boolean(
    detail.company_name?.trim() ||
      detail.company_intro?.trim() ||
      detail.company_description?.trim() ||
      detail.value_proposition?.trim()
  );
}

export function validateCompanyFields(
  detail: PlaybookDetail
): string | null {
  if (!companyFieldsTouched(detail)) return null;

  if (!detail.company_name?.trim()) {
    return "Company Name is required.";
  }
  if (!detail.company_intro?.trim()) {
    return "Company Introduction is required.";
  }
  if (
    (detail.company_name?.length ?? 0) > COMPANY_LIMITS.company_name
  ) {
    return `Company Name must be at most ${COMPANY_LIMITS.company_name} characters.`;
  }
  if (
    (detail.company_intro?.length ?? 0) > COMPANY_LIMITS.company_intro
  ) {
    return `Company Introduction must be at most ${COMPANY_LIMITS.company_intro} characters.`;
  }
  if (
    (detail.company_description?.length ?? 0) >
    COMPANY_LIMITS.company_description
  ) {
    return `Company Description must be at most ${COMPANY_LIMITS.company_description} characters.`;
  }
  if (
    (detail.value_proposition?.length ?? 0) >
    COMPANY_LIMITS.value_proposition
  ) {
    return `Value Proposition must be at most ${COMPANY_LIMITS.value_proposition} characters.`;
  }
  return null;
}

export function previewOpeningLine(detail: PlaybookDetail): string | null {
  const company = detail.company_name?.trim();
  const agent = resolveAgentName(detail);

  if (detail.opening_line?.trim()) {
    return detail.opening_line
      .replace(/\{agent_name\}/g, agent)
      .replace(/\{company_name\}/g, company || "our company")
      .replace(/\{company\}/g, company || "our company");
  }

  // Auto-generate only when an identity is configured.
  const hasIdentity = Boolean(detail.agent_name?.trim()) || Boolean(company);
  if (!hasIdentity) return null;

  if (company) {
    let line = `Hi, this is ${agent} from ${company}.`;
    const intro = detail.company_intro?.trim();
    if (intro) line = `${line} ${intro}`;
    return line;
  }
  return `Hi, this is ${agent}.`;
}
