import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

import {
  deleteOrganization,
  getOrganization,
  renameOrganization,
  transferOwnership,
} from "@/services/organization";
import { listMembers, type Member } from "@/services/members";
import { useAuth } from "@/store/auth";
import { useMe, canManageMembers, isOwner } from "@/store/me";

export default function OrganizationCard() {
  const nav = useNavigate();
  const me = useMe((s) => s.data);
  const loadMe = useMe((s) => s.load);
  const logout = useAuth((s) => s.logout);
  const resetMe = useMe((s) => s.reset);

  const canManage = canManageMembers(me?.role);
  const owner = isOwner(me?.role);

  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [transferTo, setTransferTo] = useState("");
  const [transferring, setTransferring] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    getOrganization()
      .then((org) => setName(org.name))
      .catch(() => toast.error("Failed to load organization"));
  }, []);

  useEffect(() => {
    if (!owner) return;
    listMembers()
      .then(setMembers)
      .catch(() => {});
  }, [owner]);

  const transferCandidates = members.filter(
    (m) => m.membership_id !== me?.membership_id && m.role !== "owner"
  );

  async function saveName() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const org = await renameOrganization(name.trim());
      setName(org.name);
      await loadMe();
      toast.success("Organization renamed");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Failed to rename");
    } finally {
      setSaving(false);
    }
  }

  async function transfer() {
    if (!transferTo) return;
    setTransferring(true);
    try {
      await transferOwnership(transferTo);
      await loadMe();
      toast.success("Ownership transferred");
      setTransferTo("");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Transfer failed");
    } finally {
      setTransferring(false);
    }
  }

  async function deleteOrg() {
    if (deleteConfirm !== name) {
      toast.error("Organization name does not match");
      return;
    }
    setDeleting(true);
    try {
      await deleteOrganization();
      logout();
      resetMe();
      nav("/login");
      toast.success("Organization deleted");
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Delete failed");
    } finally {
      setDeleting(false);
      setDeleteOpen(false);
    }
  }

  if (!canManage) {
    return (
      <p className="text-[13px] text-white/40">
        Only Owners and Admins can manage organization settings.
      </p>
    );
  }

  return (
    <div className="space-y-8 max-w-lg">
      <section className="space-y-3">
        <div>
          <h2 className="text-[15px] font-medium text-white">Organization</h2>
          <p className="text-[12px] text-white/40 mt-0.5">
            Rename your workspace.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="org-name" className="text-[12px] text-white/60">
            Name
          </Label>
          <div className="flex gap-2">
            <Input
              id="org-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="bg-white/[0.03] border-white/[0.08]"
            />
            <Button
              onClick={saveName}
              disabled={saving}
              className="bg-violet-600 hover:bg-violet-500 shrink-0"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : "Save"}
            </Button>
          </div>
        </div>
      </section>

      {owner && (
        <>
          <section className="space-y-3 pt-6 border-t border-white/[0.05]">
            <div>
              <h2 className="text-[15px] font-medium text-white">
                Transfer ownership
              </h2>
              <p className="text-[12px] text-white/40 mt-0.5">
                Make another member the Owner. You will become an Admin.
              </p>
            </div>

            <div className="flex gap-2">
              <Select value={transferTo} onValueChange={setTransferTo}>
                <SelectTrigger className="bg-white/[0.03] border-white/[0.08] flex-1">
                  <SelectValue placeholder="Select member" />
                </SelectTrigger>
                <SelectContent className="bg-[#111114] border-white/[0.08]">
                  {transferCandidates.map((m) => (
                    <SelectItem
                      key={m.membership_id}
                      value={m.membership_id}
                      className="text-[12px]"
                    >
                      {m.full_name} ({m.email})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                onClick={transfer}
                disabled={!transferTo || transferring}
                variant="outline"
                className="border-white/[0.08] shrink-0"
              >
                {transferring ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  "Transfer"
                )}
              </Button>
            </div>
          </section>

          <section className="space-y-3 pt-6 border-t border-white/[0.05]">
            <div>
              <h2 className="text-[15px] font-medium text-red-400">
                Danger zone
              </h2>
              <p className="text-[12px] text-white/40 mt-0.5">
                Permanently delete this organization and all memberships.
              </p>
            </div>

            <Button
              variant="outline"
              className="border-red-500/30 text-red-400 hover:bg-red-500/[0.08] hover:text-red-300"
              onClick={() => {
                setDeleteConfirm("");
                setDeleteOpen(true);
              }}
            >
              Delete organization
            </Button>
          </section>
        </>
      )}

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent className="bg-[#0f0f12] border-white/[0.08]">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px] font-medium text-red-400">
              Delete {name}?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12px] text-white/45">
              This cannot be undone. Type{" "}
              <span className="text-white/80 font-mono">{name}</span> to confirm.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <Input
            value={deleteConfirm}
            onChange={(e) => setDeleteConfirm(e.target.value)}
            placeholder={name}
            className="bg-white/[0.03] border-white/[0.08]"
          />

          <AlertDialogFooter>
            <AlertDialogCancel className="bg-transparent border-white/[0.08] text-white/70">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={deleteOrg}
              disabled={deleting || deleteConfirm !== name}
              className="bg-red-600 hover:bg-red-500"
            >
              {deleting ? "Deleting…" : "Delete forever"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
