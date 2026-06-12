import { useEffect, useState } from "react";
import { CalendarDays, CheckCircle2, ExternalLink, Loader2, Unlink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useMe } from "@/store/me";
import {
  getCalendarStatus,
  disconnectCalendar,
  type CalendarIntegration,
} from "@/services/calendar";
import { toast } from "sonner";

export default function CalendarIntegrationCard() {
  const me = useMe((s) => s.data);
  const [integration, setIntegration] = useState<CalendarIntegration | null | undefined>(
    undefined
  );
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getCalendarStatus()
      .then(setIntegration)
      .catch(() => setIntegration(null));
  }, []);

  // Handle redirect back from OAuth callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("connected") === "1") {
      toast.success("Google Calendar connected successfully!");
      window.history.replaceState({}, "", window.location.pathname);
      getCalendarStatus().then(setIntegration).catch(() => {});
    }
    if (params.get("error")) {
      toast.error("Google Calendar connection failed. Please try again.");
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  const handleConnect = async () => {
    const orgId = me?.organization?.id;
    if (!orgId) return;
    setLoading(true);
    try {
      const apiBase = (import.meta.env.VITE_API_URL ?? "http://localhost:8001/api/v1")
        .replace("/api/v1", "");
      const token = localStorage.getItem("token") ?? "";

      // Fetch the auth URL with the Authorization header, then redirect
      const res = await fetch(
        `${apiBase}/auth/google?org_id=${orgId}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) throw new Error(`${res.status}`);
      const { auth_url } = await res.json();
      window.location.href = auth_url;
    } catch {
      toast.error("Failed to start Google Calendar connection.");
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    try {
      await disconnectCalendar();
      setIntegration(null);
      toast.success("Google Calendar disconnected.");
    } catch {
      toast.error("Failed to disconnect calendar.");
    } finally {
      setLoading(false);
    }
  };

  const isConnected = integration?.connected === true;

  return (
    <div className="space-y-4 max-w-lg">
      <div>
        <h2 className="text-[15px] font-medium text-white">
          Calendar Integration
        </h2>
        <p className="text-[12px] text-white/40 mt-0.5">
          Connect Google Calendar to enable automatic meeting booking during AI
          calls.
        </p>
      </div>

      <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-5">
        <div className="flex items-center justify-between gap-4">
          {/* Left — icon + info */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-white/[0.07] flex items-center justify-center flex-shrink-0">
              <CalendarDays className="w-5 h-5 text-white/70" />
            </div>
            <div>
              <p className="text-[14px] font-medium text-white">
                Google Calendar
              </p>
              {integration === undefined ? (
                <p className="text-[12px] text-white/40">Loading…</p>
              ) : isConnected ? (
                <div className="flex items-center gap-1.5 mt-0.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <p className="text-[12px] text-emerald-400">
                    Connected
                    {integration?.calendar_email
                      ? ` · ${integration.calendar_email}`
                      : ""}
                  </p>
                </div>
              ) : (
                <p className="text-[12px] text-white/40">Not connected</p>
              )}
            </div>
          </div>

          {/* Right — action button */}
          {integration === undefined ? (
            <Loader2 className="w-4 h-4 animate-spin text-white/30" />
          ) : isConnected ? (
            <Button
              variant="outline"
              size="sm"
              onClick={handleDisconnect}
              disabled={loading}
              className="text-red-400 border-red-400/30 hover:bg-red-400/10 hover:text-red-300 text-[12px] gap-1.5"
            >
              {loading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Unlink className="w-3.5 h-3.5" />
              )}
              Disconnect
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleConnect}
              disabled={loading}
              className="bg-violet-600 hover:bg-violet-500 text-white text-[12px] gap-1.5"
            >
              {loading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <ExternalLink className="w-3.5 h-3.5" />
              )}
              Connect
            </Button>
          )}
        </div>

        {isConnected && (
          <div className="mt-4 pt-4 border-t border-white/[0.06]">
            <p className="text-[12px] text-white/40">
              The AI agent will automatically check availability and book
              meetings during calls. Confirmation emails are sent to leads with
              Google Meet links.
            </p>
          </div>
        )}
      </div>

      {!isConnected && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
          <p className="text-[12px] text-amber-300/80">
            <strong className="text-amber-300">Setup required: </strong>
            After connecting, the AI agent on calls can automatically check your
            calendar, book meetings, and send invites — no manual scheduling
            needed.
          </p>
        </div>
      )}
    </div>
  );
}
