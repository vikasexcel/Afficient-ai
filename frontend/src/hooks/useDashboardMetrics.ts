import { useCallback, useEffect, useRef, useState } from "react";
import { analyticsApi, type CallAnalyticsData, type FunnelData, type OverviewData } from "@/services/analytics";

export interface DashboardMetrics {
  callsMade: number;
  connectedRate: number;
  meetingsBooked: number;
  // Deltas vs yesterday (percentage points or absolute)
  callsMadeDelta: number | null;
  connectedRateDelta: number | null;
  meetingsBookedDelta: number | null;
  funnel: FunnelData | null;
  loading: boolean;
  error: string | null;
}

const EMPTY: DashboardMetrics = {
  callsMade: 0,
  connectedRate: 0,
  meetingsBooked: 0,
  callsMadeDelta: null,
  connectedRateDelta: null,
  meetingsBookedDelta: null,
  funnel: null,
  loading: true,
  error: null,
};

function connectRate(calls: CallAnalyticsData): number {
  if (!calls.attempted) return 0;
  return Math.round((calls.completed / calls.attempted) * 100);
}

export function useDashboardMetrics(refreshIntervalMs = 30_000): DashboardMetrics {
  const [state, setState] = useState<DashboardMetrics>(EMPTY);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetch = useCallback(async () => {
    try {
      // Fetch today (days=1) and a 2-day window to derive yesterday's value
      const [today, twoDays, funnel] = await Promise.all([
        Promise.all([analyticsApi.overview(1), analyticsApi.calls(1)]),
        Promise.all([analyticsApi.overview(2), analyticsApi.calls(2)]),
        analyticsApi.funnel(30),
      ]);

      const [ovToday, callsToday] = today;
      const [ovTwo, callsTwo] = twoDays;

      // Yesterday's values = 2-day total minus today's
      const callsYesterday = callsTwo.attempted - callsToday.attempted;
      const meetingsYesterday =
        (ovTwo.leads.converted ?? 0) - (ovToday.leads.converted ?? 0);
      const rateToday = connectRate(callsToday);
      const rateTwo = connectRate(callsTwo);
      const rateYesterday = rateTwo - rateToday;

      const callsDelta = callsYesterday
        ? Math.round(((callsToday.attempted - callsYesterday) / callsYesterday) * 100)
        : null;
      const meetingsDelta = meetingsYesterday
        ? Math.round(
            ((ovToday.leads.converted - meetingsYesterday) / meetingsYesterday) * 100
          )
        : null;
      const rateDelta = rateYesterday !== 0 ? rateToday - rateTwo + rateYesterday : null;

      setState({
        callsMade: callsToday.attempted,
        connectedRate: rateToday,
        meetingsBooked: ovToday.leads.converted,
        callsMadeDelta: callsDelta,
        connectedRateDelta: rateDelta,
        meetingsBookedDelta: meetingsDelta,
        funnel,
        loading: false,
        error: null,
      });
    } catch (err) {
      setState((prev) => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : "Failed to load metrics",
      }));
    }
  }, []);

  useEffect(() => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    void fetch();
    intervalRef.current = setInterval(() => void fetch(), refreshIntervalMs);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetch, refreshIntervalMs]);

  return state;
}
