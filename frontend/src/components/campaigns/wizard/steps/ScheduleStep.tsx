import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { WEEKDAYS, type Weekday } from "@/types/campaign";
import type { WizardDraft } from "../types";
import { COMMON_TIMEZONES } from "../types";

interface Props {
  draft: WizardDraft;
  onChange: (partial: Partial<WizardDraft>) => void;
}

function todayDate() {
  return new Date().toISOString().slice(0, 10);
}

export default function ScheduleStep({ draft, onChange }: Props) {
  const { business_hours: bh } = draft;

  function toggleDay(day: Weekday) {
    const days = bh.days.includes(day)
      ? bh.days.filter((d) => d !== day)
      : [...bh.days, day];
    onChange({ business_hours: { ...bh, days } });
  }

  const pastError =
    !draft.start_immediately &&
    draft.scheduled_date &&
    draft.scheduled_date < todayDate();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-base font-semibold text-white">Schedule</h2>
        <p className="text-[13px] text-white/40 mt-0.5">
          Configure when the campaign starts and the business hours it operates in.
        </p>
      </div>

      <div className="flex flex-col gap-5">
        {/* Start immediately toggle */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[13px] text-white/80 font-medium">Start immediately</p>
            <p className="text-[11px] text-white/35">Launch as soon as the campaign is activated</p>
          </div>
          <Switch
            checked={draft.start_immediately}
            onCheckedChange={(v) =>
              onChange({
                start_immediately: v,
                scheduled_date: v ? null : draft.scheduled_date,
                scheduled_time: v ? null : draft.scheduled_time,
              })
            }
          />
        </div>

        {/* Scheduled date + time */}
        {!draft.start_immediately && (
          <div className="flex gap-3">
            <div className="flex flex-col gap-1.5 flex-1">
              <Label className="text-white/70 text-xs uppercase tracking-widest">Start date</Label>
              <Input
                type="date"
                min={todayDate()}
                value={draft.scheduled_date ?? ""}
                onChange={(e) => onChange({ scheduled_date: e.target.value || null })}
                className="bg-white/5 border-white/10 text-white"
              />
              {pastError && (
                <p className="text-[11px] text-rose-400/70">Cannot schedule in the past</p>
              )}
            </div>
            <div className="flex flex-col gap-1.5 w-32">
              <Label className="text-white/70 text-xs uppercase tracking-widest">Start time</Label>
              <Input
                type="time"
                value={draft.scheduled_time ?? ""}
                onChange={(e) => onChange({ scheduled_time: e.target.value || null })}
                className="bg-white/5 border-white/10 text-white"
              />
            </div>
          </div>
        )}

        {/* Timezone */}
        <div className="flex flex-col gap-1.5">
          <Label className="text-white/70 text-xs uppercase tracking-widest">Timezone</Label>
          <Select
            value={draft.timezone}
            onValueChange={(v) => onChange({ timezone: v })}
          >
            <SelectTrigger className="bg-white/5 border-white/10 text-white">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1a1a2e] border-white/10">
              {COMMON_TIMEZONES.map((tz) => (
                <SelectItem key={tz} value={tz} className="text-white focus:bg-white/10">
                  {tz}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Business hours */}
        <div className="flex flex-col gap-3">
          <Label className="text-white/70 text-xs uppercase tracking-widest">Business hours</Label>

          {/* Days */}
          <div className="flex gap-1.5 flex-wrap">
            {WEEKDAYS.map((d) => {
              const active = bh.days.includes(d.id);
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => toggleDay(d.id)}
                  className={`px-3 py-1.5 rounded text-[11px] font-medium transition-colors ${
                    active
                      ? "bg-violet-600 text-white"
                      : "bg-white/5 text-white/40 hover:bg-white/10 hover:text-white/70"
                  }`}
                >
                  {d.short}
                </button>
              );
            })}
          </div>

          {/* Hours window */}
          <div className="flex gap-3 items-center">
            <div className="flex flex-col gap-1 flex-1">
              <Label className="text-white/40 text-[10px] uppercase tracking-widest">From</Label>
              <Input
                type="time"
                value={bh.start}
                onChange={(e) =>
                  onChange({ business_hours: { ...bh, start: e.target.value } })
                }
                className="bg-white/5 border-white/10 text-white text-sm"
              />
            </div>
            <span className="text-white/30 text-sm mt-4">–</span>
            <div className="flex flex-col gap-1 flex-1">
              <Label className="text-white/40 text-[10px] uppercase tracking-widest">To</Label>
              <Input
                type="time"
                value={bh.end}
                onChange={(e) =>
                  onChange({ business_hours: { ...bh, end: e.target.value } })
                }
                className="bg-white/5 border-white/10 text-white text-sm"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
