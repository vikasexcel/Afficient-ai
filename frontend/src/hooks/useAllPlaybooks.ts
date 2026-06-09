import { useCallback, useEffect, useState } from "react";

import { listPlaybooks, type PlaybookSummary } from "@/services/playbook";

const REFRESH_MS = 20_000;

/**
 * All playbooks (any status) for the workflow builder.
 * Auto-refreshes on interval and tab focus so newly created
 * playbooks appear without a full page reload.
 */
export function useAllPlaybooks(enabled = true) {
  const [playbooks, setPlaybooks] = useState<PlaybookSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await listPlaybooks(false);
      setPlaybooks(rows);
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Failed to load playbooks";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    reload();
    const interval = setInterval(reload, REFRESH_MS);
    const onFocus = () => reload();
    const onVisibility = () => {
      if (document.visibilityState === "visible") reload();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, reload]);

  return { playbooks, loading, error, reload };
}
