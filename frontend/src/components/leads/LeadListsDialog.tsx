/**
 * LeadListsDialog
 *
 * A full-featured lead-list management modal.
 *
 * Views:
 *   "lists"  — shows all lead lists with CRUD (create, rename+desc edit, delete)
 *   "detail" — shows leads inside a list; supports search, remove, and adding existing leads
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Edit2,
  Loader2,
  MoreHorizontal,
  Phone,
  Plus,
  Search,
  Trash2,
  Upload,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  addLeadsToList,
  createLeadList,
  deleteLeadList,
  formatLeadError,
  listLeadLists,
  listLeads,
  removeLeadsFromList,
  updateLeadList,
} from "@/services/leads";
import { leadDisplayName } from "@/types/lead";
import type { Lead, LeadList } from "@/types/lead";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type View = "lists" | "detail";

const DETAIL_PAGE_SIZE = 15;
const ADD_CANDIDATES_LIMIT = 50;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called when the user asks to import CSV into a specific list. */
  onImportIntoList: (listId: string) => void;
  /** Called after any mutation so the parent can refresh its own list cache. */
  onListsChanged: () => void;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function LeadListsDialog({
  open,
  onOpenChange,
  onImportIntoList,
  onListsChanged,
}: Props) {
  const [view, setView] = useState<View>("lists");
  const [lists, setLists] = useState<LeadList[]>([]);
  const [listsLoading, setListsLoading] = useState(true);

  // Create-list form
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);
  const createInputRef = useRef<HTMLInputElement>(null);

  // Per-item edit state (rename = inline name+desc edit)
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameDescValue, setRenameDescValue] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Detail view — list members
  const [selectedList, setSelectedList] = useState<LeadList | null>(null);
  const [detailLeads, setDetailLeads] = useState<Lead[]>([]);
  const [detailTotal, setDetailTotal] = useState(0);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailSearch, setDetailSearch] = useState("");
  const [detailRawSearch, setDetailRawSearch] = useState("");
  const [detailPage, setDetailPage] = useState(0);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const detailDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Add-leads panel
  const [addPanelOpen, setAddPanelOpen] = useState(false);
  const [addRawSearch, setAddRawSearch] = useState("");
  const [addSearch, setAddSearch] = useState("");
  const [addCandidates, setAddCandidates] = useState<Lead[]>([]);
  const [addCandidatesLoading, setAddCandidatesLoading] = useState(false);
  const [addSelected, setAddSelected] = useState<Set<string>>(new Set());
  const [addSubmitting, setAddSubmitting] = useState(false);
  const addDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset on open
  useEffect(() => {
    if (open) {
      setView("lists");
      setSelectedList(null);
      setCreateOpen(false);
      setNewName("");
      setNewDesc("");
      setRenamingId(null);
      setDeletingId(null);
      setDetailSearch("");
      setDetailRawSearch("");
      setDetailPage(0);
      setAddPanelOpen(false);
      setAddRawSearch("");
      setAddSearch("");
      setAddSelected(new Set());
      void fetchLists();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Focus create input when panel opens
  useEffect(() => {
    if (createOpen) {
      setTimeout(() => createInputRef.current?.focus(), 50);
    }
  }, [createOpen]);

  // ---------------------------------------------------------------------------
  // List management
  // ---------------------------------------------------------------------------

  const fetchLists = useCallback(async () => {
    setListsLoading(true);
    try {
      const data = await listLeadLists();
      setLists(data);
    } catch (err) {
      toast.error(formatLeadError(err, "Failed to load lead lists"));
    } finally {
      setListsLoading(false);
    }
  }, []);

  async function handleCreateList(e: React.FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    try {
      const created = await createLeadList({ name, description: newDesc.trim() || undefined });
      toast.success(`Lead list "${created.name}" created`);
      setNewName("");
      setNewDesc("");
      setCreateOpen(false);
      await fetchLists();
      onListsChanged();
      setSelectedList({ ...created });
      setDetailLeads([]);
      setDetailTotal(0);
      setDetailPage(0);
      setDetailSearch("");
      setDetailRawSearch("");
      setAddPanelOpen(false);
      setAddSelected(new Set());
      setView("detail");
    } catch (err) {
      toast.error(formatLeadError(err, "Failed to create lead list"));
    } finally {
      setCreating(false);
    }
  }

  function startRename(ll: LeadList) {
    setRenamingId(ll.id);
    setRenameValue(ll.name);
    setRenameDescValue(ll.description ?? "");
    setDeletingId(null);
  }

  async function commitRename(id: string) {
    const name = renameValue.trim();
    if (!name) { setRenamingId(null); return; }
    try {
      const updated = await updateLeadList(id, {
        name,
        description: renameDescValue.trim() || undefined,
      });
      setRenamingId(null);
      setLists((prev) =>
        prev.map((ll) => ll.id === id ? { ...ll, name: updated.name, description: updated.description } : ll)
      );
      if (selectedList?.id === id) {
        setSelectedList((prev) =>
          prev ? { ...prev, name: updated.name, description: updated.description } : prev
        );
      }
      onListsChanged();
    } catch (err) {
      toast.error(formatLeadError(err, "Failed to update list"));
    }
  }

  function startDelete(id: string) {
    setDeletingId(id);
    setRenamingId(null);
  }

  async function confirmDelete(id: string) {
    try {
      await deleteLeadList(id);
      toast.success("Lead list deleted");
      setDeletingId(null);
      if (selectedList?.id === id) {
        setView("lists");
        setSelectedList(null);
      }
      await fetchLists();
      onListsChanged();
    } catch (err) {
      toast.error(formatLeadError(err, "Failed to delete list"));
    }
  }

  // ---------------------------------------------------------------------------
  // Detail view — list members
  // ---------------------------------------------------------------------------

  function enterDetail(ll: LeadList) {
    setSelectedList(ll);
    setDetailLeads([]);
    setDetailTotal(0);
    setDetailPage(0);
    setDetailSearch("");
    setDetailRawSearch("");
    setAddPanelOpen(false);
    setAddSelected(new Set());
    setView("detail");
  }

  const fetchDetailLeads = useCallback(async () => {
    if (!selectedList) return;
    setDetailLoading(true);
    try {
      const res = await listLeads({
        lead_list_id: selectedList.id,
        search: detailSearch || undefined,
        limit: DETAIL_PAGE_SIZE,
        offset: detailPage * DETAIL_PAGE_SIZE,
      });
      setDetailLeads(res.leads);
      setDetailTotal(res.total);
      // When no search filter, res.total is the authoritative member count
      if (!detailSearch) {
        setSelectedList((prev) => prev ? { ...prev, lead_count: res.total } : prev);
        setLists((prev) =>
          prev.map((ll) =>
            ll.id === selectedList.id ? { ...ll, lead_count: res.total } : ll
          )
        );
      }
    } catch (err) {
      toast.error(formatLeadError(err, "Failed to load leads"));
    } finally {
      setDetailLoading(false);
    }
  }, [selectedList, detailSearch, detailPage]);

  useEffect(() => {
    if (view === "detail") void fetchDetailLeads();
  }, [view, fetchDetailLeads]);

  function handleDetailSearchChange(val: string) {
    setDetailRawSearch(val);
    if (detailDebounce.current) clearTimeout(detailDebounce.current);
    detailDebounce.current = setTimeout(() => {
      setDetailSearch(val.trim());
      setDetailPage(0);
    }, 300);
  }

  async function handleRemoveLead(leadId: string) {
    if (!selectedList || removingId) return;
    setRemovingId(leadId);
    try {
      await removeLeadsFromList(selectedList.id, [leadId]);
      toast.success("Lead removed from list");
      await fetchDetailLeads();
      onListsChanged();
    } catch (err) {
      toast.error(formatLeadError(err, "Failed to remove lead"));
    } finally {
      setRemovingId(null);
    }
  }

  function handleImportCSV() {
    if (!selectedList) return;
    onOpenChange(false);
    onImportIntoList(selectedList.id);
  }

  // ---------------------------------------------------------------------------
  // Add-leads panel
  // ---------------------------------------------------------------------------

  const fetchAddCandidates = useCallback(async () => {
    if (!selectedList) return;
    setAddCandidatesLoading(true);
    try {
      const res = await listLeads({
        search: addSearch || undefined,
        limit: ADD_CANDIDATES_LIMIT,
      });
      // Exclude leads already in this list
      const inListIds = new Set(detailLeads.map((l) => l.id));
      setAddCandidates(res.leads.filter((l) => !inListIds.has(l.id)));
    } catch {
      setAddCandidates([]);
    } finally {
      setAddCandidatesLoading(false);
    }
  }, [selectedList, addSearch, detailLeads]);

  useEffect(() => {
    if (addPanelOpen) void fetchAddCandidates();
  }, [addPanelOpen, addSearch, fetchAddCandidates]);

  function handleAddSearchChange(val: string) {
    setAddRawSearch(val);
    if (addDebounce.current) clearTimeout(addDebounce.current);
    addDebounce.current = setTimeout(() => setAddSearch(val.trim()), 300);
  }

  function toggleAddSelected(id: string) {
    setAddSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function openAddPanel() {
    setAddPanelOpen(true);
    setAddRawSearch("");
    setAddSearch("");
    setAddSelected(new Set());
  }

  function closeAddPanel() {
    setAddPanelOpen(false);
    setAddRawSearch("");
    setAddSearch("");
    setAddSelected(new Set());
  }

  async function handleSubmitAdd() {
    if (!selectedList || addSelected.size === 0 || addSubmitting) return;
    setAddSubmitting(true);
    try {
      const res = await addLeadsToList(selectedList.id, [...addSelected]);
      const n = res.added ?? addSelected.size;
      toast.success(`${n} lead${n !== 1 ? "s" : ""} added to list`);
      closeAddPanel();
      await fetchDetailLeads();
      onListsChanged();
    } catch (err) {
      toast.error(formatLeadError(err, "Failed to add leads"));
    } finally {
      setAddSubmitting(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const detailPageCount = Math.ceil(detailTotal / DETAIL_PAGE_SIZE);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#0c0c10] border border-white/[0.08] p-0 gap-0 sm:max-w-2xl">
        {/* ── Header ── */}
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            {view === "detail" && (
              <button
                type="button"
                onClick={() => { setView("lists"); setSelectedList(null); setAddPanelOpen(false); }}
                className="h-7 w-7 flex items-center justify-center rounded-[6px] text-white/40 hover:text-white hover:bg-white/[0.05] transition-colors"
              >
                <ArrowLeft size={15} />
              </button>
            )}
            <div className="h-9 w-9 shrink-0 rounded-[10px] bg-violet-500/10 border border-violet-500/25 flex items-center justify-center">
              <Users size={16} className="text-violet-300" />
            </div>
            <div className="flex-1 min-w-0">
              <DialogTitle className="text-[15px] text-white">
                {view === "detail" && selectedList ? selectedList.name : "Lead Lists"}
              </DialogTitle>
              <p className="text-[12px] text-white/40 mt-0.5">
                {view === "detail" && selectedList
                  ? `${selectedList.lead_count.toLocaleString()} lead${selectedList.lead_count === 1 ? "" : "s"}`
                  : `${lists.length} list${lists.length === 1 ? "" : "s"}`}
              </p>
            </div>
            {view === "lists" && (
              <Button
                type="button"
                size="sm"
                className="bg-violet-600 hover:bg-violet-500 text-white shrink-0"
                onClick={() => { setCreateOpen((v) => !v); setRenamingId(null); setDeletingId(null); }}
              >
                <Plus size={13} />
                New list
              </Button>
            )}
            {view === "detail" && (
              <div className="flex items-center gap-2 shrink-0">
                <Button
                  type="button"
                  size="sm"
                  className="bg-violet-600/80 hover:bg-violet-600 text-white"
                  onClick={addPanelOpen ? closeAddPanel : openAddPanel}
                >
                  <UserPlus size={12} />
                  {addPanelOpen ? "Cancel" : "Add Leads"}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="border-white/[0.1] bg-white/[0.02] text-white/70 hover:text-white"
                  onClick={handleImportCSV}
                >
                  <Upload size={12} />
                  Import CSV
                </Button>
              </div>
            )}
          </div>
        </DialogHeader>

        {/* ── Body ── */}
        <div className="overflow-y-auto max-h-[65vh]">
          {view === "lists" ? (
            <ListsView
              lists={lists}
              loading={listsLoading}
              createOpen={createOpen}
              creating={creating}
              newName={newName}
              newDesc={newDesc}
              renamingId={renamingId}
              renameValue={renameValue}
              renameDescValue={renameDescValue}
              deletingId={deletingId}
              createInputRef={createInputRef}
              onNewNameChange={setNewName}
              onNewDescChange={setNewDesc}
              onCreateSubmit={handleCreateList}
              onCreateCancel={() => { setCreateOpen(false); setNewName(""); setNewDesc(""); }}
              onRenameValueChange={setRenameValue}
              onRenameDescValueChange={setRenameDescValue}
              onStartRename={startRename}
              onCommitRename={commitRename}
              onCancelRename={() => setRenamingId(null)}
              onStartDelete={startDelete}
              onConfirmDelete={confirmDelete}
              onCancelDelete={() => setDeletingId(null)}
              onViewDetail={enterDetail}
            />
          ) : (
            <DetailView
              list={selectedList!}
              leads={detailLeads}
              total={detailTotal}
              loading={detailLoading}
              rawSearch={detailRawSearch}
              page={detailPage}
              pageCount={detailPageCount}
              removingId={removingId}
              addPanelOpen={addPanelOpen}
              addCandidates={addCandidates}
              addCandidatesLoading={addCandidatesLoading}
              addRawSearch={addRawSearch}
              addSelected={addSelected}
              addSubmitting={addSubmitting}
              onSearchChange={handleDetailSearchChange}
              onPageChange={setDetailPage}
              onRemoveLead={handleRemoveLead}
              onAddSearchChange={handleAddSearchChange}
              onToggleAddSelected={toggleAddSelected}
              onSubmitAdd={handleSubmitAdd}
            />
          )}
        </div>

        {/* ── Footer ── */}
        <div className="flex justify-end px-5 py-3 border-t border-white/[0.06] bg-white/[0.01]">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-white/50 hover:text-white"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Lists view
// ---------------------------------------------------------------------------

function ListsView({
  lists,
  loading,
  createOpen,
  creating,
  newName,
  newDesc,
  renamingId,
  renameValue,
  renameDescValue,
  deletingId,
  createInputRef,
  onNewNameChange,
  onNewDescChange,
  onCreateSubmit,
  onCreateCancel,
  onRenameValueChange,
  onRenameDescValueChange,
  onStartRename,
  onCommitRename,
  onCancelRename,
  onStartDelete,
  onConfirmDelete,
  onCancelDelete,
  onViewDetail,
}: {
  lists: LeadList[];
  loading: boolean;
  createOpen: boolean;
  creating: boolean;
  newName: string;
  newDesc: string;
  renamingId: string | null;
  renameValue: string;
  renameDescValue: string;
  deletingId: string | null;
  createInputRef: React.RefObject<HTMLInputElement>;
  onNewNameChange: (v: string) => void;
  onNewDescChange: (v: string) => void;
  onCreateSubmit: (e: React.FormEvent) => void;
  onCreateCancel: () => void;
  onRenameValueChange: (v: string) => void;
  onRenameDescValueChange: (v: string) => void;
  onStartRename: (ll: LeadList) => void;
  onCommitRename: (id: string) => void;
  onCancelRename: () => void;
  onStartDelete: (id: string) => void;
  onConfirmDelete: (id: string) => void;
  onCancelDelete: () => void;
  onViewDetail: (ll: LeadList) => void;
}) {
  return (
    <div className="px-5 py-4 space-y-3">
      {/* Create form */}
      {createOpen && (
        <form
          onSubmit={onCreateSubmit}
          className="rounded-[10px] border border-violet-500/25 bg-violet-500/5 p-4 space-y-3"
        >
          <p className="text-[12px] font-medium text-white/70">Create lead list</p>
          <div className="space-y-2">
            <Input
              ref={createInputRef}
              value={newName}
              onChange={(e) => onNewNameChange(e.target.value)}
              placeholder="Name *"
              className="h-9 bg-white/[0.04] border-white/[0.1] text-[13px] text-white placeholder:text-white/30"
              required
            />
            <Input
              value={newDesc}
              onChange={(e) => onNewDescChange(e.target.value)}
              placeholder="Description (optional)"
              className="h-9 bg-white/[0.04] border-white/[0.1] text-[13px] text-white placeholder:text-white/30"
            />
          </div>
          <div className="flex items-center gap-2 justify-end">
            <Button type="button" variant="ghost" size="sm" className="text-white/50 hover:text-white" onClick={onCreateCancel}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={!newName.trim() || creating}
              className="bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
            >
              {creating ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
              Create
            </Button>
          </div>
        </form>
      )}

      {/* Loading */}
      {loading ? (
        <div className="space-y-2 py-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3 py-2">
              <Skeleton className="h-8 w-8 rounded-[8px]" />
              <Skeleton className="h-4 flex-1 max-w-[200px]" />
              <Skeleton className="h-5 w-12 rounded-full ml-auto" />
            </div>
          ))}
        </div>
      ) : lists.length === 0 && !createOpen ? (
        <EmptyListsState onCreateClick={() => {}} />
      ) : (
        <div className="space-y-1">
          {lists.map((ll) => (
            <ListRow
              key={ll.id}
              ll={ll}
              isRenaming={renamingId === ll.id}
              renameValue={renameValue}
              renameDescValue={renameDescValue}
              isDeleting={deletingId === ll.id}
              onRenameValueChange={onRenameValueChange}
              onRenameDescValueChange={onRenameDescValueChange}
              onCommitRename={onCommitRename}
              onCancelRename={onCancelRename}
              onStartRename={onStartRename}
              onStartDelete={onStartDelete}
              onConfirmDelete={onConfirmDelete}
              onCancelDelete={onCancelDelete}
              onViewDetail={onViewDetail}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ListRow({
  ll,
  isRenaming,
  renameValue,
  renameDescValue,
  isDeleting,
  onRenameValueChange,
  onRenameDescValueChange,
  onCommitRename,
  onCancelRename,
  onStartRename,
  onStartDelete,
  onConfirmDelete,
  onCancelDelete,
  onViewDetail,
}: {
  ll: LeadList;
  isRenaming: boolean;
  renameValue: string;
  renameDescValue: string;
  isDeleting: boolean;
  onRenameValueChange: (v: string) => void;
  onRenameDescValueChange: (v: string) => void;
  onCommitRename: (id: string) => void;
  onCancelRename: () => void;
  onStartRename: (ll: LeadList) => void;
  onStartDelete: (id: string) => void;
  onConfirmDelete: (id: string) => void;
  onCancelDelete: () => void;
  onViewDetail: (ll: LeadList) => void;
}) {
  return (
    <div
      className={cn(
        "group flex items-center gap-3 rounded-[8px] px-3 py-2.5 border transition-colors",
        isDeleting
          ? "border-red-500/25 bg-red-500/5"
          : "border-white/[0.05] bg-white/[0.015] hover:bg-white/[0.03] hover:border-white/[0.08]"
      )}
    >
      {/* Icon */}
      <div className="h-8 w-8 shrink-0 rounded-[8px] bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
        <Users size={13} className="text-violet-300" />
      </div>

      {/* Name / rename inputs */}
      <div className="flex-1 min-w-0">
        {isRenaming ? (
          <form
            onSubmit={(e) => { e.preventDefault(); onCommitRename(ll.id); }}
            className="space-y-1.5"
          >
            <div className="flex items-center gap-2">
              <Input
                autoFocus
                value={renameValue}
                onChange={(e) => onRenameValueChange(e.target.value)}
                placeholder="List name *"
                className="h-7 text-[13px] bg-white/[0.05] border-violet-500/40 text-white px-2 flex-1"
                onKeyDown={(e) => e.key === "Escape" && onCancelRename()}
                required
              />
              <button type="submit" title="Save" className="text-emerald-400 hover:text-emerald-300 p-1 shrink-0">
                <CheckCircle2 size={14} />
              </button>
              <button type="button" onClick={onCancelRename} title="Cancel" className="text-white/35 hover:text-white/70 p-1 shrink-0">
                <X size={14} />
              </button>
            </div>
            <Input
              value={renameDescValue}
              onChange={(e) => onRenameDescValueChange(e.target.value)}
              placeholder="Description (optional)"
              className="h-7 text-[12px] bg-white/[0.03] border-white/[0.1] text-white/70 px-2"
              onKeyDown={(e) => e.key === "Escape" && onCancelRename()}
            />
          </form>
        ) : (
          <>
            <button
              type="button"
              onClick={() => !isDeleting && onViewDetail(ll)}
              className="text-[13px] text-white/85 hover:text-white truncate block text-left w-full"
            >
              {ll.name}
            </button>
            {ll.description && (
              <p className="text-[11px] text-white/35 truncate mt-0.5">{ll.description}</p>
            )}
          </>
        )}
      </div>

      {/* Lead count badge */}
      {!isRenaming && !isDeleting && (
        <span className="shrink-0 inline-flex items-center gap-1 h-5 px-2 rounded-full bg-white/[0.05] border border-white/[0.07] text-[10px] text-white/50">
          <Users size={9} />
          {ll.lead_count.toLocaleString()}
        </span>
      )}

      {/* Delete confirmation */}
      {isDeleting && (
        <div className="shrink-0 flex items-center gap-2">
          <span className="text-[11px] text-red-300/80">Delete?</span>
          <Button size="sm" type="button" onClick={() => onConfirmDelete(ll.id)}
            className="h-6 px-2 text-[11px] bg-red-500/20 border border-red-500/30 text-red-300 hover:bg-red-500/30">
            Yes
          </Button>
          <Button size="sm" type="button" variant="ghost" onClick={onCancelDelete}
            className="h-6 px-2 text-[11px] text-white/50 hover:text-white">
            Cancel
          </Button>
        </div>
      )}

      {/* 3-dot menu */}
      {!isRenaming && !isDeleting && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="shrink-0 text-white/25 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <MoreHorizontal size={14} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40 bg-[#111114] border-white/[0.08] text-[13px]">
            <DropdownMenuItem onSelect={() => onViewDetail(ll)}>
              View leads
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => onStartRename(ll)}>
              <Edit2 size={12} />
              Edit
            </DropdownMenuItem>
            <DropdownMenuSeparator className="bg-white/[0.06]" />
            <DropdownMenuItem
              className="text-red-400 focus:text-red-300 focus:bg-red-500/10"
              onSelect={() => onStartDelete(ll.id)}
            >
              <Trash2 size={12} />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail view
// ---------------------------------------------------------------------------

function DetailView({
  list,
  leads,
  total,
  loading,
  rawSearch,
  page,
  pageCount,
  removingId,
  addPanelOpen,
  addCandidates,
  addCandidatesLoading,
  addRawSearch,
  addSelected,
  addSubmitting,
  onSearchChange,
  onPageChange,
  onRemoveLead,
  onAddSearchChange,
  onToggleAddSelected,
  onSubmitAdd,
}: {
  list: LeadList;
  leads: Lead[];
  total: number;
  loading: boolean;
  rawSearch: string;
  page: number;
  pageCount: number;
  removingId: string | null;
  addPanelOpen: boolean;
  addCandidates: Lead[];
  addCandidatesLoading: boolean;
  addRawSearch: string;
  addSelected: Set<string>;
  addSubmitting: boolean;
  onSearchChange: (v: string) => void;
  onPageChange: (p: number) => void;
  onRemoveLead: (id: string) => void;
  onAddSearchChange: (v: string) => void;
  onToggleAddSelected: (id: string) => void;
  onSubmitAdd: () => void;
}) {
  const from = total === 0 ? 0 : page * DETAIL_PAGE_SIZE + 1;
  const to = Math.min((page + 1) * DETAIL_PAGE_SIZE, total);

  return (
    <div className="px-5 py-4 space-y-4">
      {/* Add Leads Panel */}
      {addPanelOpen && (
        <AddLeadsPanel
          candidates={addCandidates}
          loading={addCandidatesLoading}
          rawSearch={addRawSearch}
          selected={addSelected}
          submitting={addSubmitting}
          onSearchChange={onAddSearchChange}
          onToggle={onToggleAddSelected}
          onSubmit={onSubmitAdd}
        />
      )}

      {/* Member search toolbar */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/35 pointer-events-none" />
          <Input
            value={rawSearch}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search name, email, phone, company…"
            className="pl-8 h-9 bg-white/[0.03] border-white/[0.08] text-[13px] text-white placeholder:text-white/30"
          />
        </div>
        {loading && <Loader2 size={14} className="animate-spin text-white/30 shrink-0" />}
      </div>

      {/* Members table */}
      {loading && leads.length === 0 ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="flex items-center gap-3 py-1.5">
              <Skeleton className="h-7 w-7 rounded-full shrink-0" />
              <Skeleton className="h-4 flex-1 max-w-[160px]" />
              <Skeleton className="h-4 flex-1 max-w-[120px] hidden sm:block" />
              <Skeleton className="h-6 w-6 ml-auto rounded-[4px]" />
            </div>
          ))}
        </div>
      ) : leads.length === 0 ? (
        <div className="py-10 flex flex-col items-center text-center">
          <div className="h-10 w-10 rounded-full bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-3">
            <Users size={16} className="text-white/30" />
          </div>
          <p className="text-[13px] text-white/60">
            {rawSearch ? "No leads matched your search" : "No leads in this list yet"}
          </p>
          {!rawSearch && (
            <p className="text-[11px] text-white/35 mt-1">
              Use "Add Leads" to pick from existing leads, or import a CSV.
            </p>
          )}
        </div>
      ) : (
        <div className="rounded-[8px] border border-white/[0.06] overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="border-white/[0.05] hover:bg-transparent bg-white/[0.015]">
                <TableHead className="py-2 text-[10px] font-medium text-white/40 uppercase tracking-wider">Name</TableHead>
                <TableHead className="py-2 text-[10px] font-medium text-white/40 uppercase tracking-wider hidden sm:table-cell">Contact</TableHead>
                <TableHead className="py-2 text-[10px] font-medium text-white/40 uppercase tracking-wider hidden md:table-cell">Company</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {leads.map((lead) => {
                const dn = leadDisplayName(lead);
                const initials = dn.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
                return (
                  <TableRow key={lead.id} className="border-white/[0.04] hover:bg-white/[0.02]">
                    <TableCell className="py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex shrink-0 items-center justify-center w-7 h-7 rounded-full bg-white/[0.06] border border-white/[0.08] text-[10px] font-medium text-white/75">
                          {initials}
                        </span>
                        <span className="text-[12px] text-white/85 truncate max-w-[140px]">{dn}</span>
                      </div>
                    </TableCell>
                    <TableCell className="py-2.5 hidden sm:table-cell">
                      {lead.email && (
                        <p className="text-[11px] text-white/65 truncate max-w-[160px]">{lead.email}</p>
                      )}
                      <div className="flex items-center gap-1 text-[11px] text-white/40">
                        <Phone size={9} />
                        {lead.phone}
                      </div>
                    </TableCell>
                    <TableCell className="py-2.5 text-[11px] text-white/50 hidden md:table-cell">
                      {lead.company ?? <span className="text-white/25">—</span>}
                    </TableCell>
                    <TableCell className="py-2.5 text-right pr-3">
                      <button
                        type="button"
                        title="Remove from list"
                        disabled={removingId === lead.id}
                        onClick={() => onRemoveLead(lead.id)}
                        className="text-white/25 hover:text-red-400 transition-colors disabled:opacity-40"
                      >
                        {removingId === lead.id
                          ? <Loader2 size={13} className="animate-spin" />
                          : <X size={13} />}
                      </button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Pagination */}
      {total > DETAIL_PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-white/40">
            {from}–{to} of {total.toLocaleString()}
          </span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => onPageChange(page - 1)}
              className="h-7 px-2 text-white/50 hover:text-white disabled:opacity-30">
              ← Prev
            </Button>
            <span className="text-[11px] text-white/40 px-1">{page + 1} / {pageCount}</span>
            <Button variant="ghost" size="sm" disabled={page >= pageCount - 1} onClick={() => onPageChange(page + 1)}
              className="h-7 px-2 text-white/50 hover:text-white disabled:opacity-30">
              Next →
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add Leads panel (inline picker)
// ---------------------------------------------------------------------------

function AddLeadsPanel({
  candidates,
  loading,
  rawSearch,
  selected,
  submitting,
  onSearchChange,
  onToggle,
  onSubmit,
}: {
  candidates: Lead[];
  loading: boolean;
  rawSearch: string;
  selected: Set<string>;
  submitting: boolean;
  onSearchChange: (v: string) => void;
  onToggle: (id: string) => void;
  onSubmit: () => void;
}) {
  return (
    <div className="rounded-[10px] border border-violet-500/25 bg-violet-500/5 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[12px] font-medium text-violet-300">Add existing leads</p>
        {selected.size > 0 && (
          <Button
            size="sm"
            disabled={submitting}
            onClick={onSubmit}
            className="h-7 px-3 text-[12px] bg-violet-600 hover:bg-violet-500 text-white"
          >
            {submitting
              ? <Loader2 size={12} className="animate-spin mr-1" />
              : <UserPlus size={12} className="mr-1" />}
            Add {selected.size} lead{selected.size !== 1 ? "s" : ""}
          </Button>
        )}
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/35 pointer-events-none" />
        <Input
          autoFocus
          value={rawSearch}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search by name, email, phone, company…"
          className="pl-8 h-8 bg-white/[0.04] border-white/[0.1] text-[12px] text-white placeholder:text-white/30"
        />
        {loading && (
          <Loader2 size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-white/30" />
        )}
      </div>

      {/* Candidates list */}
      {loading && candidates.length === 0 ? (
        <div className="space-y-1.5">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-2 py-1">
              <Skeleton className="h-5 w-5 rounded" />
              <Skeleton className="h-4 flex-1 max-w-[180px]" />
            </div>
          ))}
        </div>
      ) : candidates.length === 0 ? (
        <div className="py-4 text-center">
          <p className="text-[12px] text-white/45">
            {rawSearch
              ? "No leads matched your search"
              : "All leads are already in this list"}
          </p>
        </div>
      ) : (
        <div className="space-y-0.5 max-h-[200px] overflow-y-auto pr-1">
          {candidates.map((lead) => {
            const dn = leadDisplayName(lead);
            const isChecked = selected.has(lead.id);
            return (
              <label
                key={lead.id}
                className={cn(
                  "flex items-center gap-2.5 px-2 py-1.5 rounded-[6px] cursor-pointer transition-colors",
                  isChecked ? "bg-violet-500/15" : "hover:bg-white/[0.04]"
                )}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => onToggle(lead.id)}
                  className="w-3.5 h-3.5 rounded accent-violet-500 shrink-0"
                />
                <span className="flex-1 min-w-0">
                  <span className="text-[12px] text-white/85 truncate block">{dn}</span>
                  <span className="text-[11px] text-white/40 truncate block">
                    {lead.email || lead.phone}
                    {lead.company ? ` · ${lead.company}` : ""}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}

      {candidates.length > 0 && selected.size === 0 && (
        <p className="text-[11px] text-white/35">Select leads above then click "Add N leads"</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyListsState({ onCreateClick }: { onCreateClick: () => void }) {
  return (
    <div className="py-14 flex flex-col items-center text-center">
      <div className="h-12 w-12 rounded-full bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-4">
        <Users size={18} className="text-white/30" />
      </div>
      <p className="text-[14px] font-medium text-white/70">No lead lists yet</p>
      <p className="text-[12px] text-white/35 mt-1 max-w-[240px]">
        Create your first lead list to organise imported leads.
      </p>
      <Button
        type="button"
        size="sm"
        onClick={onCreateClick}
        className="mt-4 bg-violet-600 hover:bg-violet-500 text-white"
      >
        <Plus size={13} />
        Create lead list
      </Button>
    </div>
  );
}
