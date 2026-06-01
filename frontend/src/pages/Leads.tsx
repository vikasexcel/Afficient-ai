import { useMemo, useState } from "react";
import {
  Filter,
  MoreHorizontal,
  Phone,
  Plus,
  Search,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import LeadUploadDialog from "@/components/leads/LeadUploadDialog";
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

type LeadStatus = "new" | "contacted" | "qualified" | "converted" | "lost";

type Lead = {
  id: string;
  name: string;
  email: string;
  phone: string;
  company: string;
  status: LeadStatus;
  source: string;
  owner: string;
  lastContact: string;
};

const MOCK_LEADS: Lead[] = [
  {
    id: "ld_001",
    name: "Aarav Sharma",
    email: "aarav.sharma@northwindlabs.com",
    phone: "+91 98201 12345",
    company: "Northwind Labs",
    status: "new",
    source: "Website",
    owner: "Unassigned",
    lastContact: "Just added",
  },
  {
    id: "ld_002",
    name: "Priya Iyer",
    email: "priya@brightpath.io",
    phone: "+91 99876 54211",
    company: "Brightpath",
    status: "contacted",
    source: "Outbound",
    owner: "Riya M.",
    lastContact: "2 hours ago",
  },
  {
    id: "ld_003",
    name: "Daniel Cohen",
    email: "dan@helio-energy.com",
    phone: "+1 415 555 0188",
    company: "Helio Energy",
    status: "qualified",
    source: "Referral",
    owner: "Karan S.",
    lastContact: "Yesterday",
  },
  {
    id: "ld_004",
    name: "Mei Tanaka",
    email: "mei.tanaka@orbitfin.co",
    phone: "+81 80 4422 7711",
    company: "OrbitFin",
    status: "converted",
    source: "Campaign · Q2 SaaS",
    owner: "Aditi R.",
    lastContact: "3 days ago",
  },
  {
    id: "ld_005",
    name: "Lucas Ferreira",
    email: "lucas@viacore.br",
    phone: "+55 11 99888 4422",
    company: "Viacore",
    status: "lost",
    source: "Inbound chat",
    owner: "Karan S.",
    lastContact: "1 week ago",
  },
  {
    id: "ld_006",
    name: "Hannah Müller",
    email: "h.muller@helvio.de",
    phone: "+49 151 4422 1188",
    company: "Helvio",
    status: "contacted",
    source: "LinkedIn",
    owner: "Riya M.",
    lastContact: "4 hours ago",
  },
  {
    id: "ld_007",
    name: "Omar Haddad",
    email: "omar@levantretail.com",
    phone: "+971 50 991 4422",
    company: "Levant Retail",
    status: "new",
    source: "Website",
    owner: "Unassigned",
    lastContact: "Today",
  },
  {
    id: "ld_008",
    name: "Sofia Castillo",
    email: "sofia@montepay.mx",
    phone: "+52 55 8814 7720",
    company: "Montepay",
    status: "qualified",
    source: "Campaign · LATAM",
    owner: "Aditi R.",
    lastContact: "2 days ago",
  },
];

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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return MOCK_LEADS.filter((lead) => {
      if (status !== "all" && lead.status !== status) return false;
      if (!q) return true;
      return (
        lead.name.toLowerCase().includes(q) ||
        lead.email.toLowerCase().includes(q) ||
        lead.company.toLowerCase().includes(q) ||
        lead.phone.includes(q)
      );
    });
  }, [query, status]);

  const counts = useMemo(() => {
    const total = MOCK_LEADS.length;
    const byStatus = (s: LeadStatus) =>
      MOCK_LEADS.filter((l) => l.status === s).length;
    return {
      total,
      new: byStatus("new"),
      qualified: byStatus("qualified"),
      contacted: byStatus("contacted"),
    };
  }, []);

  return (
    <AppLayout>
      <div className="space-y-6 max-w-6xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-medium text-white">Leads</h1>
            <p className="text-[13px] text-white/40 mt-1">
              Manage prospects and pipeline activity. Backend wiring coming soon.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <LeadUploadDialog
              onImported={(res) =>
                toast.success(
                  `${res.inserted.toLocaleString()} lead${res.inserted === 1 ? "" : "s"} added to "${res.lead_list.name}"`
                )
              }
            />
            <Button
              size="sm"
              className="bg-violet-600 hover:bg-violet-500 text-white"
              onClick={() => toast.message("Add lead will be available soon")}
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
          <div className="flex items-center gap-3 p-3 border-b border-white/[0.05]">
            <div className="relative flex-1 max-w-sm">
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

            <div className="hidden md:flex items-center gap-1.5">
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

          {filtered.length === 0 ? (
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
                    Owner
                  </TableHead>
                  <TableHead className="text-white/40 font-medium text-[11px] uppercase tracking-wider">
                    Last contact
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
                            {lead.company}
                          </div>
                        </div>
                      </div>
                    </TableCell>

                    <TableCell className="py-2.5">
                      <div className="text-[12px] text-white/80 truncate">
                        {lead.email}
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
                      {lead.source}
                    </TableCell>

                    <TableCell className="py-2.5 text-[12px] text-white/70">
                      {lead.owner}
                    </TableCell>

                    <TableCell className="py-2.5 text-[12px] text-white/55">
                      {lead.lastContact}
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
                            onSelect={() =>
                              toast.message(`Opening ${lead.name}`)
                            }
                          >
                            View details
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() =>
                              toast.message(`Calling ${lead.name}`)
                            }
                          >
                            Start call
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() =>
                              toast.message(`Logging activity for ${lead.name}`)
                            }
                          >
                            Log activity
                          </DropdownMenuItem>
                          <DropdownMenuSeparator className="bg-white/[0.06]" />
                          <DropdownMenuItem
                            className="text-red-400 focus:text-red-300"
                            onSelect={() =>
                              toast.error("Delete will be available soon")
                            }
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
