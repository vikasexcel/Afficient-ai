import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";

import { getSchedulerStatus, type SchedulerStatus } from "@/services/campaign";
import { useAuth } from "@/store/auth";

const POLL_MS = 60_000;

export default function SchedulerOfflineBanner() {
  const accessToken = useAuth((s) => s.accessToken);
  const [status, setStatus] = useState<SchedulerStatus | null>(null);

  useEffect(() => {
    if (!accessToken) {
      setStatus(null);
      return;
    }

    let cancelled = false;

    async function poll() {
      try {
        const next = await getSchedulerStatus();
        if (!cancelled) setStatus(next);
      } catch {
        if (!cancelled) setStatus(null);
      }
    }

    void poll();
    const id = window.setInterval(() => void poll(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [accessToken]);

  if (!status || status.scheduler_online) {
    return null;
  }

  const parts: string[] = [];
  if (!status.redis_connected) parts.push("Redis unreachable");
  if (!status.beat_running) parts.push("Celery Beat offline");
  if (!status.worker_running) parts.push("Celery worker offline");

  const detail =
    parts.length > 0
      ? parts.join(" · ")
      : status.message;

  const queued =
    status.queued_executions > 0
      ? ` ${status.queued_executions} call(s) queued and will not dial until the scheduler is running.`
      : "";

  return (
    <div
      role="alert"
      className="shrink-0 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-100"
    >
      <div className="flex items-start gap-2 max-w-screen-2xl mx-auto">
        <AlertTriangle
          className="h-4 w-4 mt-0.5 shrink-0 text-amber-400"
          aria-hidden
        />
        <div>
          <p className="font-medium text-amber-200">
            Campaign scheduler offline — activated campaigns will not place calls.
          </p>
          <p className="text-amber-100/80 mt-0.5">
            {detail}.{queued}
          </p>
        </div>
      </div>
    </div>
  );
}
