import { useMemo, useState } from "react";
import type { MeetingsTrendData, MeetingsDailyPoint } from "@/services/analytics";

interface Props {
  data: MeetingsTrendData;
  /** Show the daily/weekly toggle. Default true. */
  showToggle?: boolean;
}

// Stable palette — cycles if there are more than 8 campaigns
const PALETTE = [
  "#8b5cf6", "#38bdf8", "#4ade80", "#f59e0b",
  "#f87171", "#a78bfa", "#34d399", "#fb923c",
];

function groupByWeek(daily: MeetingsDailyPoint[]): MeetingsDailyPoint[] {
  const buckets: Map<number, MeetingsDailyPoint> = new Map();
  daily.forEach((d) => {
    const ts = new Date(d.date).getTime();
    // Round down to start of ISO week (Monday)
    const day = new Date(ts);
    const diff = (day.getDay() + 6) % 7; // 0=Mon … 6=Sun
    day.setDate(day.getDate() - diff);
    const key = day.getTime();
    if (!buckets.has(key)) {
      buckets.set(key, {
        date: day.toISOString().slice(0, 10),
        total: 0,
        by_campaign: [],
      });
    }
    const bucket = buckets.get(key)!;
    bucket.total += d.total;
    d.by_campaign.forEach(({ campaign_id, campaign_name, count }) => {
      const existing = bucket.by_campaign.find((x) => x.campaign_id === campaign_id);
      if (existing) {
        existing.count += count;
      } else {
        bucket.by_campaign.push({ campaign_id, campaign_name, count });
      }
    });
  });
  return Array.from(buckets.values()).sort((a, b) => a.date.localeCompare(b.date));
}

export default function MeetingsChart({ data, showToggle = true }: Props) {
  const [groupBy, setGroupBy] = useState<"day" | "week">("day");

  const points = useMemo(
    () => (groupBy === "week" ? groupByWeek(data.daily) : data.daily),
    [data.daily, groupBy]
  );

  // Collect all unique campaigns and assign colors
  const campaigns = useMemo(() => {
    const seen = new Map<string, string>();
    data.daily.forEach((d) =>
      d.by_campaign.forEach(({ campaign_id, campaign_name }) => {
        if (!seen.has(campaign_id)) {
          seen.set(campaign_id, campaign_name);
        }
      })
    );
    return Array.from(seen.entries()).map(([id, name], i) => ({
      id,
      name,
      color: PALETTE[i % PALETTE.length],
    }));
  }, [data.daily]);

  const maxVal = useMemo(
    () => Math.max(...points.map((p) => p.total), 1),
    [points]
  );

  if (data.daily.length === 0) {
    return (
      <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
        <h2 className="text-[14px] font-medium text-white">Meetings Booked</h2>
        <p className="text-[12px] text-white/30 mt-6 text-center py-8">
          No meetings booked in the selected period
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] p-5">
      <div className="flex items-center justify-between mb-1">
        <div>
          <h2 className="text-[14px] font-medium text-white">Meetings Booked</h2>
          <p className="text-[12px] text-white/40">
            {data.total.toLocaleString()} total · by campaign
          </p>
        </div>

        {showToggle && (
          <div className="inline-flex rounded-[7px] border border-white/[0.08] bg-white/[0.02] p-0.5">
            {(["day", "week"] as const).map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => setGroupBy(g)}
                className={`px-2.5 h-6 rounded-[5px] text-[11px] transition-colors ${
                  groupBy === g
                    ? "bg-white/[0.07] text-white"
                    : "text-white/45 hover:text-white/75"
                }`}
              >
                {g === "day" ? "Daily" : "Weekly"}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Bar chart */}
      <div className="mt-5 flex items-end gap-1 h-36">
        {points.map((point) => (
          <div
            key={point.date}
            className="flex-1 flex flex-col items-center gap-0.5 min-w-0 h-full"
            title={`${point.date}: ${point.total} meetings`}
          >
            {/* Stacked bar */}
            <div className="w-full flex flex-col-reverse items-stretch justify-start" style={{ height: `${(point.total / maxVal) * 100}%` }}>
              {point.by_campaign.map(({ campaign_id, count }) => {
                const camp = campaigns.find((c) => c.id === campaign_id);
                const segH = point.total ? (count / point.total) * 100 : 0;
                return (
                  <div
                    key={campaign_id}
                    className="w-full rounded-t-[2px] first:rounded-t-[2px] last:rounded-b-none"
                    style={{
                      height: `${segH}%`,
                      background: camp?.color ?? "#8b5cf6",
                      minHeight: count > 0 ? "2px" : "0",
                    }}
                    title={`${camp?.name ?? campaign_id}: ${count}`}
                  />
                );
              })}
            </div>
            <span className="text-[9px] text-white/25 truncate max-w-full">
              {point.date.slice(5)}
            </span>
          </div>
        ))}
      </div>

      {/* Legend */}
      {campaigns.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
          {campaigns.map((c) => (
            <span key={c.id} className="inline-flex items-center gap-1.5 text-[11px] text-white/50">
              <span className="h-2 w-2 rounded-sm shrink-0" style={{ background: c.color }} />
              {c.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
