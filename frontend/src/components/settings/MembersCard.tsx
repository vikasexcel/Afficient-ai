import { useCallback, useEffect, useState } from "react";
import { Copy, Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { InviteMemberDialog } from "@/components/members/InviteMemberDialog";
import { MembersTable } from "@/components/members/MembersTable";

import {
  listMembers,
  removeMember,
  resetMemberPassword,
  updateRole,
  type Member,
  type Role,
} from "@/services/members";
import { canManageMembers, useMe } from "@/store/me";

export default function MembersCard() {
  const me = useMe((s) => s.data);
  const canManage = canManageMembers(me?.role);

  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);

  const [inviteOpen, setInviteOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<Member | null>(null);
  const [tempPassword, setTempPassword] = useState<string | null>(null);
  const [resetTarget, setResetTarget] = useState<Member | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await listMembers();
      setMembers(list);
    } catch {
      toast.error("Failed to load members");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleChangeRole(m: Member, role: Role) {
    if (m.role === role) return;
    try {
      const updated = await updateRole(m.membership_id, role);
      setMembers((prev) =>
        prev.map((x) => (x.membership_id === m.membership_id ? updated : x))
      );
      toast.success(`${m.full_name} is now ${role}`);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Failed to update role");
    }
  }

  async function handleResetPassword(m: Member) {
    try {
      const res = await resetMemberPassword(m.membership_id);
      setTempPassword(res.temp_password);
      setResetTarget(m);
      if (res.email_sent) {
        toast.success(`New password emailed to ${m.email}`);
      }
      load();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Failed to reset password");
    }
  }

  async function confirmRemove() {
    if (!removeTarget) return;
    try {
      const res = await removeMember(removeTarget.membership_id);
      setMembers((prev) =>
        prev.filter((x) => x.membership_id !== removeTarget.membership_id)
      );
      if (res.email_sent) {
        toast.success(
          `${removeTarget.full_name} removed. We've notified ${removeTarget.email}.`
        );
      } else {
        toast.success(`${removeTarget.full_name} removed`);
      }
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Failed to remove member");
    } finally {
      setRemoveTarget(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[15px] font-medium text-white">
            Members
          </h2>
          <p className="text-[12px] text-white/40">
            Manage who can access {me?.organization?.name ?? "this organization"}.
          </p>
        </div>

        {canManage && (
          <Button
            onClick={() => setInviteOpen(true)}
            className="bg-violet-600 hover:bg-violet-500 h-8 text-[12px] font-medium self-start sm:self-auto"
          >
            <Plus size={14} className="mr-1.5" />
            Invite member
          </Button>
        )}
      </div>

      <div className="rounded-[10px] border border-white/[0.05] overflow-hidden">
        <MembersTable
          members={members}
          loading={loading}
          canManage={canManage}
          currentRole={(me?.role as Role | undefined) ?? null}
          currentMembershipId={me?.membership_id ?? null}
          onChangeRole={handleChangeRole}
          onResetPassword={handleResetPassword}
          onRemove={(m) => setRemoveTarget(m)}
        />
      </div>

      <InviteMemberDialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        onCreated={load}
      />

      <AlertDialog
        open={!!removeTarget}
        onOpenChange={(v) => !v && setRemoveTarget(null)}
      >
        <AlertDialogContent className="bg-[#0f0f12] border-white/[0.08]">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px] font-medium">
              Remove {removeTarget?.full_name}?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12px] text-white/45">
              They will lose access to {me?.organization?.name ?? "this org"}.
              You can re-invite them later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-transparent border-white/[0.08] text-white/70">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmRemove}
              className="bg-red-600 hover:bg-red-500"
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog
        open={!!tempPassword}
        onOpenChange={(v) => {
          if (!v) {
            setTempPassword(null);
            setResetTarget(null);
          }
        }}
      >
        <DialogContent className="bg-[#0f0f12] border-white/[0.08] sm:max-w-[440px]">
          <DialogHeader>
            <DialogTitle className="text-[15px] font-medium">
              Password reset
            </DialogTitle>
            <DialogDescription className="text-[12px] text-white/40">
              {resetTarget
                ? `We've emailed the new password to ${resetTarget.email}.`
                : "Share this temporary password with the member."}{" "}
              It won't be shown again.
            </DialogDescription>
          </DialogHeader>

          <div className="my-3 rounded-[8px] border border-white/[0.08] bg-white/[0.03] p-3 flex items-center justify-between gap-3">
            <code className="text-[13px] text-violet-300 font-mono break-all">
              {tempPassword}
            </code>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-white/50 hover:text-white shrink-0"
              onClick={() => {
                if (tempPassword) {
                  navigator.clipboard.writeText(tempPassword);
                  toast.success("Copied");
                }
              }}
            >
              <Copy size={13} />
            </Button>
          </div>

          <DialogFooter>
            <Button
              onClick={() => {
                setTempPassword(null);
                setResetTarget(null);
              }}
              className="bg-violet-600 hover:bg-violet-500"
            >
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
