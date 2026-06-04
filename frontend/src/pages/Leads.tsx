import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Filter,
  Loader2,
  MoreHorizontal,
  Phone,
  Plus,
  Search,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import LeadUploadDialog from "@/components/leads/LeadUploadDialog";
import LeadFormDialog from "@/components/leads/LeadFormDialog";
import LogActivityDialog from "@/components/leads/LogActivityDialog";
import LeadDetailsDialog from "@/components/leads/LeadDetailsDialog";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { formatApiError } from "@/lib/apiError";
import { formatLeadApiError, listLeads, deleteLead } from "@/services/lead";
import { initiateCall } from "@/services/telephony";
import type { Lead, LeadStatus } from "@/types/lead";

// Telephony backend (Twilio + LiveKit SIP) is implemented, so calling is
// enabled. Flip to false to fall back to a disabled "coming soon" button.
const CALLING_ENABLED = true;

/** Best-effort conversion of a stored phone to E.164 for the call API. */
function toE164(phone: string): string {
  const digits = (phone ?? "").replace(/\D/g, "");
  return `+${digits}`;
}

const STATUS_FILTERS: { id: LeadStatus | "all"; label: string }[] = [
  { id: "all", label: "All" },
  { id: "new", label: "New" },
  { id: "contacted", label: "Contacted" },
  { id: "qualified", label: "Qualified" },
  { id: "converted", label: "Converted" },
  { id: "lost", label: "Lost" },
];

export default function Leads() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<LeadStatus | "all">("all");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);

  // Modal coordination. Only one dialog is shown at a time.
  const [formState, setFormState] = useState<
    { mode: "add" } | { mode: "edit"; lead: Lead } | null
  >(null);
  const [activityLead, setActivityLead] = useState<Lead | null>(null);
  const [detailsLead, setDetailsLead] = useState<Lead | null>(null);
  const [detailsRefresh, setDetailsRefresh] = useState(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { leads } = await listLeads({ limit: 1000 });
      setLeads(leads);
    } catch (err) {
      toast.error(formatLeadApiError(err, "Failed to load leads"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return leads.filter((lead) => {
      if (status !== "all" && lead.status !== status) return false;
      if (!q) return true;
      // Case-insensitive partial match across every meaningful field so
      // "Sof" → "Software" (industry) and "754" → phone both resolve.
      const haystack = [
        lead.name,
        lead.email ?? "",
        lead.phone,
        lead.company ?? "",
        lead.industry ?? "",
        ...(lead.tags ?? []),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [query, status, leads]);

  const counts = useMemo(() => {
    const byStatus = (s: LeadStatus) =>
      leads.filter((l) => l.status === s).length;
    return {
      total: leads.length,
      new: byStatus("new"),
      qualified: byStatus("qualified"),
      contacted: byStatus("contacted"),
    };
  }, [leads]);

  async function handleDelete(lead: Lead) {
    try {
      await deleteLead(lead.id);
      toast.success(`Deleted ${lead.name}`);
      await refresh();
    } catch (err) {
      toast.error(formatLeadApiError(err, "Delete failed"));
    }
  }

  async function handleStartCall(lead: Lead) {
    if (!CALLING_ENABLED) {
      toast.message("Calling functionality coming soon");
      return;
    }
    const toastId = toast.loading(`Calling ${lead.name}…`);
    try {
      await initiateCall({
        to_number: toE164(lead.phone),
        lead_id: lead.id,
        lead_name: lead.name,
        lead_phone: toE164(lead.phone),
      });
      toast.success(`Call started to ${lead.name}`, { id: toastId });
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response
        ?.status;
      if (status === 404 || status === 405) {
        toast.message("Calling functionality coming soon", { id: toastId });
        return;
      }
      toast.error(formatApiError(err, "Could not start the call"), {
        id: toastId,
      });
    }
  }

  function openDetails(lead: Lead) {
    setDetailsLead(lead);
  }

  function openEdit(lead: Lead) {
    setDetailsLead(null);
    setActivityLead(null);
    setFormState({ mode: "edit", lead });
  }

  function openLogActivity(lead: Lead) {
    setActivityLead(lead);
  }

  return (
    <AppLayout>
      <div className="space-y-6 max-w-6xl">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-medium text-white">Leads</h1>
            <p className="text-[13px] text-white/40 mt-1">
              Manage prospects and pipeline activity.
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <LeadUploadDialog
              onImported={(res) => {
                toast.success(
                  `${res.inserted.toLocaleString()} lead${res.inserted === 1 ? "" : "s"} added to "${res.lead_list.name}"`
                );
                void refresh();
              }}
            />
            <Button
              size="sm"
              className="bg-violet-600 hover:bg-violet-500 text-white"
              onClick={() => setFormState({ mode: "add" })}
            >
              <Plus size={13} />
              Add lead
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Total leads" value={counts.total} accent="violet" />
          <StatCard label="New" value={counts.new} accent="emerald" />
          <StatCard
            label="Contacted"
            value={counts.contacted}
            accent="amber"
          />
          <StatCard label="Qualified" value={counts.qualified} accent="sky" />
        </div>

        <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02]">
          <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-3 p-3 border-b border-white/[0.05]">
            <div className="relative w-full md:flex-1 md:max-w-sm">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/35"
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search by name, email, company, or phone"
                className="pl-8 h-9 bg-white/[0.03] border-white/[0.08] text-[13px]"
              />
            </div>

            {/* Mobile status filter: native select keeps it ergonomic. */}
            <div className="md:hidden">
              <select
                value={status}
                onChange={(e) =>
                  setStatus(e.target.value as LeadStatus | "all")
                }
                className="w-full h-9 bg-white/[0.03] border border-white/[0.08] rounded-[8px] px-2.5 text-[13px] text-white outline-none"
                aria-label="Filter by status"
              >
                {STATUS_FILTERS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="hidden md:flex items-center gap-1.5 flex-wrap">
              <Filter size={12} className="text-white/35" />
              {STATUS_FILTERS.map((s) => {
                const active = status === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setStatus(s.id)}
                    className={cn(
                      "px-2.5 h-7 rounded-[7px] text-[12px] transition-colors",
                      active
                        ? "bg-violet-500/15 text-violet-200 border border-violet-500/30"
                        : "text-white/55 hover:text-white/85 hover:bg-white/[0.04] border border-transparent"
                    )}
                  >
                    {s.label}
                  </button>
                );
              })}
            </div>
          </div>

          {loading ? (
            <div className="py-16 flex items-center justify-center text-white/45">
              <Loader2 size={16} className="animate-spin mr-2" />
              Loading leads…
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState query={query} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-white/[0.05] hover:bg-transparent">
                  <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
                    Name
                  </TableHead>
                  <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
                    Contact
                  </TableHead>
                  <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
                    Status
                  </TableHead>
                  <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
                    Source
                  </TableHead>
                  <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
                    Industry
                  </TableHead>
                  <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
                    Added
                  </TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>

              <TableBody>
                {filtered.map((lead) => (
                  <TableRow
                    key={lead.id}
                    className="border-white/[0.04] hover:bg-white/[0.02]"
                  >
                    <TableCell className="py-2.5">
                      <div className="flex items-center gap-2.5">
                        <Avatar name={lead.name} />
                        <div className="min-w-0">
                          <div className="text-[13px] text-white truncate">
                            {lead.name}
                          </div>
                          <div className="text-[11px] text-white/40 truncate">
                            {lead.company ?? "—"}
                          </div>
                        </div>
                      </div>
                    </TableCell>

                    <TableCell className="py-2.5">
                      <div className="text-[12px] text-white/80 truncate">
                        {lead.email ?? "—"}
                      </div>
                      <div className="text-[11px] text-white/40 flex items-center gap-1 mt-0.5">
                        <Phone size={10} />
                        {lead.phone}
                      </div>
                    </TableCell>

                    <TableCell className="py-2.5">
                      <StatusBadge status={lead.status} />
                    </TableCell>

                    <TableCell className="py-2.5 text-[12px] text-white/70">
                      {lead.source ?? "—"}
                    </TableCell>

                    <TableCell className="py-2.5 text-[12px] text-white/70">
                      {lead.industry ?? "—"}
                    </TableCell>

                    <TableCell className="py-2.5 text-[12px] text-white/55">
                      {lead.created_at
                        ? new Date(lead.created_at).toLocaleDateString()
                        : "—"}
                    </TableCell>

                    <TableCell className="py-2.5">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            className="text-white/50 hover:text-white"
                          >
                            <MoreHorizontal size={14} />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="end"
                          className="w-44 bg-[#111114] border-white/[0.08]"
                        >
                          <DropdownMenuItem
                            onSelect={() => openDetails(lead)}
                          >
                            View details
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => openEdit(lead)}
                          >
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            disabled={!CALLING_ENABLED}
                            onSelect={() => void handleStartCall(lead)}
                          >
                            Start call
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => openLogActivity(lead)}
                          >
                            Log activity
                          </DropdownMenuItem>
                          <DropdownMenuSeparator className="bg-white/[0.06]" />
                          <DropdownMenuItem
                            className="text-red-400 focus:text-red-300"
                            onSelect={() => void handleDelete(lead)}
                          >
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </div>

      <LeadFormDialog
        open={formState !== null}
        onOpenChange={(o) => {
          if (!o) setFormState(null);
        }}
        lead={formState?.mode === "edit" ? formState.lead : null}
        onSaved={(saved) => {
          void refresh();
          // Keep an open details view in sync after an edit.
          setDetailsLead((cur) => (cur && cur.id === saved.id ? saved : cur));
        }}
      />

      <LogActivityDialog
        open={activityLead !== null}
        onOpenChange={(o) => {
          if (!o) setActivityLead(null);
        }}
        lead={activityLead}
        onLogged={() => setDetailsRefresh((n) => n + 1)}
      />

      <LeadDetailsDialog
        open={detailsLead !== null}
        onOpenChange={(o) => {
          if (!o) setDetailsLead(null);
        }}
        lead={detailsLead}
        refreshKey={detailsRefresh}
        callDisabled={!CALLING_ENABLED}
        onEdit={openEdit}
        onLogActivity={openLogActivity}
        onStartCall={(lead) => void handleStartCall(lead)}
      />
    </AppLayout>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: "violet" | "emerald" | "amber" | "sky";
}) {
  const accentMap = {
    violet: "text-violet-300 bg-violet-500/10 border-violet-500/20",
    emerald: "text-emerald-300 bg-emerald-500/10 border-emerald-500/20",
    amber: "text-amber-300 bg-amber-500/10 border-amber-500/20",
    sky: "text-sky-300 bg-sky-500/10 border-sky-500/20",
  } as const;

  return (
    <div className="rounded-[10px] border border-white/[0.06] bg-white/[0.02] p-4 flex items-center gap-3">
      <div
        className={cn(
          "h-9 w-9 rounded-[8px] border flex items-center justify-center",
          accentMap[accent]
        )}
      >
        <Users size={14} />
      </div>
      <div>
        <div className="text-[11px] text-white/45 uppercase tracking-wider">
          {label}
        </div>
        <div className="text-[18px] font-semibold text-white">{value}</div>
      </div>
    </div>
  );
}

const STATUS_STYLES: Record<LeadStatus, { label: string; className: string }> = {
  new: {
    label: "New",
    className: "bg-sky-500/10 text-sky-300 border-sky-500/20",
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

function StatusBadge({ status }: { status: LeadStatus }) {
  const s = STATUS_STYLES[status];
  return (
    <span
      className={cn(
        "inline-flex items-center h-5 px-2 rounded-full border text-[11px] font-medium",
        s.className
      )}
    >
      {s.label}
    </span>
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
    <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-white/[0.06] border border-white/[0.08] text-[11px] font-medium text-white/80">
      {initials}
    </span>
  );
}

function EmptyState({ query }: { query: string }) {
  return (
    <div className="py-16 flex flex-col items-center justify-center text-center">
      <div className="h-10 w-10 rounded-full bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-3">
        <Users size={16} className="text-white/40" />
      </div>
      <div className="text-[14px] text-white/80 font-medium">
        No leads found
      </div>
      <div className="text-[12px] text-white/45 mt-1 max-w-sm">
        {query
          ? `Nothing matched "${query}". Try a different search or status filter.`
          : "No leads match the selected filters."}
      </div>
    </div>
  );
}
