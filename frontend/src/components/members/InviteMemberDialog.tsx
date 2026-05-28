import { useState } from "react";
import { Copy, Info, Loader2, Mail } from "lucide-react";
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
  const [accountExists, setAccountExists] = useState(false);
  const [emailSent, setEmailSent] = useState(false);
  const [done, setDone] = useState(false);

  function reset() {
    setName("");
    setEmail("");
    setRole("member");
    setTempPassword(null);
    setAccountExists(false);
    setEmailSent(false);
    setDone(false);
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
        email: email.trim().toLowerCase(),
        role,
      });
      setTempPassword(res.temp_password ?? null);
      setAccountExists(!!res.account_exists);
      setEmailSent(!!res.email_sent);
      setDone(true);
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
        {!done ? (
          <>
            <DialogHeader>
              <DialogTitle className="text-[15px] font-medium">
                Invite a member
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/40">
                We'll create their account and email them the sign-in details.
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
                Member added
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/40">
                {accountExists
                  ? "This person already has an Aifficient account, so they'll sign in with their existing password."
                  : emailSent
                    ? `We've emailed sign-in details to ${email.trim()}.`
                    : "Share this temporary password with them. It won't be shown again."}
              </DialogDescription>
            </DialogHeader>

            {accountExists ? (
              <div className="my-3 rounded-[8px] border border-violet-500/20 bg-violet-500/[0.06] p-3 flex gap-2.5 items-start">
                <Info size={14} className="text-violet-300 shrink-0 mt-0.5" />
                <p className="text-[12px] text-white/70 leading-relaxed">
                  No new password was created. Ask {email.trim()} to log in with
                  the password they already use.
                </p>
              </div>
            ) : tempPassword ? (
              <div className="my-3 space-y-2">
                <div className="rounded-[8px] border border-white/[0.08] bg-white/[0.03] p-3 flex items-center justify-between gap-3">
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
                {emailSent && (
                  <p className="flex items-center gap-1.5 text-[11px] text-white/40 px-1">
                    <Mail size={11} className="text-violet-300/80" />
                    Also sent to {email.trim()}.
                  </p>
                )}
              </div>
            ) : null}

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
