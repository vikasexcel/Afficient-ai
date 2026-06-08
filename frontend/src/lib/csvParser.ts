/**
 * Client-side CSV parsing and row-level validation for the lead importer.
 *
 * Mirrors the backend csv_parser.py logic so users see the same validation
 * errors before the file ever hits the API.
 */

import type { ParsedRow, ParsedRowStatus } from "@/types/lead";

// Re-export for consumers that import from here rather than types/lead
export type { ParsedRow, ParsedRowStatus };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_ALLOWED_RE = /^[+\d\s().\-]+$/;

/** Maps canonical column names to common CSV header synonyms (lowercase). */
export const COLUMN_SYNONYMS: Record<string, string[]> = {
  display_name: [
    "display_name",
    "display name",
    "lead_name",
    "lead name",
    "alias",
  ],
  name: [
    "name",
    "full name",
    "full_name",
    "contact",
    "contact name",
    "lead",
  ],
  email: ["email", "email address", "e-mail", "work email"],
  phone: [
    "phone",
    "phone number",
    "mobile",
    "mobile number",
    "cell",
    "contact number",
    "tel",
    "telephone",
  ],
  company: [
    "company",
    "organization",
    "organisation",
    "account",
    "employer",
  ],
  industry: ["industry", "vertical", "sector"],
  location: ["location", "city", "country", "region"],
  tags: ["tags", "labels"],
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ColumnMapping {
  display_name: string | null;
  name: string | null;
  email: string | null;
  phone: string | null;
  company: string | null;
  industry: string | null;
  location: string | null;
  tags: string | null;
  [key: string]: string | null;
}

export interface ValidationSummary {
  total: number;
  valid: number;
  invalid: number;
  duplicate: number;
  missingRequired: number;
  invalidEmails: number;
}

export interface ParseResult {
  rows: ParsedRow[];
  headers: string[];
  columns: ColumnMapping;
  summary: ValidationSummary;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function normalizePhone(raw: string): string {
  return (raw ?? "").replace(/\D/g, "");
}

/** Map CSV headers → canonical column names via synonym lookup. */
export function detectColumns(headers: string[]): ColumnMapping {
  const lowered: Record<string, string> = {};
  for (const h of headers) {
    lowered[h.trim().toLowerCase()] = h;
  }

  const mapping: ColumnMapping = {
    display_name: null,
    name: null,
    email: null,
    phone: null,
    company: null,
    industry: null,
    location: null,
    tags: null,
  };

  for (const [canonical, synonyms] of Object.entries(COLUMN_SYNONYMS)) {
    for (const syn of synonyms) {
      if (syn in lowered) {
        mapping[canonical] = lowered[syn];
        break;
      }
    }
  }

  return mapping;
}

function getValue(
  row: Record<string, string>,
  header: string | null
): string {
  if (!header) return "";
  return (row[header] ?? "").trim();
}

function validateSingleRow(
  raw: Record<string, string>,
  columns: ColumnMapping,
  rowNumber: number
): ParsedRow {
  const display_name = getValue(raw, columns.display_name) || null;
  const name = getValue(raw, columns.name);
  const email = getValue(raw, columns.email);
  const phone = getValue(raw, columns.phone);
  const company = getValue(raw, columns.company) || null;
  const industry = getValue(raw, columns.industry) || null;
  const location = getValue(raw, columns.location) || null;
  const tagsRaw = getValue(raw, columns.tags);
  const tags = tagsRaw
    ? tagsRaw
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
    : null;

  const errors: string[] = [];

  if (!name) {
    errors.push("name is required");
  } else if (name.length > 255) {
    errors.push("name is too long (max 255 chars)");
  }

  if (!phone) {
    errors.push("phone is required");
  } else if (!PHONE_ALLOWED_RE.test(phone)) {
    errors.push("phone contains invalid characters");
  } else {
    const digits = normalizePhone(phone);
    if (digits.length < 7) {
      errors.push("phone is too short (need at least 7 digits)");
    } else if (digits.length > 15) {
      errors.push("phone is too long (max 15 digits)");
    }
  }

  if (email && !EMAIL_RE.test(email)) {
    errors.push("email is not valid");
  }

  // Collect unknown columns as custom_fields.
  const knownHeaders = new Set(
    Object.values(columns).filter(Boolean) as string[]
  );
  const customFields: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (!k || knownHeaders.has(k)) continue;
    const cleaned = (v ?? "").trim();
    if (cleaned) customFields[k.trim()] = cleaned;
  }

  return {
    row_number: rowNumber,
    display_name,
    name: name || null,
    email: email || null,
    phone: phone || null,
    company,
    industry,
    location,
    tags,
    custom_fields: Object.keys(customFields).length ? customFields : null,
    status: errors.length > 0 ? "invalid" : "valid",
    errors,
  };
}

function annotateDuplicates(rows: ParsedRow[]): ParsedRow[] {
  const seen = new Set<string>();
  return rows.map((row) => {
    if (row.status === "invalid") return row;
    const normalized = normalizePhone(row.phone ?? "");
    if (!normalized) return row;
    if (seen.has(normalized)) {
      return {
        ...row,
        status: "duplicate" as ParsedRowStatus,
        errors: [...row.errors, "duplicate phone in this file"],
      };
    }
    seen.add(normalized);
    return row;
  });
}

// ---------------------------------------------------------------------------
// CSV text parser (RFC-4180)
// ---------------------------------------------------------------------------

function parseCSVLine(line: string): string[] {
  const result: string[] = [];
  let current = "";
  let inQuote = false;

  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuote) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          inQuote = false;
        }
      } else {
        current += ch;
      }
    } else {
      if (ch === '"') {
        inQuote = true;
      } else if (ch === ",") {
        result.push(current);
        current = "";
      } else {
        current += ch;
      }
    }
  }
  result.push(current);
  return result.map((v) => v.trim());
}

function parseCSVText(text: string): {
  rows: Record<string, string>[];
  headers: string[];
} {
  const lines = text.split(/\r?\n/);
  let headerLine = "";
  let dataStart = 0;

  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim()) {
      headerLine = lines[i];
      dataStart = i + 1;
      break;
    }
  }

  if (!headerLine) throw new Error("CSV is empty");

  const headers = parseCSVLine(headerLine);
  if (headers.length === 0 || headers.every((h) => !h)) {
    throw new Error("CSV is missing a header row");
  }

  const rows: Record<string, string>[] = [];
  for (let i = dataStart; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    const values = parseCSVLine(line);
    const row: Record<string, string> = {};
    for (let j = 0; j < headers.length; j++) {
      row[headers[j]] = values[j] ?? "";
    }
    if (Object.values(row).every((v) => !v.trim())) continue;
    rows.push(row);
  }

  return { rows, headers };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Full parse → validate → duplicate-annotate pipeline. */
export function processCSV(text: string): ParseResult {
  const { rows: rawRows, headers } = parseCSVText(text);
  const columns = detectColumns(headers);
  let rows = rawRows.map((raw, i) => validateSingleRow(raw, columns, i + 1));
  rows = annotateDuplicates(rows);

  const summary: ValidationSummary = {
    total: rows.length,
    valid: rows.filter((r) => r.status === "valid").length,
    invalid: rows.filter((r) => r.status === "invalid").length,
    duplicate: rows.filter((r) => r.status === "duplicate").length,
    missingRequired: rows.filter((r) =>
      r.errors.some((e) => e.includes("required"))
    ).length,
    invalidEmails: rows.filter((r) =>
      r.errors.some((e) => e.includes("email"))
    ).length,
  };

  return { rows, columns, headers, summary };
}

/** Serialize all rows to a downloadable validation-report CSV string. */
export function generateValidationReport(rows: ParsedRow[]): string {
  const escape = (v: string | number | null | undefined): string => {
    const s = String(v ?? "");
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };

  const lines = [
    ["row", "name", "email", "phone", "company", "status", "errors"].join(","),
    ...rows.map((r) =>
      [
        r.row_number,
        escape(r.name),
        escape(r.email),
        escape(r.phone),
        escape(r.company),
        r.status,
        escape(r.errors.join("; ")),
      ].join(",")
    ),
  ];

  return lines.join("\n") + "\n";
}
