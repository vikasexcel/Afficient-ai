import type { PlaybookField, PlaybookFramework } from "@/services/playbook";

/** Default qualification fields per framework (mirrors backend seeds + qualification cues). */
type FieldSpec = {
  key: string;
  display_name: string;
  weight: number;
  required: boolean;
  /** Plain keywords/phrases — rendered as chips. */
  keywords: string[];
  /** Optional advanced regex patterns that don't reduce to a plain keyword. */
  advanced?: string[];
};

const BANT_SPECS: FieldSpec[] = [
  {
    key: "budget",
    display_name: "Budget",
    weight: 2,
    required: true,
    keywords: [
      "budget",
      "spend",
      "spending",
      "afford",
      "price",
      "pricing",
      "cost",
      "costs",
      "dollars",
      "euros",
      "pounds",
      "quote",
      "quotation",
    ],
    advanced: [String.raw`\$\s*\d`],
  },
  {
    key: "authority",
    display_name: "Authority",
    weight: 2,
    required: true,
    keywords: [
      "decision maker",
      "decision-maker",
      "decide",
      "approve",
      "approver",
      "sign off",
      "sign-off",
      "ceo",
      "cto",
      "cfo",
      "coo",
      "vp",
      "director",
      "head of",
      "owner",
      "my team",
      "my boss",
      "report to",
      "reports to",
      "i decide",
      "i approve",
      "i own",
    ],
  },
  {
    key: "need",
    display_name: "Need",
    weight: 2,
    required: true,
    keywords: [
      "problem",
      "pain",
      "challenge",
      "struggle",
      "issue",
      "frustrated",
      "frustrating",
      "bottleneck",
      "looking for",
      "need",
      "needed",
      "require",
      "trying to",
      "replace",
      "upgrade",
      "switch from",
    ],
  },
  {
    key: "timeline",
    display_name: "Timeline",
    weight: 1,
    required: false,
    keywords: [
      "this week",
      "this month",
      "this quarter",
      "this year",
      "next week",
      "next month",
      "next quarter",
      "next year",
      "q1",
      "q2",
      "q3",
      "q4",
      "h1",
      "h2",
      "asap",
      "immediately",
      "urgent",
      "today",
      "tomorrow",
    ],
    advanced: [
      String.raw`\b(by|before|after) \w+`,
      String.raw`\b\d{1,2} (days?|weeks?|months?)\b`,
    ],
  },
];

const MEDDICC_SPECS: FieldSpec[] = [
  {
    key: "metrics",
    display_name: "Metrics",
    weight: 2,
    required: true,
    keywords: [
      "roi",
      "kpi",
      "metric",
      "measure",
      "increase",
      "reduce",
      "save",
      "cut",
    ],
    advanced: [
      String.raw`\b\d+\s*(%|percent|x|hours?|days?|users?|calls?|leads?)\b`,
    ],
  },
  {
    key: "economic_buyer",
    display_name: "Economic Buyer",
    weight: 2,
    required: true,
    keywords: [
      "ceo",
      "cfo",
      "coo",
      "vp",
      "head of finance",
      "controller",
      "budget owner",
      "signs the cheque",
      "signs the check",
      "signs the contract",
      "approves the spend",
    ],
  },
  {
    key: "decision_criteria",
    display_name: "Decision Criteria",
    weight: 1,
    required: false,
    keywords: [
      "criteria",
      "requirement",
      "must have",
      "must-have",
      "nice to have",
      "nice-to-have",
      "evaluate",
      "evaluating",
      "compare",
      "comparing",
      "shortlist",
      "rfp",
      "rfi",
    ],
  },
  {
    key: "decision_process",
    display_name: "Decision Process",
    weight: 1,
    required: false,
    keywords: [
      "process",
      "steps",
      "stakeholder",
      "stakeholders",
      "procurement",
      "legal",
      "security review",
      "timeline",
      "kickoff",
      "go live",
      "go-live",
      "onboarding",
    ],
  },
  {
    key: "identify_pain",
    display_name: "Identify Pain",
    weight: 2,
    required: true,
    keywords: [
      "pain",
      "problem",
      "issue",
      "risk",
      "losing",
      "costing",
      "wasting",
      "broken",
    ],
  },
  {
    key: "champion",
    display_name: "Champion",
    weight: 1,
    required: false,
    keywords: [
      "champion",
      "advocate",
      "internal sponsor",
      "on my side",
      "will push for",
    ],
  },
  {
    key: "competition",
    display_name: "Competition",
    weight: 1,
    required: false,
    keywords: [
      "competitor",
      "alternative",
      "currently using",
      "in-house",
      "in house",
      "build vs buy",
      "also looking at",
      "also evaluating",
    ],
  },
];

function specsToFields(specs: FieldSpec[]): PlaybookField[] {
  return specs.map((s, i) => ({
    key: s.key,
    display_name: s.display_name,
    weight: s.weight,
    required: s.required,
    cue_patterns: [
      ...s.keywords.map((k) => keywordToPattern(k)).filter(Boolean),
      ...(s.advanced ?? []),
    ],
    position: i,
  }));
}

export function defaultFieldsForFramework(
  framework: PlaybookFramework
): PlaybookField[] {
  if (framework === "BANT") return specsToFields(BANT_SPECS);
  if (framework === "MEDDICC") return specsToFields(MEDDICC_SPECS);
  return [];
}

export function defaultFieldKeys(framework: PlaybookFramework): string[] {
  return defaultFieldsForFramework(framework).map((f) => f.key);
}

/** True when current fields match the canonical keys for BANT or MEDDICC. */
export function fieldsMatchFramework(
  fields: PlaybookField[],
  framework: PlaybookFramework
): boolean {
  if (framework === "CUSTOM") return fields.length === 0;
  const expected = defaultFieldKeys(framework).sort().join(",");
  const actual = fields
    .map((f) => f.key)
    .sort()
    .join(",");
  return expected === actual;
}

/** Whether changing framework should offer to replace the field list. */
export function shouldReplaceFieldsOnFrameworkChange(
  fields: PlaybookField[],
  currentFramework: PlaybookFramework,
  newFramework: PlaybookFramework
): boolean {
  if (newFramework === currentFramework) return false;
  if (newFramework === "CUSTOM") return fields.length > 0;
  return !fieldsMatchFramework(fields, newFramework);
}

export function frameworkSwitchMessage(
  framework: PlaybookFramework
): string {
  if (framework === "CUSTOM") {
    return "Switch to CUSTOM? Qualification fields will be cleared so you can define your own.";
  }
  const n = defaultFieldsForFramework(framework).length;
  return `Switch to ${framework}? Qualification fields will be replaced with ${n} default ${framework} fields.`;
}

/* ---------------------------------------------------------------------------
 * Cue pattern helpers — let users edit keywords, not regex.
 *
 * Backend lowercases the user turn before matching, so a plain keyword
 * "budget" compiles to `\bbudget\b`. Multi-word phrases are escaped the same
 * way ("VP of Sales" → `\bvp of sales\b`).
 * ---------------------------------------------------------------------------
 */

const REGEX_METACHARS = /[\\^$.*+?()[\]{}|]/;
const KEYWORD_PATTERN_RE = /^\\b([a-z0-9 _\-']+)\\b$/;

function escapeRegex(s: string): string {
  return s.replace(/[\\^$.*+?()[\]{}|]/g, "\\$&");
}

/** Convert a plain keyword/phrase into a backend-ready regex. */
export function keywordToPattern(keyword: string): string {
  const trimmed = keyword.trim().toLowerCase();
  if (!trimmed) return "";
  return `\\b${escapeRegex(trimmed)}\\b`;
}

/** Extract a keyword from a simple `\b...\b` pattern; null if it's a real regex. */
export function patternToKeyword(pattern: string): string | null {
  const m = KEYWORD_PATTERN_RE.exec(pattern.trim());
  return m ? m[1] : null;
}

/** True when the pattern uses regex features beyond a plain keyword. */
export function isAdvancedPattern(pattern: string): boolean {
  if (patternToKeyword(pattern) !== null) return false;
  return REGEX_METACHARS.test(pattern);
}

export type SplitPatterns = {
  keywords: string[];
  advanced: string[];
};

export function splitPatterns(patterns: string[]): SplitPatterns {
  const keywords: string[] = [];
  const advanced: string[] = [];
  for (const p of patterns) {
    const kw = patternToKeyword(p);
    if (kw !== null) keywords.push(kw);
    else advanced.push(p);
  }
  return { keywords, advanced };
}

export function joinPatterns(parts: SplitPatterns): string[] {
  const fromKeywords = parts.keywords
    .map((k) => keywordToPattern(k))
    .filter(Boolean);
  return [...fromKeywords, ...parts.advanced];
}
