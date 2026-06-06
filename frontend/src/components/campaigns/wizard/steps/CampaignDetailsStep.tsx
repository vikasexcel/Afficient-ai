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
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-base font-semibold text-white">Campaign Details</h2>
        <p className="text-[13px] text-white/40 mt-0.5">Give your campaign a name and set the operating timezone.</p>
      </div>

      <div className="flex flex-col gap-5">
        {/* Name */}
        <div className="flex flex-col gap-1.5">
          <Label className="text-white/70 text-xs uppercase tracking-widest">
            Campaign Name <span className="text-rose-400">*</span>
          </Label>
          <Input
            value={draft.name}
            onChange={(e) => onChange({ name: e.target.value })}
            placeholder="e.g. Q3 Cold Outreach"
            maxLength={200}
            className="bg-white/5 border-white/10 text-white placeholder:text-white/25"
          />
          {draft.name.trim().length === 0 && (
            <p className="text-[11px] text-rose-400/70">Name is required</p>
          )}
        </div>

        {/* Timezone */}
        <div className="flex flex-col gap-1.5">
          <Label className="text-white/70 text-xs uppercase tracking-widest">Timezone</Label>
          <Select
            value={draft.timezone}
            onValueChange={(v) => onChange({ timezone: v })}
          >
            <SelectTrigger className="bg-white/5 border-white/10 text-white">
              <SelectValue placeholder="Select timezone…" />
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
      </div>
    </div>
  );
}
