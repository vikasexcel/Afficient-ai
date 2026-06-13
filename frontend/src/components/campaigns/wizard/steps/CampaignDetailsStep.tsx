import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { WizardDraft } from "../types";
import { COMMON_TIMEZONES } from "../types";

interface Props {
  draft: WizardDraft;
  onChange: (partial: Partial<WizardDraft>) => void;
}

export default function CampaignDetailsStep({ draft, onChange }: Props) {
  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-[13px] text-white/40 mt-0.5">
          Give your campaign a name and set the operating timezone.
        </p>
      </div>

      <div className="flex flex-col gap-6">
        {/* Name */}
        <div className="flex flex-col gap-2">
          <Label className="text-white/55 text-[10px] uppercase tracking-[0.12em] font-semibold">
            Campaign Name <span className="text-rose-400">*</span>
          </Label>
          <Input
            value={draft.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="e.g. Q3 Cold Outreach"
            maxLength={200}
            className="bg-white/[0.04] border-white/[0.10] text-white placeholder:text-white/20 h-11 text-[14px] focus:border-violet-500/60 focus:bg-white/[0.06] transition-colors"
          />
          {draft.name.trim().length === 0 ? (
            <p className="text-[11px] text-rose-400/60">Name is required to continue</p>
          ) : (
            <p className="text-[11px] text-white/25">{draft.name.trim().length}/200 characters</p>
          )}
        </div>

        {/* Timezone */}
        <div className="flex flex-col gap-2">
          <Label className="text-white/55 text-[10px] uppercase tracking-[0.12em] font-semibold">
            Timezone
          </Label>
          <Select
            value={draft.timezone}
            onValueChange={(v) => onChange({ timezone: v })}
          >
            <SelectTrigger className="bg-white/[0.04] border-white/[0.10] text-white h-11 focus:border-violet-500/60 focus:bg-white/[0.06] transition-colors">
              <SelectValue placeholder="Select timezone…" />
            </SelectTrigger>
            <SelectContent className="bg-[#13131f] border-white/[0.10] shadow-2xl shadow-black/50">
              {COMMON_TIMEZONES.map((tz) => (
                <SelectItem key={tz} value={tz} className="text-white/80 focus:bg-violet-900/30 focus:text-white">
                  {tz}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[11px] text-white/25">
            Used for scheduling and business-hours enforcement
          </p>
        </div>
      </div>
    </div>
  );
}
