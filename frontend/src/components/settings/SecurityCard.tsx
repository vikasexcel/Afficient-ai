import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LogOut, ShieldCheck } from "lucide-react";
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

import { logout as apiLogout } from "@/services/auth";
import { useAuth } from "@/store/auth";
import { useMe } from "@/store/me";

export default function SecurityCard() {
  const nav = useNavigate();
  const refreshToken = useAuth((s) => s.refreshToken);
  const clearAuth = useAuth((s) => s.logout);
  const resetMe = useMe((s) => s.reset);

  const [confirming, setConfirming] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  async function signOutEverywhere() {
    setSigningOut(true);
    try {
      if (refreshToken) {
        try {
          await apiLogout(refreshToken);
        } catch {
          /* token may already be invalid */
        }
      }
      clearAuth();
      resetMe();
      toast.success("Signed out of all sessions");
      nav("/login");
    } finally {
      setSigningOut(false);
      setConfirming(false);
    }
  }

  return (
    <div className="space-y-6 max-w-lg">
      <div>
        <h2 className="text-[15px] font-medium text-white">Security</h2>
        <p className="text-[12px] text-white/40 mt-0.5">
          Manage your account access and active sessions.
        </p>
      </div>

      <section className="rounded-[10px] border border-white/[0.05] bg-white/[0.02] p-4 flex items-start gap-3">
        <div className="h-8 w-8 rounded-[8px] bg-violet-500/10 border border-violet-500/20 flex items-center justify-center shrink-0">
          <ShieldCheck size={14} className="text-violet-300" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] text-white/85 font-medium">Password</p>
          <p className="text-[12px] text-white/40 mt-0.5">
            You sign in with email and password. Password reset and 2FA are
            coming soon.
          </p>
        </div>
      </section>

      <section className="space-y-3 pt-5 border-t border-white/[0.05]">
        <div>
          <h3 className="text-[13px] font-medium text-white">Active sessions</h3>
          <p className="text-[12px] text-white/40 mt-0.5">
            Sign out of every device where this account is logged in.
          </p>
        </div>

        <Button
          variant="outline"
          className="border-white/[0.08] bg-white/[0.03] text-white/85 hover:bg-white/[0.06] hover:text-white dark:bg-white/[0.03] dark:hover:bg-white/[0.06]"
          onClick={() => setConfirming(true)}
        >
          <LogOut size={13} className="mr-1.5" />
          Sign out everywhere
        </Button>
      </section>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent className="bg-[#0f0f12] border-white/[0.08]">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px] font-medium">
              Sign out of all sessions?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[12px] text-white/45">
              You'll have to sign in again on every device, including this one.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-transparent border-white/[0.08] text-white/70">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={signOutEverywhere}
              disabled={signingOut}
              className="bg-red-600 hover:bg-red-500"
            >
              {signingOut ? "Signing out…" : "Sign out"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
