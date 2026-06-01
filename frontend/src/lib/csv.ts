import type { ParsedRow } from "@/types/lead";

/* Minimal RFC-4180 escape — quotes are doubled, fields are wrapped only */
/* when they contain a comma, quote, or line break.                       */
function escapeCsvField(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export function toCsv(headers: string[], rows: (string | number | null)[][]): string {
  const out: string[] = [headers.map(escapeCsvField).join(",")];
  for (const row of rows) {
    out.push(row.map(escapeCsvField).join(","));
  }
  return out.join("\n") + "\n";
}

export function downloadText(filename: string, body: string, mime = "text/csv") {
  const blob = new Blob([body], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Sample CSV the user can download to bootstrap their import. */
export const SAMPLE_LEAD_CSV = toCsv(
  ["name", "email", "phone", "company", "industry", "location", "tags"],
  [
    [
      "Aarav Sharma",
      "aarav@northwindlabs.com",
      "+1 415 555 0188",
      "Northwind Labs",
      "SaaS",
      "San Francisco, CA",
      "warm,demo-requested",
    ],
    [
      "Priya Iyer",
      "priya@brightpath.io",
      "+91 98201 12345",
      "Brightpath",
      "Fintech",
      "Mumbai, IN",
      "outbound,t2",
    ],
    [
      "Daniel Cohen",
      "dan@helio-energy.com",
      "+44 20 7946 0958",
      "Helio Energy",
      "Energy",
      "London, UK",
      "referral",
    ],
  ]
);

/** Export the invalid rows so users can fix them in their spreadsheet. */
export function invalidRowsCsv(rows: ParsedRow[]): string {
  const headers = [
    "row_number",
    "name",
    "email",
    "phone",
    "company",
    "industry",
    "location",
    "tags",
    "errors",
  ];
  return toCsv(
    headers,
    rows.map((r) => [
      r.row_number,
      r.name ?? "",
      r.email ?? "",
      r.phone ?? "",
      r.company ?? "",
      r.industry ?? "",
      r.location ?? "",
      (r.tags ?? []).join(","),
      r.errors.join("; "),
    ])
  );
}
