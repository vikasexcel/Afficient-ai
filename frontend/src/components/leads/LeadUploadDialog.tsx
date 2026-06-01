import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Copy,
  Download,
  FileSpreadsheet,
  FileText,
  Layers,
  Loader2,
  Plus,
  Trash2,
  Upload,
  UploadCloud,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

import {
  commitUpload,
  listLeadLists,
  previewUpload,
} from "@/services/lead";
import {
  invalidRowsCsv,
  downloadText,
  SAMPLE_LEAD_CSV,
} from "@/lib/csv";
import type {
  CommitUploadResult,
  LeadList,
  ParsedRow,
  ParsedRowStatus,
  UploadPreview,
} from "@/types/lead";

/* -------------------------------------------------------------------------- */
/* Internal types                                                             */
/* -------------------------------------------------------------------------- */

type PreviewRow = ParsedRow & { included: boolean };

type UploadState =
  | { kind: "idle" }
  | { kind: "uploading"; file: File }
  | {
      kind: "preview";
      file: File;
      preview: UploadPreview;
      rows: PreviewRow[];
    }
  | { kind: "committing" }
  | { kind: "done"; result: CommitUploadResult };

type StatusFilter = "all" | ParsedRowStatus;

type Segmentation = {
  industry: string;
  location: string;
  tagsRaw: string;
  customFields: { key: string; value: string }[];
  /** "existing" picks a LeadList from the dropdown; "new" creates one. */
  targetMode: "existing" | "new";
  leadListId: string | null;
  newListName: string;
  source: string;
};

const MAX_FILE_BYTES = 5 * 1024 * 1024;

const FILTER_LABELS: { id: StatusFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "valid", label: "Valid" },
  { id: "duplicate", label: "Duplicates" },
  { id: "invalid", label: "Invalid" },
];

function emptySegmentation(): Segmentation {
  return {
    industry: "",
    location: "",
    tagsRaw: "",
    customFields: [],
    targetMode: "new",
    leadListId: null,
    newListName: "",
    source: "CSV import",
  };
}

function parseTags(raw: string): string[] {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}

function customFieldsToRecord(
  pairs: { key: string; value: string }[]
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { key, value } of pairs) {
    const k = key.trim();
    if (!k) continue;
    out[k] = value;
  }
  return out;
}

/* -------------------------------------------------------------------------- */
/* Component                                                                  */
/* -------------------------------------------------------------------------- */

type Props = {
  trigger?: React.ReactNode;
  onImported?: (result: CommitUploadResult) => void;
};

export default function LeadUploadDialog({ trigger, onImported }: Props) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<UploadState>({ kind: "idle" });
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);
  const [listsLoading, setListsLoading] = useState(false);
  const [segmentation, setSegmentation] = useState<Segmentation>(
    emptySegmentation()
  );
  const [filter, setFilter] = useState<StatusFilter>("all");

  const refsLoadedRef = useRef(false);

  const loadLists = useCallback(async () => {
    setListsLoading(true);
    try {
      const lists = await listLeadLists();
      setLeadLists(lists);
      if (lists.length > 0) {
        setSegmentation((s) => ({
          ...s,
          targetMode: "existing",
          leadListId: lists[0].id,
        }));
      }
    } catch {
      // Soft-fail: user can still create a new list.
      setLeadLists([]);
    } finally {
      setListsLoading(false);
    }
  }, []);

  function resetAll() {
    setState({ kind: "idle" });
    setSegmentation(emptySegmentation());
    setFilter("all");
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next && !refsLoadedRef.current) {
      refsLoadedRef.current = true;
      void loadLists();
    }
    if (!next) {
      resetAll();
    }
  }

  /* ------------------------- File handling ------------------------------- */

  const ingestFile = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".csv")) {
      toast.error("Only .csv files are supported");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      toast.error(
        `File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Max is 5 MB.`
      );
      return;
    }

    setState({ kind: "uploading", file });
    try {
      const preview = await previewUpload(file);
      setState({
        kind: "preview",
        file,
        preview,
        rows: preview.rows.map((r) => ({
          ...r,
          // Auto-exclude invalid + duplicate rows; user can opt back in.
          included: r.status === "valid",
        })),
      });
      setFilter("all");
    } catch (err) {
      const message =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        ((err as any)?.response?.data?.detail as string | undefined) ||
        (err instanceof Error ? err.message : "Upload failed");
      toast.error(message);
      setState({ kind: "idle" });
    }
  }, []);

  const handleFileInput = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (file) void ingestFile(file);
    },
    [ingestFile]
  );

  /* ------------------------- Commit -------------------------------------- */

  async function handleCommit() {
    if (state.kind !== "preview") return;
    const included = state.rows.filter((r) => r.included);
    if (included.length === 0) {
      toast.error("Select at least one row to import");
      return;
    }

    // Target list validation -------------------------------------------------
    if (segmentation.targetMode === "existing" && !segmentation.leadListId) {
      toast.error("Pick a lead list (or switch to 'create new')");
      return;
    }
    if (
      segmentation.targetMode === "new" &&
      segmentation.newListName.trim().length < 2
    ) {
      toast.error("Give the new list a name (min 2 chars)");
      return;
    }

    setState({ kind: "committing" });

    try {
      const payload = {
        rows: included.map((r) => ({
          name: r.name ?? "",
          email: r.email,
          phone: r.phone ?? "",
          company: r.company,
          industry: r.industry,
          location: r.location,
          tags: r.tags,
          custom_fields: r.custom_fields,
        })),
        segmentation: {
          industry: segmentation.industry.trim() || null,
          location: segmentation.location.trim() || null,
          tags: parseTags(segmentation.tagsRaw),
          custom_fields: customFieldsToRecord(segmentation.customFields),
        },
        lead_list_id:
          segmentation.targetMode === "existing"
            ? segmentation.leadListId
            : null,
        new_list_name:
          segmentation.targetMode === "new"
            ? segmentation.newListName.trim()
            : null,
        source: segmentation.source.trim() || null,
      };

      const result = await commitUpload(payload);
      setState({ kind: "done", result });
      onImported?.(result);
      toast.success(
        `Imported ${result.inserted} lead${result.inserted === 1 ? "" : "s"} into "${result.lead_list.name}"`
      );
    } catch (err) {
      const message =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        ((err as any)?.response?.data?.detail as string | undefined) ||
        (err instanceof Error ? err.message : "Import failed");
      toast.error(message);
      // Recover into preview state so user can retry without re-uploading.
      // We've lost the original parsed rows in `committing`, so just go idle.
      setState({ kind: "idle" });
    }
  }

  /* ------------------------- Render -------------------------------------- */

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button
            variant="outline"
            size="sm"
            className="border-white/[0.08] bg-white/[0.03] text-white/85 hover:bg-white/[0.06] hover:text-white"
          >
            <Upload size={13} />
            Import
          </Button>
        )}
      </DialogTrigger>

      <DialogContent
        className="sm:max-w-4xl p-0 gap-0 bg-[#0c0c10] border border-white/[0.08] ring-0"
        showCloseButton={false}
      >
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3 min-w-0">
              <div className="h-9 w-9 shrink-0 rounded-[10px] bg-violet-500/10 border border-violet-500/25 flex items-center justify-center">
                <FileSpreadsheet size={16} className="text-violet-300" />
              </div>
              <div className="min-w-0">
                <DialogTitle className="text-[15px] text-white">
                  Import leads from CSV
                </DialogTitle>
                <DialogDescription className="text-[12px] text-white/45 mt-0.5">
                  Validate, dedupe, and segment your contacts before they
                  land in a lead list.
                </DialogDescription>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => handleOpenChange(false)}
              className="text-white/55 hover:text-white"
            >
              <X size={14} />
            </Button>
          </div>
        </DialogHeader>

        {state.kind === "idle" && (
          <DropZone
            onFile={ingestFile}
            onFileInput={handleFileInput}
          />
        )}

        {state.kind === "uploading" && (
          <Centered>
            <Loader2 size={20} className="animate-spin text-violet-300" />
            <div className="text-[13px] text-white mt-3">
              Parsing {state.file.name}…
            </div>
            <div className="text-[11px] text-white/45 mt-1">
              We're validating names, phones, and emails — and checking
              your workspace for duplicates.
            </div>
          </Centered>
        )}

        {state.kind === "preview" && (
          <PreviewPanel
            file={state.file}
            preview={state.preview}
            rows={state.rows}
            setRows={(updater) =>
              setState((s) =>
                s.kind === "preview"
                  ? { ...s, rows: updater(s.rows) }
                  : s
              )
            }
            filter={filter}
            setFilter={setFilter}
            segmentation={segmentation}
            setSegmentation={setSegmentation}
            leadLists={leadLists}
            listsLoading={listsLoading}
            onReset={() => setState({ kind: "idle" })}
            onCommit={handleCommit}
          />
        )}

        {state.kind === "committing" && (
          <Centered>
            <Loader2 size={20} className="animate-spin text-violet-300" />
            <div className="text-[13px] text-white mt-3">
              Importing leads…
            </div>
          </Centered>
        )}

        {state.kind === "done" && (
          <DonePanel
            result={state.result}
            onUploadAnother={() => {
              resetAll();
            }}
            onClose={() => handleOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/* -------------------------------------------------------------------------- */
/* Drop zone                                                                  */
/* -------------------------------------------------------------------------- */

function DropZone({
  onFile,
  onFileInput,
}: {
  onFile: (file: File) => void;
  onFileInput: (e: ChangeEvent<HTMLInputElement>) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const onDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!dragging) setDragging(true);
  }, [dragging]);

  const onDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  }, []);

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
      const file = e.dataTransfer.files?.[0];
      if (file) onFile(file);
    },
    [onFile]
  );

  function downloadSample() {
    downloadText("aifficient-leads-sample.csv", SAMPLE_LEAD_CSV);
  }

  return (
    <div className="p-5 space-y-3">
      <div
        onDragOver={onDragOver}
        onDragEnter={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        className={cn(
          "relative rounded-[12px] border border-dashed transition-colors cursor-pointer",
          "flex flex-col items-center justify-center text-center py-14 px-6",
          dragging
            ? "border-violet-400/70 bg-violet-500/[0.07]"
            : "border-white/[0.12] bg-white/[0.02] hover:bg-white/[0.03] hover:border-white/[0.18]"
        )}
      >
        <div className="h-12 w-12 rounded-full bg-violet-500/10 border border-violet-500/25 flex items-center justify-center mb-3">
          <UploadCloud size={20} className="text-violet-300" />
        </div>
        <div className="text-[14px] text-white font-medium">
          Drop a CSV file here, or click to browse
        </div>
        <div className="text-[12px] text-white/45 mt-1 max-w-md">
          Supported headers include <code className="text-white/70">name</code>,{" "}
          <code className="text-white/70">phone</code>,{" "}
          <code className="text-white/70">email</code>,{" "}
          <code className="text-white/70">company</code>,{" "}
          <code className="text-white/70">industry</code>,{" "}
          <code className="text-white/70">location</code>,{" "}
          <code className="text-white/70">tags</code>. Unknown columns are
          preserved as custom fields.
        </div>
        <div className="mt-4 text-[11px] text-white/40">
          Max 5 MB · UTF-8 encoded · One header row required
        </div>

        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={onFileInput}
        />
      </div>

      <div className="flex items-center justify-between text-[12px]">
        <button
          type="button"
          onClick={downloadSample}
          className="inline-flex items-center gap-1.5 text-white/55 hover:text-white transition-colors"
        >
          <Download size={12} />
          Download sample CSV
        </button>
        <span className="text-white/35">
          Need help? Required columns are <strong>name</strong> and{" "}
          <strong>phone</strong>.
        </span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Preview panel                                                              */
/* -------------------------------------------------------------------------- */

function PreviewPanel({
  file,
  preview,
  rows,
  setRows,
  filter,
  setFilter,
  segmentation,
  setSegmentation,
  leadLists,
  listsLoading,
  onReset,
  onCommit,
}: {
  file: File;
  preview: UploadPreview;
  rows: PreviewRow[];
  setRows: (updater: (rows: PreviewRow[]) => PreviewRow[]) => void;
  filter: StatusFilter;
  setFilter: (f: StatusFilter) => void;
  segmentation: Segmentation;
  setSegmentation: React.Dispatch<React.SetStateAction<Segmentation>>;
  leadLists: LeadList[];
  listsLoading: boolean;
  onReset: () => void;
  onCommit: () => void;
}) {
  const stats = preview.stats;
  const includedCount = useMemo(
    () => rows.filter((r) => r.included).length,
    [rows]
  );

  const filtered = useMemo(() => {
    if (filter === "all") return rows;
    return rows.filter((r) => r.status === filter);
  }, [rows, filter]);

  const visibleAllIncluded = filtered.length > 0 && filtered.every((r) => r.included);

  function toggleRow(rowNumber: number) {
    setRows((rs) =>
      rs.map((r) =>
        r.row_number === rowNumber ? { ...r, included: !r.included } : r
      )
    );
  }

  function setAllInVisible(included: boolean) {
    const visibleNums = new Set(filtered.map((r) => r.row_number));
    setRows((rs) =>
      rs.map((r) => (visibleNums.has(r.row_number) ? { ...r, included } : r))
    );
  }

  function excludeStatus(status: ParsedRowStatus) {
    setRows((rs) =>
      rs.map((r) => (r.status === status ? { ...r, included: false } : r))
    );
  }

  function downloadInvalid() {
    const invalid = rows.filter((r) => r.status === "invalid");
    if (invalid.length === 0) {
      toast.message("No invalid rows to export");
      return;
    }
    downloadText("invalid-leads.csv", invalidRowsCsv(invalid));
  }

  return (
    <div className="flex flex-col max-h-[78vh]">
      {/* File + stats bar -------------------------------------------------- */}
      <div className="px-5 py-3 border-b border-white/[0.06] flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <FileText size={14} className="text-white/55 shrink-0" />
          <div className="min-w-0">
            <div className="text-[12px] text-white truncate">{file.name}</div>
            <div className="text-[11px] text-white/40">
              {(file.size / 1024).toFixed(1)} KB · {stats.total} rows
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <StatChip
            tone="neutral"
            label="Total"
            value={stats.total}
          />
          <StatChip tone="emerald" label="Valid" value={stats.valid} />
          <StatChip tone="amber" label="Duplicate" value={stats.duplicate} />
          <StatChip tone="red" label="Invalid" value={stats.invalid} />
        </div>
      </div>

      {/* Body -------------------------------------------------------------- */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-0 overflow-hidden">
        {/* Table column */}
        <div className="border-r border-white/[0.05] flex flex-col min-h-0">
          {/* Filters + bulk actions */}
          <div className="px-5 py-3 border-b border-white/[0.05] flex flex-wrap items-center gap-2 justify-between">
            <div className="flex items-center gap-1.5">
              {FILTER_LABELS.map((f) => {
                const active = filter === f.id;
                const count =
                  f.id === "all"
                    ? rows.length
                    : rows.filter((r) => r.status === f.id).length;
                return (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => setFilter(f.id)}
                    className={cn(
                      "h-7 px-2.5 rounded-[7px] text-[11.5px] transition-colors border",
                      active
                        ? "bg-violet-500/15 text-violet-200 border-violet-500/30"
                        : "text-white/55 hover:text-white hover:bg-white/[0.04] border-transparent"
                    )}
                  >
                    {f.label}
                    <span className="ml-1 text-white/40">({count})</span>
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-1.5">
              {stats.invalid > 0 && (
                <Button
                  size="xs"
                  variant="ghost"
                  className="text-white/55 hover:text-white"
                  onClick={() => excludeStatus("invalid")}
                >
                  <Trash2 size={11} />
                  Remove invalid
                </Button>
              )}
              {stats.duplicate > 0 && (
                <Button
                  size="xs"
                  variant="ghost"
                  className="text-white/55 hover:text-white"
                  onClick={() => excludeStatus("duplicate")}
                >
                  <Copy size={11} />
                  Remove duplicates
                </Button>
              )}
              {stats.invalid > 0 && (
                <Button
                  size="xs"
                  variant="ghost"
                  className="text-white/55 hover:text-white"
                  onClick={downloadInvalid}
                >
                  <Download size={11} />
                  Export invalid
                </Button>
              )}
            </div>
          </div>

          {/* Table */}
          <div className="overflow-auto max-h-[52vh]">
            {filtered.length === 0 ? (
              <div className="py-12 text-center text-[12px] text-white/45">
                Nothing to show for this filter.
              </div>
            ) : (
              <Table>
                <TableHeader className="sticky top-0 bg-[#0c0c10] z-10">
                  <TableRow className="border-white/[0.06] hover:bg-transparent">
                    <TableHead className="w-9 px-3">
                      <input
                        type="checkbox"
                        checked={visibleAllIncluded}
                        onChange={(e) => setAllInVisible(e.target.checked)}
                        className="accent-violet-500"
                        aria-label="Toggle all visible rows"
                      />
                    </TableHead>
                    <TableHead className="text-white/40 font-medium text-[10.5px] uppercase tracking-wider w-12">
                      Row
                    </TableHead>
                    <TableHead className="text-white/40 font-medium text-[10.5px] uppercase tracking-wider">
                      Lead
                    </TableHead>
                    <TableHead className="text-white/40 font-medium text-[10.5px] uppercase tracking-wider">
                      Phone
                    </TableHead>
                    <TableHead className="text-white/40 font-medium text-[10.5px] uppercase tracking-wider">
                      Status
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((row) => (
                    <PreviewRowItem
                      key={row.row_number}
                      row={row}
                      onToggle={() => toggleRow(row.row_number)}
                    />
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </div>

        {/* Segmentation column */}
        <SegmentationPanel
          segmentation={segmentation}
          setSegmentation={setSegmentation}
          leadLists={leadLists}
          listsLoading={listsLoading}
        />
      </div>

      {/* Footer ------------------------------------------------------------ */}
      <div className="border-t border-white/[0.06] bg-white/[0.015] px-5 py-3 flex items-center justify-between gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={onReset}
          className="text-white/55 hover:text-white"
        >
          <ArrowLeft size={13} />
          Upload a different file
        </Button>

        <div className="flex items-center gap-3">
          <div className="text-[12px] text-white/55">
            <span className="text-white font-medium">
              {includedCount.toLocaleString()}
            </span>{" "}
            of {rows.length.toLocaleString()} selected
          </div>
          <Button
            size="sm"
            disabled={includedCount === 0}
            onClick={onCommit}
            className="bg-violet-600 hover:bg-violet-500 text-white"
          >
            <CheckCircle2 size={13} />
            Import {includedCount.toLocaleString()} lead
            {includedCount === 1 ? "" : "s"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function PreviewRowItem({
  row,
  onToggle,
}: {
  row: PreviewRow;
  onToggle: () => void;
}) {
  const hasErrors = row.errors.length > 0;

  return (
    <TableRow
      className={cn(
        "border-white/[0.04] hover:bg-white/[0.02]",
        !row.included && "opacity-50"
      )}
    >
      <TableCell className="py-2 px-3 align-top">
        <input
          type="checkbox"
          checked={row.included}
          onChange={onToggle}
          className="accent-violet-500 mt-0.5"
          aria-label={`Include row ${row.row_number}`}
        />
      </TableCell>
      <TableCell className="py-2 text-[11px] text-white/45 align-top">
        {row.row_number}
      </TableCell>
      <TableCell className="py-2 align-top">
        <div className="text-[12.5px] text-white truncate max-w-[18rem]">
          {row.name || (
            <span className="text-red-400/80">— name missing —</span>
          )}
        </div>
        <div className="text-[11px] text-white/45 truncate max-w-[18rem]">
          {row.email || row.company || "—"}
        </div>
        {hasErrors && (
          <div className="mt-1 text-[11px] text-red-300/90 leading-tight flex items-start gap-1">
            <AlertCircle size={10} className="mt-[3px] shrink-0" />
            <span>{row.errors.join(" · ")}</span>
          </div>
        )}
      </TableCell>
      <TableCell className="py-2 text-[12px] text-white/80 align-top whitespace-nowrap">
        {row.phone || "—"}
      </TableCell>
      <TableCell className="py-2 align-top">
        <StatusBadge status={row.status} />
      </TableCell>
    </TableRow>
  );
}

/* -------------------------------------------------------------------------- */
/* Segmentation panel                                                         */
/* -------------------------------------------------------------------------- */

function SegmentationPanel({
  segmentation,
  setSegmentation,
  leadLists,
  listsLoading,
}: {
  segmentation: Segmentation;
  setSegmentation: React.Dispatch<React.SetStateAction<Segmentation>>;
  leadLists: LeadList[];
  listsLoading: boolean;
}) {
  // Keep the target mode honest: if user picks "existing" but there are
  // no lists yet, gently flip them back to "new".
  useEffect(() => {
    if (
      segmentation.targetMode === "existing" &&
      leadLists.length === 0 &&
      !listsLoading
    ) {
      setSegmentation((s) => ({ ...s, targetMode: "new" }));
    }
  }, [segmentation.targetMode, leadLists.length, listsLoading, setSegmentation]);

  function addCustomField() {
    setSegmentation((s) => ({
      ...s,
      customFields: [...s.customFields, { key: "", value: "" }],
    }));
  }

  function updateCustomField(
    idx: number,
    patch: Partial<{ key: string; value: string }>
  ) {
    setSegmentation((s) => ({
      ...s,
      customFields: s.customFields.map((cf, i) =>
        i === idx ? { ...cf, ...patch } : cf
      ),
    }));
  }

  function removeCustomField(idx: number) {
    setSegmentation((s) => ({
      ...s,
      customFields: s.customFields.filter((_, i) => i !== idx),
    }));
  }

  return (
    <div className="p-4 space-y-4 overflow-y-auto max-h-[52vh]">
      <SidebarSection
        icon={<Layers size={12} />}
        title="Destination"
      >
        <div className="flex items-center gap-1.5 mb-2">
          <ModeToggle
            active={segmentation.targetMode === "existing"}
            onClick={() =>
              setSegmentation((s) => ({ ...s, targetMode: "existing" }))
            }
            disabled={listsLoading || leadLists.length === 0}
          >
            Existing
          </ModeToggle>
          <ModeToggle
            active={segmentation.targetMode === "new"}
            onClick={() =>
              setSegmentation((s) => ({ ...s, targetMode: "new" }))
            }
          >
            Create new
          </ModeToggle>
        </div>

        {segmentation.targetMode === "existing" ? (
          <Select
            value={segmentation.leadListId ?? undefined}
            onValueChange={(v) =>
              setSegmentation((s) => ({ ...s, leadListId: v }))
            }
            disabled={listsLoading}
          >
            <SelectTrigger className="w-full h-8 bg-white/[0.03] border-white/[0.09] text-[12.5px]">
              <SelectValue
                placeholder={listsLoading ? "Loading…" : "Select a list"}
              />
            </SelectTrigger>
            <SelectContent
              className="bg-[#111114] border-white/[0.08]"
              position="popper"
            >
              {leadLists.map((list) => (
                <SelectItem key={list.id} value={list.id}>
                  <div className="flex flex-col">
                    <span className="text-[12.5px]">{list.name}</span>
                    <span className="text-[11px] text-white/40">
                      {list.lead_count.toLocaleString()} leads
                    </span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Input
            placeholder="e.g. Q3 SaaS · Warm inbound"
            value={segmentation.newListName}
            onChange={(e) =>
              setSegmentation((s) => ({
                ...s,
                newListName: e.target.value,
              }))
            }
            className="h-8 bg-white/[0.03] border-white/[0.09] text-[12.5px]"
          />
        )}
      </SidebarSection>

      <SidebarSection title="Source">
        <Input
          placeholder="HubSpot, Manual upload, …"
          value={segmentation.source}
          onChange={(e) =>
            setSegmentation((s) => ({ ...s, source: e.target.value }))
          }
          className="h-8 bg-white/[0.03] border-white/[0.09] text-[12.5px]"
        />
      </SidebarSection>

      <SidebarSection
        title="Segmentation"
        hint="Applied to every imported row. Per-row values from the CSV win."
      >
        <FieldLabel>Tags</FieldLabel>
        <Input
          placeholder="warm, demo-requested"
          value={segmentation.tagsRaw}
          onChange={(e) =>
            setSegmentation((s) => ({ ...s, tagsRaw: e.target.value }))
          }
          className="h-8 bg-white/[0.03] border-white/[0.09] text-[12.5px]"
        />

        <FieldLabel className="mt-2.5">Industry</FieldLabel>
        <Input
          placeholder="SaaS"
          value={segmentation.industry}
          onChange={(e) =>
            setSegmentation((s) => ({ ...s, industry: e.target.value }))
          }
          className="h-8 bg-white/[0.03] border-white/[0.09] text-[12.5px]"
        />

        <FieldLabel className="mt-2.5">Location</FieldLabel>
        <Input
          placeholder="San Francisco, CA"
          value={segmentation.location}
          onChange={(e) =>
            setSegmentation((s) => ({ ...s, location: e.target.value }))
          }
          className="h-8 bg-white/[0.03] border-white/[0.09] text-[12.5px]"
        />
      </SidebarSection>

      <SidebarSection title="Custom fields">
        <div className="space-y-1.5">
          {segmentation.customFields.length === 0 && (
            <div className="text-[11px] text-white/40">
              Add ad-hoc metadata applied to every row.
            </div>
          )}
          {segmentation.customFields.map((cf, idx) => (
            <div key={idx} className="flex items-center gap-1.5">
              <Input
                placeholder="key"
                value={cf.key}
                onChange={(e) =>
                  updateCustomField(idx, { key: e.target.value })
                }
                className="h-8 bg-white/[0.03] border-white/[0.09] text-[12px] flex-1"
              />
              <Input
                placeholder="value"
                value={cf.value}
                onChange={(e) =>
                  updateCustomField(idx, { value: e.target.value })
                }
                className="h-8 bg-white/[0.03] border-white/[0.09] text-[12px] flex-1"
              />
              <Button
                variant="ghost"
                size="icon-xs"
                onClick={() => removeCustomField(idx)}
                className="text-white/45 hover:text-red-300"
              >
                <X size={11} />
              </Button>
            </div>
          ))}
        </div>
        <Button
          variant="ghost"
          size="xs"
          onClick={addCustomField}
          className="mt-2 text-white/55 hover:text-white"
        >
          <Plus size={11} />
          Add field
        </Button>
      </SidebarSection>
    </div>
  );
}

function SidebarSection({
  icon,
  title,
  hint,
  children,
}: {
  icon?: React.ReactNode;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-center gap-1.5 mb-1.5">
        {icon && <span className="text-violet-300/90">{icon}</span>}
        <h4 className="text-[10.5px] font-medium text-white/55 uppercase tracking-wider">
          {title}
        </h4>
      </div>
      {hint && (
        <p className="text-[10.5px] text-white/40 mb-2 leading-snug">
          {hint}
        </p>
      )}
      {children}
    </section>
  );
}

function FieldLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Label
      className={cn(
        "text-[10.5px] font-medium text-white/45 mb-1 block",
        className
      )}
    >
      {children}
    </Label>
  );
}

function ModeToggle({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "h-7 px-2.5 rounded-[7px] text-[11.5px] transition-colors border",
        active
          ? "bg-violet-500/15 text-violet-200 border-violet-500/30"
          : "text-white/55 hover:text-white hover:bg-white/[0.04] border-transparent",
        disabled && "opacity-50 cursor-not-allowed"
      )}
    >
      {children}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/* Status + stat chips                                                        */
/* -------------------------------------------------------------------------- */

const STATUS_STYLES: Record<
  ParsedRowStatus,
  { label: string; className: string }
> = {
  valid: {
    label: "Valid",
    className: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  },
  duplicate: {
    label: "Duplicate",
    className: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  },
  invalid: {
    label: "Invalid",
    className: "bg-red-500/10 text-red-300 border-red-500/25",
  },
};

function StatusBadge({ status }: { status: ParsedRowStatus }) {
  const s = STATUS_STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex items-center h-5 px-2 rounded-full border text-[10.5px] font-medium",
        s.className
      )}
    >
      {s.label}
    </span>
  );
}

function StatChip({
  tone,
  label,
  value,
}: {
  tone: "neutral" | "emerald" | "amber" | "red";
  label: string;
  value: number;
}) {
  const tones = {
    neutral: "bg-white/[0.04] text-white/75 border-white/[0.08]",
    emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
    amber: "bg-amber-500/10 text-amber-300 border-amber-500/20",
    red: "bg-red-500/10 text-red-300 border-red-500/20",
  } as const;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 h-6 px-2 rounded-[7px] border text-[11px]",
        tones[tone]
      )}
    >
      <span className="opacity-70">{label}</span>
      <span className="font-semibold tabular-nums">
        {value.toLocaleString()}
      </span>
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Done panel + utility wrappers                                              */
/* -------------------------------------------------------------------------- */

function DonePanel({
  result,
  onUploadAnother,
  onClose,
}: {
  result: CommitUploadResult;
  onUploadAnother: () => void;
  onClose: () => void;
}) {
  return (
    <div className="px-6 py-12 flex flex-col items-center text-center">
      <div className="h-12 w-12 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center mb-3">
        <CheckCircle2 size={22} className="text-emerald-300" />
      </div>
      <div className="text-[15px] text-white font-medium">
        Import complete
      </div>
      <p className="text-[12.5px] text-white/55 mt-1 max-w-md">
        Added <strong>{result.inserted.toLocaleString()}</strong> lead
        {result.inserted === 1 ? "" : "s"} to{" "}
        <span className="text-white">"{result.lead_list.name}"</span>.
        {result.skipped_duplicates > 0 && (
          <>
            {" "}
            Skipped{" "}
            <strong>{result.skipped_duplicates.toLocaleString()}</strong>{" "}
            duplicate row{result.skipped_duplicates === 1 ? "" : "s"}.
          </>
        )}
      </p>

      <div className="flex gap-2 mt-6">
        <Button
          variant="outline"
          size="sm"
          onClick={onUploadAnother}
          className="border-white/[0.1] bg-white/[0.02] text-white/85 hover:bg-white/[0.06] hover:text-white"
        >
          Upload another file
        </Button>
        <Button
          size="sm"
          onClick={onClose}
          className="bg-violet-600 hover:bg-violet-500 text-white"
        >
          Done
        </Button>
      </div>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="py-16 px-6 flex flex-col items-center text-center">
      {children}
    </div>
  );
}
