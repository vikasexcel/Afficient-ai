import { useState } from "react";
import { Copy, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { createMember, type Role } from "@/services/members";

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: () => void;
};

const ROLES: Role[] = ["admin", "agent", "member"];

export function InviteMemberDialog({ open, onOpenChange, onCreated }: Props) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [submitting, setSubmitting] = useState(false);
  const [tempPassword, setTempPassword] = useState<string | null>(null);

  function reset() {
    setName("");
    setEmail("");
    setRole("member");
    setTempPassword(null);
  }

  async function submit() {
    if (!name.trim() || !email.trim()) {
      toast.error("Name and email are required");
      return;
    }
    setSubmitting(true);
    try {
      const res = await createMember({
        full_name: name.trim(),
        email: email.trim(),
        role,
      });
      setTempPassword(res.temp_password ?? null);
      onCreated();
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? "Failed to invite member";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  function close() {
    onOpenChange(false);
    setTimeout(reset, 200);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) setTimeout(reset, 200);
      }}
    >
      <DialogContent className="bg-[#0f0f12] border-white/[0.08] sm:max-w-[440px]">
        {!tempPassword ? (
          <>
            <DialogHeader>
              <DialogTitle className="text-[15px] font-medium">
                Invite a member
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/40">
                We'll create their account with a temporary password.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4 py-2">
              <div className="space-y-1.5">
                <Label htmlFor="name" className="text-[12px] text-white/60">
                  Name
                </Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Jane Doe"
                  className="bg-white/[0.03] border-white/[0.08]"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="email" className="text-[12px] text-white/60">
                  Email
                </Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="jane@example.com"
                  className="bg-white/[0.03] border-white/[0.08]"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-[12px] text-white/60">Role</Label>
                <Select
                  value={role}
                  onValueChange={(v) => setRole(v as Role)}
                >
                  <SelectTrigger className="bg-white/[0.03] border-white/[0.08]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[#111114] border-white/[0.08]">
                    {ROLES.map((r) => (
                      <SelectItem
                        key={r}
                        value={r}
                        className="capitalize text-[12px]"
                      >
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <DialogFooter>
              <Button
                variant="ghost"
                onClick={close}
                disabled={submitting}
                className="text-white/60"
              >
                Cancel
              </Button>
              <Button
                onClick={submit}
                disabled={submitting}
                className="bg-violet-600 hover:bg-violet-500"
              >
                {submitting ? (
                  <>
                    <Loader2 size={14} className="animate-spin mr-2" />
                    Inviting…
                  </>
                ) : (
                  "Invite member"
                )}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle className="text-[15px] font-medium">
                Member created
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/40">
                Share this temporary password with them. It won't be shown
                again.
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
                  navigator.clipboard.writeText(tempPassword);
                  toast.success("Copied to clipboard");
                }}
              >
                <Copy size={13} />
              </Button>
            </div>

            <DialogFooter>
              <Button onClick={close} className="bg-violet-600 hover:bg-violet-500">
                Done
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
