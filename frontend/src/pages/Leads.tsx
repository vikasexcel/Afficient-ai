import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ChevronLeft,
  ChevronRight,
  Layers,
  Loader2,
  MoreHorizontal,
  Phone,
  Plus,
  Search,
  Upload,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import LeadFormDialog from "@/components/leads/LeadFormDialog";
import LeadDeleteDialog from "@/components/leads/LeadDeleteDialog";
import LeadDrawer from "@/components/leads/LeadDrawer";
import LeadImportDialog from "@/components/leads/LeadImportDialog";
import LeadListsDialog from "@/components/leads/LeadListsDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import {
  formatLeadError,
  listLeadLists,
  listLeads,
} from "@/services/leads";
import { initiateCall } from "@/services/telephony";
import { leadDisplayName, leadFullName } from "@/types/lead";
import type { Lead, LeadList, LeadStatus } from "@/types/lead";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

const STATUS_FILTERS: { id: LeadStatus | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "new", label: "New" },
  { id: "contacted", label: "Contacted" },
  { id: "qualified", label: "Qualified" },
  { id: "converted", label: "Converted" },
  { id: "lost", label: "Lost" },
];

const STATUS_CONFIG: Record<
  LeadStatus,
  { label: string; className: string }
> = {
  new: {
    label: "New",
    className: "bg-sky-500/10 text-sky-300 border-sky-500/25",
  },
  contacted: {
    label: "Contacted",
    className: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  },
  qualified: {
    label: "Qualified",
    className: "bg-violet-500/10 text-violet-300 border-violet-500/25",
  },
  converted: {
    label: "Converted",
    className: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  },
  lost: {
    label: "Lost",
    className: "bg-red-500/10 text-red-300 border-red-500/25",
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toE164(phone: string) {
  return `+${phone.replace(/\D/g, "")}`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Leads() {
  // List state
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [leadLists, setLeadLists] = useState<LeadList[]>([]);

  // Filters
  const [rawSearch, setRawSearch] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<LeadStatus | "all">("all");
  const [page, setPage] = useState(0); // 0-indexed

  // Modal state
  const [formOpen, setFormOpen] = useState(false);
  const [editLead, setEditLead] = useState<Lead | null>(null);
  const [deleteLead, setDeleteLead] = useState<Lead | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [drawerLead, setDrawerLead] = useState<Lead | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importPreselectedListId, setImportPreselectedListId] = useState<string | null>(null);
  const [leadListsOpen, setLeadListsOpen] = useState(false);

  // Debounce search input (300 ms)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  function handleSearchChange(value: string) {
    setRawSearch(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSearch(value.trim());
      setPage(0);
    }, 300);
  }

  // Fetch leads (stable reference; re-runs when deps change)
  const fetchLeads = useCallback(async () => {
    setLoading(true);
    try {
      const [result, lists] = await Promise.all([
        listLeads({
          search: search || undefined,
          status: statusFilter !== "all" ? statusFilter : undefined,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        }),
        listLeadLists(),
      ]);
      setLeads(result.leads);
      setTotal(result.total);
      setLeadLists(lists);
    } catch (err) {
      toast.error(formatLeadError(err, "Failed to load leads"));
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter, page]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void fetchLeads(); }, [fetchLeads]);

  // Computed stats (approximate from current page total, not per-page data)
  const pageCount = Math.ceil(total / PAGE_SIZE);
  const fromIndex = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const toIndex = Math.min((page + 1) * PAGE_SIZE, total);

  // Stat counts from current page leads
  const counts = useMemo(
    () => ({
      total,
      new: leads.filter((l) => l.status === "new").length,
      qualified: leads.filter((l) => l.status === "qualified").length,
      contacted: leads.filter((l) => l.status === "contacted").length,
    }),
    [leads, total]
  );

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  function openCreate() {
    setEditLead(null);
    setFormOpen(true);
  }

  function openEdit(lead: Lead) {
    setEditLead(lead);
    setFormOpen(true);
    setDrawerOpen(false);
  }

  function openDelete(lead: Lead) {
    setDeleteLead(lead);
    setDeleteOpen(true);
    setDrawerOpen(false);
  }

  function openDrawer(lead: Lead) {
    setDrawerLead(lead);
    setDrawerOpen(true);
  }

  async function handleCall(lead: Lead) {
    const name = leadDisplayName(lead);
    const toastId = toast.loading(`Calling ${name}…`);
    try {
      await initiateCall({
        to_number: toE164(lead.phone),
        lead_id: lead.id,
        lead_name: name,
        lead_phone: toE164(lead.phone),
      });
      toast.success(`Call started to ${name}`, { id: toastId });
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404 || status === 405) {
        toast.message("Calling coming soon", { id: toastId });
        return;
      }
      toast.error(formatLeadError(err, "Could not start call"), { id: toastId });
    }
  }

  function handleSaved(saved: Lead) {
    void fetchLeads();
    // If the drawer is open for this lead, update it.
    if (drawerLead?.id === saved.id) setDrawerLead(saved);
  }

  function handleDeleted() {
    void fetchLeads();
    if (drawerOpen) setDrawerOpen(false);
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <AppLayout>
      <div className="space-y-6 max-w-6xl">
        {/* Page header */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-medium text-white">
              Leads
            </h1>
            <p className="text-[13px] text-white/40 mt-1">
              {total > 0
                ? `${total.toLocaleString()} lead${total === 1 ? "" : "s"} in your pipeline`
                : "Manage prospects and pipeline activity."}
            </p>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-auto">
            <Button
              size="sm"
              variant="outline"
              className="border-white/[0.1] bg-white/[0.02] text-white/70 hover:text-white hover:bg-white/[0.05]"
              onClick={() => setLeadListsOpen(true)}
            >
              <Layers size={13} />
              Lead Lists
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="border-white/[0.1] bg-white/[0.02] text-white/70 hover:text-white hover:bg-white/[0.05]"
              onClick={() => { setImportPreselectedListId(null); setImportOpen(true); }}
            >
              <Upload size={13} />
              Import CSV
            </Button>
            <Button
              size="sm"
              className="bg-violet-600 hover:bg-violet-500 text-white"
              onClick={openCreate}
            >
              <Plus size={13} />
              Add lead
            </Button>
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Total" value={total} accent="violet" />
          <StatCard label="New" value={counts.new} accent="sky" />
          <StatCard label="Contacted" value={counts.contacted} accent="amber" />
          <StatCard label="Qualified" value={counts.qualified} accent="emerald" />
        </div>

        {/* Table card */}
        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02]">
          {/* Toolbar */}
          <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-3 p-3 border-b border-white/[0.05]">
            {/* Search */}
            <div className="relative flex-1 md:max-w-xs">
              <Search
                size={13}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/35 pointer-events-none"
              />
              <Input
                value={rawSearch}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="Search name, email, phone…"
                className="pl-8 h-9 bg-white/[0.03] border-white/[0.08] text-[13px] text-white placeholder:text-white/30"
              />
            </div>

            {/* Mobile filter */}
            <div className="md:hidden">
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value as LeadStatus | "all");
                  setPage(0);
                }}
                className="w-full h-9 rounded-[8px] bg-white/[0.03] border border-white/[0.08] px-2.5 text-[13px] text-white outline-none"
              >
                {STATUS_FILTERS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Desktop filter pills */}
            <div className="hidden md:flex items-center gap-1 flex-wrap">
              {STATUS_FILTERS.map((s) => {
                const active = statusFilter === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => { setStatusFilter(s.id); setPage(0); }}
                    className={cn(
                      "px-2.5 h-7 rounded-[7px] text-[12px] transition-colors border",
                      active
                        ? "bg-violet-500/15 text-violet-200 border-violet-500/30"
                        : "text-white/50 hover:text-white/85 hover:bg-white/[0.04] border-transparent"
                    )}
                  >
                    {s.label}
                  </button>
                );
              })}
            </div>

            {/* Loading indicator */}
            {loading && (
              <Loader2
                size={14}
                className="animate-spin text-white/30 ml-auto"
              />
            )}
          </div>

          {/* Table */}
          {loading && leads.length === 0 ? (
            <TableSkeleton />
          ) : leads.length === 0 ? (
            <EmptyState
              hasFilters={!!search || statusFilter !== "all"}
              onClear={() => {
                setRawSearch("");
                setSearch("");
                setStatusFilter("all");
              }}
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-white/[0.05] hover:bg-transparent">
                    <TableHead className="text-[11px] font-medium text-white/40 uppercase tracking-wider min-w-[180px]">
                      Name
                    </TableHead>
                    <TableHead className="text-[11px] font-medium text-white/40 uppercase tracking-wider min-w-[160px]">
                      Contact
                    </TableHead>
                    <TableHead className="text-[11px] font-medium text-white/40 uppercase tracking-wider min-w-[120px] hidden md:table-cell">
                      Job title
                    </TableHead>
                    <TableHead className="text-[11px] font-medium text-white/40 uppercase tracking-wider">
                      Status
                    </TableHead>
                    <TableHead className="text-[11px] font-medium text-white/40 uppercase tracking-wider hidden lg:table-cell">
                      Tags
                    </TableHead>
                    <TableHead className="text-[11px] font-medium text-white/40 uppercase tracking-wider hidden sm:table-cell">
                      Added
                    </TableHead>
                    <TableHead className="w-12" />
                  </TableRow>
                </TableHeader>

                <TableBody>
                  {leads.map((lead) => {
                    const status = STATUS_CONFIG[lead.status];
                    return (
                      <TableRow
                        key={lead.id}
                        className="border-white/[0.04] hover:bg-white/[0.02] cursor-pointer group"
                        onClick={() => openDrawer(lead)}
                      >
                        {/* Name — display name primary, contact name / company secondary */}
                        <TableCell className="py-3">
                          {(() => {
                            const displayName = leadDisplayName(lead);
                            const contactName = leadFullName(lead);
                            const hasCustomDisplay =
                              lead.display_name?.trim() &&
                              lead.display_name.trim() !== contactName;
                            return (
                              <div className="flex items-center gap-2.5">
                                <Avatar name={displayName} />
                                <div className="min-w-0">
                                  <p className="text-[13px] text-white truncate leading-tight">
                                    {displayName}
                                  </p>
                                  {hasCustomDisplay ? (
                                    <p className="text-[11px] text-white/40 truncate mt-0.5">
                                      {contactName}
                                    </p>
                                  ) : lead.company ? (
                                    <p className="text-[11px] text-white/40 truncate mt-0.5">
                                      {lead.company}
                                    </p>
                                  ) : null}
                                </div>
                              </div>
                            );
                          })()}
                        </TableCell>

                        {/* Contact */}
                        <TableCell className="py-3">
                          {lead.email && (
                            <p className="text-[12px] text-white/75 truncate leading-tight">
                              {lead.email}
                            </p>
                          )}
                          <div className="flex items-center gap-1 mt-0.5 text-[11px] text-white/40">
                            <Phone size={10} />
                            {lead.phone}
                          </div>
                        </TableCell>

                        {/* Job title */}
                        <TableCell className="py-3 text-[12px] text-white/65 hidden md:table-cell">
                          {lead.job_title ?? (
                            <span className="text-white/25">—</span>
                          )}
                        </TableCell>

                        {/* Status */}
                        <TableCell className="py-3">
                          <span
                            className={cn(
                              "inline-flex items-center h-5 px-2 rounded-full border text-[11px] font-medium",
                              status.className
                            )}
                          >
                            {status.label}
                          </span>
                        </TableCell>

                        {/* Tags */}
                        <TableCell className="py-3 hidden lg:table-cell">
                          {lead.tags && lead.tags.length > 0 ? (
                            <div className="flex flex-wrap gap-1 max-w-[160px]">
                              {lead.tags.slice(0, 2).map((tag) => (
                                <span
                                  key={tag}
                                  className="inline-flex items-center h-4 px-1.5 rounded-full bg-white/[0.05] border border-white/[0.07] text-[10px] text-white/55"
                                >
                                  {tag}
                                </span>
                              ))}
                              {lead.tags.length > 2 && (
                                <span className="text-[10px] text-white/35">
                                  +{lead.tags.length - 2}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-[11px] text-white/25">—</span>
                          )}
                        </TableCell>

                        {/* Added */}
                        <TableCell className="py-3 text-[12px] text-white/45 whitespace-nowrap hidden sm:table-cell">
                          {new Date(lead.created_at).toLocaleDateString()}
                        </TableCell>

                        {/* Row actions */}
                        <TableCell
                          className="py-3"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                className="text-white/35 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                              >
                                <MoreHorizontal size={14} />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              align="end"
                              className="w-40 bg-[#111114] border-white/[0.08] text-[13px]"
                            >
                              <DropdownMenuItem
                                onSelect={() => openDrawer(lead)}
                              >
                                View details
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => openEdit(lead)}
                              >
                                Edit
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => void handleCall(lead)}
                              >
                                Start call
                              </DropdownMenuItem>
                              <DropdownMenuSeparator className="bg-white/[0.06]" />
                              <DropdownMenuItem
                                className="text-red-400 focus:text-red-300 focus:bg-red-500/10"
                                onSelect={() => openDelete(lead)}
                              >
                                Delete
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {/* Pagination footer */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-white/[0.05]">
              <span className="text-[12px] text-white/40">
                {fromIndex}–{toIndex} of {total.toLocaleString()}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                  className="text-white/50 hover:text-white disabled:opacity-30"
                >
                  <ChevronLeft size={15} />
                </Button>
                <span className="text-[12px] text-white/50 px-2">
                  {page + 1} / {pageCount}
                </span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={page >= pageCount - 1}
                  onClick={() => setPage((p) => p + 1)}
                  className="text-white/50 hover:text-white disabled:opacity-30"
                >
                  <ChevronRight size={15} />
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Import CSV dialog */}
      <LeadImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        leadLists={leadLists}
        preselectedListId={importPreselectedListId}
        onImported={() => void fetchLeads()}
        onCreateManually={() => {
          setEditLead(null);
          setFormOpen(true);
        }}
      />

      {/* Lead Lists management dialog */}
      <LeadListsDialog
        open={leadListsOpen}
        onOpenChange={setLeadListsOpen}
        onImportIntoList={(listId) => {
          setLeadListsOpen(false);
          setImportPreselectedListId(listId);
          setImportOpen(true);
        }}
        onListsChanged={() => void fetchLeads()}
      />

      {/* Create / Edit dialog */}
      <LeadFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        lead={editLead}
        onSaved={handleSaved}
      />

      {/* Delete confirmation */}
      <LeadDeleteDialog
        lead={deleteLead}
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onDeleted={handleDeleted}
      />

      {/* Details drawer */}
      <LeadDrawer
        key={drawerLead?.id}
        lead={drawerLead}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        leadLists={leadLists}
        onEdit={openEdit}
        onDelete={openDelete}
        onCall={(lead) => void handleCall(lead)}
      />
    </AppLayout>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: "violet" | "sky" | "amber" | "emerald";
}) {
  const cls = {
    violet: "text-violet-300 bg-violet-500/10 border-violet-500/20",
    sky: "text-sky-300 bg-sky-500/10 border-sky-500/20",
    amber: "text-amber-300 bg-amber-500/10 border-amber-500/20",
    emerald: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
  } as const;
  return (
    <div className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] p-4 flex items-center gap-3">
      <div
        className={cn(
          "h-9 w-9 shrink-0 rounded-[8px] border flex items-center justify-center",
          cls[accent]
        )}
      >
        <Users size={14} />
      </div>
      <div>
        <p className="text-[11px] text-white/40 uppercase tracking-wider">
          {label}
        </p>
        <p className="text-[20px] font-semibold text-white leading-tight">
          {value.toLocaleString()}
        </p>
      </div>
    </div>
  );
}

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return (
    <span className="inline-flex shrink-0 items-center justify-center w-8 h-8 rounded-full bg-white/[0.06] border border-white/[0.08] text-[11px] font-medium text-white/75">
      {initials}
    </span>
  );
}

function TableSkeleton() {
  return (
    <div className="p-4 space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-8 w-8 rounded-full shrink-0" />
          <Skeleton className="h-4 flex-1 max-w-[160px]" />
          <Skeleton className="h-4 flex-1 max-w-[140px] hidden md:block" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-4 w-20 ml-auto hidden sm:block" />
        </div>
      ))}
    </div>
  );
}

function EmptyState({
  hasFilters,
  onClear,
}: {
  hasFilters: boolean;
  onClear: () => void;
}) {
  return (
    <div className="py-16 flex flex-col items-center justify-center text-center px-4">
      <div className="h-12 w-12 rounded-full bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-4">
        <Users size={18} className="text-white/35" />
      </div>
      <p className="text-[14px] font-medium text-white/80">
        {hasFilters ? "No leads matched" : "No leads yet"}
      </p>
      <p className="text-[12px] text-white/40 mt-1 max-w-xs">
        {hasFilters
          ? "Try adjusting your search or status filter."
          : "Add your first lead to get started."}
      </p>
      {hasFilters && (
        <Button
          size="sm"
          variant="ghost"
          onClick={onClear}
          className="mt-3 text-white/55 hover:text-white text-[12px]"
        >
          Clear filters
        </Button>
      )}
    </div>
  );
}
