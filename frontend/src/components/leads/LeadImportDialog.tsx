/**
 * LeadImportDialog — enhanced CSV bulk-import with pre-import validation preview.
 *
 * Flow:
 *   pick → parsing → preview → importing → done
 *
 * The preview step parses the CSV entirely in-browser (same rules as the
 * backend) so users see exact row-level errors before committing.
 * The actual import uses POST /leads/import, preceded by a POST /lead-lists
 * call when the user is creating a new list.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  FileText,
  Loader2,
  Upload,
  UserPlus,
} from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { downloadText } from "@/lib/csv";
import { createLeadList, importLeadsCSV } from "@/services/leads";
import type { LeadList } from "@/types/lead";
import type { ParsedRowStatus } from "@/types/lead";
import {
  COLUMN_SYNONYMS,
  generateValidationReport,
  processCSV,
  type ParsedRow,
  type ParseResult,
} from "@/lib/csvParser";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Step = "pick" | "parsing" | "preview" | "importing" | "done";
/** Whether to create a fresh list or add to an already-existing same-named one. */
type ListMode = "new" | "existing";

interface ImportResult {
  imported: number;
  skipped: number;
  errors: { row: number; errors: string[] }[];
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  leadLists: LeadList[];
  onImported: () => void;
  /** Pre-select an existing list (from Lead Lists dialog "Import CSV" button). */
  preselectedListId?: string | null;
  /** When provided, a "Create manually" ghost button appears in the footer. */
  onCreateManually?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Strip the file extension and normalise a filename into a list name. */
function nameFromFile(filename: string): string {
  return filename.replace(/\.[^.]+$/, "").trim();
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function LeadImportDialog({
  open,
  onOpenChange,
  leadLists,
  onImported,
  preselectedListId,
  onCreateManually,
}: Props) {
  const [step, setStep] = useState<Step>("pick");
  const [file, setFile] = useState<File | null>(null);

  // Import destination state
  const [importMode, setImportMode] = useState<ListMode>("new");
  const [selectedExistingId, setSelectedExistingId] = useState<string>("__none__");
  const [newListName, setNewListName] = useState("");

  const [dragging, setDragging] = useState(false);
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [showAllErrors, setShowAllErrors] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset / initialise each time the dialog opens.
  useEffect(() => {
    if (open) {
      setStep("pick");
      setFile(null);
      setParseResult(null);
      setResult(null);
      setShowAllErrors(false);
      setNewListName("");
      if (preselectedListId && leadLists.some((ll) => ll.id === preselectedListId)) {
        setImportMode("existing");
        setSelectedExistingId(preselectedListId);
      } else {
        setImportMode("new");
        setSelectedExistingId("__none__");
      }
    }
  }, [open, preselectedListId, leadLists]);

  // -- File selection --------------------------------------------------------

  function acceptFile(f: File) {
    if (!f.name.toLowerCase().endsWith(".csv") && f.type !== "text/csv") {
      toast.error("Please upload a CSV file (.csv)");
      return;
    }
    setFile(f);
    // Auto-populate the "new list" name from the filename only when empty.
    if (importMode === "new") {
      setNewListName((prev) => (prev.trim() === "" ? nameFromFile(f.name) : prev));
    }
    void parseFile(f);
  }

  async function parseFile(f: File) {
    setStep("parsing");
    try {
      const text = await f.text();
      const pr = processCSV(text);
      setParseResult(pr);
      setStep("preview");
    } catch (err) {
      toast.error((err as Error).message ?? "Failed to parse CSV");
      setFile(null);
      setStep("pick");
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) acceptFile(f);
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) acceptFile(f);
    e.target.value = "";
  }

  // -- Import ----------------------------------------------------------------

  const handleImport = useCallback(async () => {
    if (!file || !parseResult) return;
    setStep("importing");

    try {
      let resolvedListId: string | null = null;
      let listLabel = "";

      if (importMode === "existing" && selectedExistingId !== "__none__") {
        resolvedListId = selectedExistingId;
        listLabel = leadLists.find((ll) => ll.id === selectedExistingId)?.name ?? selectedExistingId;
      } else if (importMode === "new" && newListName.trim()) {
        const created = await createLeadList({ name: newListName.trim() });
        resolvedListId = created.id;
        listLabel = created.name;
      }

      const res = await importLeadsCSV(file, resolvedListId);
      setResult(res);
      setStep("done");

      if (res.imported > 0) {
        onImported();
        const into = listLabel ? ` into '${listLabel}'` : "";
        toast.success(
          `${res.imported} lead${res.imported === 1 ? "" : "s"} imported${into}`
        );
      }
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Import failed";
      toast.error(msg);
      setStep("preview");
    }
  }, [file, parseResult, importMode, selectedExistingId, newListName, leadLists, onImported]);

  // -- Report download -------------------------------------------------------

  function handleDownloadReport() {
    if (!parseResult) return;
    downloadText(
      "validation-report.csv",
      generateValidationReport(parseResult.rows)
    );
  }

  // -- Create manually -------------------------------------------------------

  function handleCreateManually() {
    onOpenChange(false);
    onCreateManually?.();
  }

  // -- Derived state ---------------------------------------------------------

  const canImport =
    !!parseResult &&
    parseResult.summary.valid > 0 &&
    (
      (importMode === "existing" && selectedExistingId !== "__none__") ||
      (importMode === "new" && newListName.trim() !== "")
    );

  // -- Render ----------------------------------------------------------------

  const isWide = step === "preview";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "bg-[#0c0c10] border border-white/[0.08] p-0 gap-0",
          isWide ? "sm:max-w-2xl" : "sm:max-w-md"
        )}
      >
        {/* Header */}
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <div className="flex items-start gap-3">
            <div className="h-9 w-9 shrink-0 rounded-[10px] bg-violet-500/10 border border-violet-500/25 flex items-center justify-center">
              <Upload size={16} className="text-violet-300" />
            </div>
            <div>
              <DialogTitle className="text-[15px] text-white">
                Import leads from CSV
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/45 mt-0.5">
                {step === "preview" && parseResult
                  ? `${file?.name ?? "CSV"} · ${parseResult.summary.total} rows parsed`
                  : "Bulk-import leads — preview and validate before committing."}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* Body */}
        <div className="overflow-y-auto max-h-[70vh]">
          {step === "pick" && (
            <PickStep
              dragging={dragging}
              inputRef={inputRef}
              onDragOver={() => setDragging(true)}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              onInputChange={handleInputChange}
            />
          )}

          {step === "parsing" && (
            <SpinnerState label="Parsing CSV…" />
          )}

          {step === "preview" && parseResult && (
            <PreviewStep
              file={file!}
              parseResult={parseResult}
              importMode={importMode}
              selectedExistingId={selectedExistingId}
              newListName={newListName}
              leadLists={leadLists}
              showAllErrors={showAllErrors}
              onImportModeChange={setImportMode}
              onExistingIdChange={setSelectedExistingId}
              onNewListNameChange={setNewListName}
              onToggleErrors={() => setShowAllErrors((v) => !v)}
              onChangeFile={() => {
                setFile(null);
                setParseResult(null);
                setStep("pick");
              }}
            />
          )}

          {step === "importing" && (
            <SpinnerState label="Importing leads…" />
          )}

          {step === "done" && result && <DoneStep result={result} />}
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center gap-2 px-5 py-3 border-t border-white/[0.06] bg-white/[0.01]">
          {/* Left side */}
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-white/50 hover:text-white"
              onClick={() => onOpenChange(false)}
              disabled={step === "importing"}
            >
              {step === "done" ? "Close" : "Cancel"}
            </Button>

            {onCreateManually &&
              step !== "importing" &&
              step !== "done" && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-white/40 hover:text-violet-300 gap-1.5 text-[12px]"
                  onClick={handleCreateManually}
                >
                  <UserPlus size={12} />
                  Create manually
                </Button>
              )}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-2">
            {step === "preview" && parseResult && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="border-white/[0.1] bg-white/[0.02] text-white/60 hover:text-white"
                  onClick={handleDownloadReport}
                >
                  <Download size={12} />
                  Download report
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled={!canImport}
                  onClick={() => void handleImport()}
                  className="bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
                >
                  <Upload size={13} />
                  Import {parseResult.summary.valid} valid
                </Button>
              </>
            )}

            {step === "done" && result && result.imported === 0 && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setStep("pick");
                  setFile(null);
                  setResult(null);
                  setParseResult(null);
                }}
                className="border-white/[0.1] bg-white/[0.02] text-white/70 hover:text-white"
              >
                Try again
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Step: pick
// ---------------------------------------------------------------------------

function PickStep({
  dragging,
  inputRef,
  onDragOver,
  onDragLeave,
  onDrop,
  onInputChange,
}: {
  dragging: boolean;
  inputRef: React.RefObject<HTMLInputElement>;
  onDragOver: () => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
  onInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <div className="px-5 py-5 space-y-3">
      <div
        role="button"
        tabIndex={0}
        onDragOver={(e) => {
          e.preventDefault();
          onDragOver();
        }}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) =>
          (e.key === "Enter" || e.key === " ") && inputRef.current?.click()
        }
        className={cn(
          "relative flex flex-col items-center justify-center gap-2 rounded-[10px]",
          "border-2 border-dashed py-10 cursor-pointer transition-colors select-none",
          dragging
            ? "border-violet-500/60 bg-violet-500/5"
            : "border-white/[0.12] bg-white/[0.015] hover:border-white/[0.25] hover:bg-white/[0.03]"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={onInputChange}
        />
        <Upload size={22} className="text-white/30" />
        <div className="text-center">
          <p className="text-[13px] text-white/70">
            Drop CSV here or{" "}
            <span className="text-violet-400 underline underline-offset-2">
              browse
            </span>
          </p>
          <p className="text-[11px] text-white/35 mt-0.5">
            Required columns: name, phone
          </p>
        </div>
      </div>

      <div className="rounded-[8px] bg-white/[0.02] border border-white/[0.06] px-3 py-2.5">
        <p className="text-[11px] text-white/40 leading-relaxed">
          <span className="text-white/60 font-medium">
            Recognised headers:
          </span>{" "}
          name · phone · email · company · industry · location · tags
          <br />
          Common synonyms like "mobile", "full name", "organisation" are
          auto-mapped.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step: preview
// ---------------------------------------------------------------------------

const PREVIEW_LIMIT = 10;

function PreviewStep({
  file,
  parseResult,
  importMode,
  selectedExistingId,
  newListName,
  leadLists,
  showAllErrors,
  onImportModeChange,
  onExistingIdChange,
  onNewListNameChange,
  onToggleErrors,
  onChangeFile,
}: {
  file: File;
  parseResult: ParseResult;
  importMode: ListMode;
  selectedExistingId: string;
  newListName: string;
  leadLists: LeadList[];
  showAllErrors: boolean;
  onImportModeChange: (m: ListMode) => void;
  onExistingIdChange: (id: string) => void;
  onNewListNameChange: (n: string) => void;
  onToggleErrors: () => void;
  onChangeFile: () => void;
}) {
  const { summary, rows, columns } = parseResult;
  const previewRows = rows.slice(0, PREVIEW_LIMIT);
  const errorRows = rows.filter((r) => r.status !== "valid");
  const visibleErrors = showAllErrors ? errorRows : errorRows.slice(0, 5);
  const canonicals = Object.keys(COLUMN_SYNONYMS);
  const required = new Set(["name", "phone"]);

  return (
    <div className="px-5 py-4 space-y-5">
      {/* File info + change link */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0 text-[12px]">
          <FileText size={13} className="text-violet-300 shrink-0" />
          <span className="text-white/80 truncate">{file.name}</span>
          <span className="text-white/35 shrink-0">
            · {(file.size / 1024).toFixed(1)} KB
          </span>
        </div>
        <button
          type="button"
          onClick={onChangeFile}
          className="flex items-center gap-1 text-[11px] text-white/40 hover:text-violet-300 transition-colors shrink-0 ml-3"
        >
          <ArrowLeft size={11} />
          Change file
        </button>
      </div>

      {/* ── Import Destination ─────────────────────────────────────────────── */}
      <section className="rounded-[10px] border border-white/[0.07] bg-white/[0.015] p-4 space-y-3">
        <p className="text-[10.5px] font-medium text-white/45 uppercase tracking-wider">
          Import destination
        </p>

        {/* Radio: existing list */}
        <label className="flex items-start gap-3 cursor-pointer group">
          <div className="mt-0.5 shrink-0">
            <div
              onClick={() => onImportModeChange("existing")}
              className={cn(
                "w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors",
                importMode === "existing"
                  ? "border-violet-500 bg-violet-500"
                  : "border-white/30 group-hover:border-white/50"
              )}
            >
              {importMode === "existing" && (
                <div className="w-1.5 h-1.5 rounded-full bg-white" />
              )}
            </div>
          </div>
          <div className="flex-1 min-w-0 space-y-1.5" onClick={() => onImportModeChange("existing")}>
            <p className="text-[13px] text-white/80 leading-tight">Existing lead list</p>
            {importMode === "existing" && (
              <select
                value={selectedExistingId}
                onChange={(e) => onExistingIdChange(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                className="w-full h-9 rounded-[7px] bg-white/[0.04] border border-white/[0.09] px-2.5 text-[13px] text-white outline-none focus:border-violet-500/50"
              >
                <option value="__none__" className="bg-[#111114]">— Select a list —</option>
                {leadLists.map((ll) => (
                  <option key={ll.id} value={ll.id} className="bg-[#111114]">
                    {ll.name} ({ll.lead_count.toLocaleString()} leads)
                  </option>
                ))}
              </select>
            )}
            {importMode === "existing" && selectedExistingId === "__none__" && (
              <p className="text-[11px] text-amber-300/80 flex items-center gap-1">
                <AlertCircle size={10} />
                Select a list to continue.
              </p>
            )}
          </div>
        </label>

        {/* Radio: create new list */}
        <label className="flex items-start gap-3 cursor-pointer group">
          <div className="mt-0.5 shrink-0">
            <div
              onClick={() => onImportModeChange("new")}
              className={cn(
                "w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors",
                importMode === "new"
                  ? "border-violet-500 bg-violet-500"
                  : "border-white/30 group-hover:border-white/50"
              )}
            >
              {importMode === "new" && (
                <div className="w-1.5 h-1.5 rounded-full bg-white" />
              )}
            </div>
          </div>
          <div className="flex-1 min-w-0 space-y-1.5" onClick={() => onImportModeChange("new")}>
            <p className="text-[13px] text-white/80 leading-tight">Create new lead list</p>
            {importMode === "new" && (
              <Input
                value={newListName}
                onChange={(e) => onNewListNameChange(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                placeholder="e.g. US SaaS CEOs"
                className="h-9 bg-white/[0.04] border-white/[0.09] text-[13px] text-white placeholder:text-white/25 focus-visible:border-violet-500/50"
              />
            )}
            {importMode === "new" && newListName.trim() === "" && (
              <p className="text-[11px] text-amber-300/80 flex items-center gap-1">
                <AlertCircle size={10} />
                Enter a name for the new list.
              </p>
            )}
          </div>
        </label>
      </section>

      {/* Column mapping */}
      <section>
        <p className="text-[10.5px] font-medium text-white/45 uppercase tracking-wider mb-2">
          Column mapping — auto-detected
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1.5">
          {canonicals.map((canonical) => {
            const mapped = columns[canonical];
            const isRequired = required.has(canonical);
            return (
              <div
                key={canonical}
                className={cn(
                  "flex items-center gap-1.5 rounded-[6px] px-2 py-1 text-[11px] truncate",
                  mapped
                    ? "bg-emerald-500/5 border border-emerald-500/15 text-emerald-300/80"
                    : isRequired
                    ? "bg-red-500/5 border border-red-500/20 text-red-300/80"
                    : "bg-white/[0.02] border border-white/[0.05] text-white/30"
                )}
              >
                {mapped ? (
                  <CheckCircle2 size={10} className="shrink-0" />
                ) : (
                  <AlertCircle size={10} className="shrink-0" />
                )}
                <span className="font-medium capitalize truncate">
                  {canonical}
                </span>
                {mapped && (
                  <span className="text-white/35 truncate ml-auto">
                    → {mapped}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Validation summary */}
      <section>
        <p className="text-[10.5px] font-medium text-white/45 uppercase tracking-wider mb-2">
          Validation summary
        </p>
        <div className="grid grid-cols-4 gap-2">
          <SummaryCard label="Total" value={summary.total} tone="neutral" />
          <SummaryCard label="Valid" value={summary.valid} tone="emerald" />
          <SummaryCard label="Invalid" value={summary.invalid} tone="red" />
          <SummaryCard
            label="Duplicate"
            value={summary.duplicate}
            tone="amber"
          />
        </div>

        {(summary.missingRequired > 0 || summary.invalidEmails > 0) && (
          <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
            {summary.missingRequired > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] text-amber-300/80">
                <AlertCircle size={10} />
                {summary.missingRequired} row
                {summary.missingRequired !== 1 ? "s" : ""} missing required
                fields
              </span>
            )}
            {summary.invalidEmails > 0 && (
              <span className="inline-flex items-center gap-1 text-[11px] text-amber-300/80">
                <AlertCircle size={10} />
                {summary.invalidEmails} invalid email
                {summary.invalidEmails !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        )}
      </section>

      {/* Preview table */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <p className="text-[10.5px] font-medium text-white/45 uppercase tracking-wider">
            Preview
          </p>
          {rows.length > PREVIEW_LIMIT && (
            <span className="text-[10.5px] text-white/30">
              First {PREVIEW_LIMIT} of {rows.length} rows
            </span>
          )}
        </div>

        <div className="rounded-[8px] border border-white/[0.06] overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-white/[0.05] hover:bg-transparent bg-white/[0.015]">
                <TableHead className="py-2 w-10 text-[10px] font-medium text-white/40 uppercase tracking-wider">
                  #
                </TableHead>
                <TableHead className="py-2 text-[10px] font-medium text-white/40 uppercase tracking-wider">
                  Name
                </TableHead>
                <TableHead className="py-2 text-[10px] font-medium text-white/40 uppercase tracking-wider hidden sm:table-cell">
                  Phone
                </TableHead>
                <TableHead className="py-2 text-[10px] font-medium text-white/40 uppercase tracking-wider hidden md:table-cell">
                  Email
                </TableHead>
                <TableHead className="py-2 text-[10px] font-medium text-white/40 uppercase tracking-wider">
                  Status
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {previewRows.map((row) => (
                <PreviewRow key={row.row_number} row={row} />
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      {/* Row-level errors */}
      {errorRows.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10.5px] font-medium text-white/45 uppercase tracking-wider">
              Row errors ({errorRows.length})
            </p>
            {errorRows.length > 5 && (
              <button
                type="button"
                onClick={onToggleErrors}
                className="flex items-center gap-1 text-[11px] text-white/40 hover:text-white/70 transition-colors"
              >
                {showAllErrors ? (
                  <>
                    <ChevronUp size={11} /> Collapse
                  </>
                ) : (
                  <>
                    <ChevronDown size={11} /> Show all {errorRows.length}
                  </>
                )}
              </button>
            )}
          </div>
          <div className="rounded-[8px] border border-white/[0.06] bg-white/[0.02] p-2 space-y-1 max-h-40 overflow-y-auto">
            {visibleErrors.map((row) => (
              <div
                key={row.row_number}
                className="flex items-start gap-2 text-[11px]"
              >
                <AlertCircle
                  size={11}
                  className={cn(
                    "shrink-0 mt-[2px]",
                    row.status === "duplicate"
                      ? "text-amber-400"
                      : "text-red-400"
                  )}
                />
                <span className="text-white/50">
                  Row {row.row_number}:{" "}
                  <span className="text-white/75">
                    {row.errors.join(", ")}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* No valid rows warning */}
      {summary.valid === 0 && (
        <div className="flex items-center gap-2 rounded-[8px] border border-red-500/20 bg-red-500/5 px-3 py-2.5 text-[12px] text-red-300/80">
          <AlertCircle size={13} className="shrink-0" />
          No valid rows found. Fix the errors above and try a corrected file.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step: done
// ---------------------------------------------------------------------------

function DoneStep({ result }: { result: ImportResult }) {
  return (
    <div className="px-5 py-5 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-[8px] border border-emerald-500/20 bg-emerald-500/5 p-3 text-center">
          <p className="text-[22px] font-bold text-emerald-300">
            {result.imported}
          </p>
          <p className="text-[11px] text-emerald-300/70 mt-0.5">Imported</p>
        </div>
        <div className="rounded-[8px] border border-white/[0.07] bg-white/[0.02] p-3 text-center">
          <p className="text-[22px] font-bold text-white/60">
            {result.skipped}
          </p>
          <p className="text-[11px] text-white/40 mt-0.5">Skipped</p>
        </div>
      </div>

      {result.errors.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[10.5px] font-medium text-white/45 uppercase tracking-wider">
            Skipped rows
          </p>
          <div className="max-h-36 overflow-y-auto space-y-1 rounded-[8px] border border-white/[0.06] bg-white/[0.02] p-2">
            {result.errors.slice(0, 50).map((e) => (
              <div key={e.row} className="flex items-start gap-2 text-[11px]">
                <AlertCircle
                  size={11}
                  className="text-amber-400 shrink-0 mt-[2px]"
                />
                <span className="text-white/50">
                  Row {e.row}:{" "}
                  <span className="text-white/75">{e.errors.join(", ")}</span>
                </span>
              </div>
            ))}
            {result.errors.length > 50 && (
              <p className="text-[11px] text-white/35 pl-[19px]">
                …and {result.errors.length - 50} more
              </p>
            )}
          </div>
        </div>
      )}

      {result.imported === 0 && result.skipped > 0 && (
        <div className="flex items-center gap-2 rounded-[8px] border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 text-[12px] text-amber-300/80">
          <AlertCircle size={13} className="shrink-0" />
          All rows were skipped. Check the error details above.
        </div>
      )}

      {result.imported > 0 && (
        <div className="flex items-center gap-2 rounded-[8px] border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5 text-[12px] text-emerald-300/80">
          <CheckCircle2 size={13} className="shrink-0" />
          {result.imported} lead{result.imported === 1 ? "" : "s"} added to your pipeline.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function SpinnerState({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-3">
      <Loader2 size={26} className="animate-spin text-violet-400" />
      <p className="text-[13px] text-white/50">{label}</p>
    </div>
  );
}

const ROW_STATUS: Record<
  ParsedRowStatus,
  { label: string; className: string }
> = {
  valid: {
    label: "Valid",
    className: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  },
  invalid: {
    label: "Invalid",
    className: "bg-red-500/10 text-red-300 border-red-500/25",
  },
  duplicate: {
    label: "Duplicate",
    className: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  },
};

function PreviewRow({ row }: { row: ParsedRow }) {
  const status = ROW_STATUS[row.status];
  return (
    <TableRow className="border-white/[0.04] hover:bg-white/[0.02]">
      <TableCell className="py-2 text-[11px] text-white/35">
        {row.row_number}
      </TableCell>
      <TableCell className="py-2 text-[12px] text-white/85 max-w-[140px] truncate">
        {row.name ?? (
          <span className="text-red-400/70 italic text-[11px]">
            — missing —
          </span>
        )}
      </TableCell>
      <TableCell className="py-2 text-[12px] text-white/60 hidden sm:table-cell">
        {row.phone ?? <span className="text-white/25">—</span>}
      </TableCell>
      <TableCell className="py-2 text-[12px] text-white/50 max-w-[150px] truncate hidden md:table-cell">
        {row.email ?? <span className="text-white/25">—</span>}
      </TableCell>
      <TableCell className="py-2">
        <span
          className={cn(
            "inline-flex items-center h-5 px-2 rounded-full border text-[10px] font-medium",
            status.className
          )}
        >
          {status.label}
        </span>
      </TableCell>
    </TableRow>
  );
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "neutral" | "emerald" | "red" | "amber";
}) {
  const tones = {
    neutral: "border-white/[0.07] bg-white/[0.02] text-white/65",
    emerald: "border-emerald-500/20 bg-emerald-500/5 text-emerald-300",
    red: "border-red-500/20 bg-red-500/5 text-red-300",
    amber: "border-amber-500/20 bg-amber-500/5 text-amber-300",
  } as const;
  return (
    <div className={cn("rounded-[8px] border p-3 text-center", tones[tone])}>
      <p className="text-[18px] font-bold tabular-nums">{value}</p>
      <p className="text-[10px] mt-0.5 opacity-70">{label}</p>
    </div>
  );
}
