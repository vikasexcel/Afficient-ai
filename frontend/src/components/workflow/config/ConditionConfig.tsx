import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ConditionConfig } from "@/types/workflow";

const CONDITION_OPTIONS: { value: ConditionConfig["condition_type"]; label: string; description: string }[] = [
  { value: "EMAIL_SENT",      label: "Email sent",                     description: "TRUE when the email was delivered successfully." },
  { value: "EMAIL_FAILED",    label: "Email failed",                   description: "TRUE when the email could not be delivered." },
  { value: "EMAIL_REPLIED",   label: "Email replied (within window)",  description: "TRUE when the recipient replies within the configured time window." },
  { value: "NEGATIVE_REPLY",  label: "Negative / opt-out reply",       description: "TRUE when the reply contains an opt-out phrase (e.g. 'not interested', 'unsubscribe'). Lead is automatically marked closed." },
  { value: "CALL_COMPLETED",  label: "Call completed",                 description: "TRUE when the call connected and completed." },
  { value: "CALL_FAILED",     label: "Call failed",                    description: "TRUE when the call failed or was exhausted." },
];

interface Props {
  config: ConditionConfig;
  onChange: (next: ConditionConfig) => void;
}

export default function ConditionConfigPanel({ config, onChange }: Props) {
  const selected = CONDITION_OPTIONS.find((o) => o.value === config.condition_type);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">Condition</Label>
        <Select
          value={config.condition_type}
          onValueChange={(v) =>
            onChange({ ...config, condition_type: v as ConditionConfig["condition_type"] })
          }
        >
          <SelectTrigger className="bg-white/5 border-white/10 text-white text-sm">
            <SelectValue placeholder="Select condition…" />
          </SelectTrigger>
          <SelectContent className="bg-[#1a1a2e] border-white/10">
            {CONDITION_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value} className="text-white focus:bg-white/10">
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selected && (
          <p className="text-white/30 text-[11px]">
            {selected.description} The TRUE branch fires when this condition is met; FALSE otherwise.
          </p>
        )}
      </div>

      {/* Window minutes — shown for EMAIL_REPLIED and NEGATIVE_REPLY */}
      {(config.condition_type === "EMAIL_REPLIED" || config.condition_type === "NEGATIVE_REPLY") && (
        <div className="flex flex-col gap-1.5">
          <Label className="text-white/70 text-xs uppercase tracking-widest">
            Reply window (minutes)
          </Label>
          <Input
            type="number"
            min={1}
            max={1440}
            value={config.window_minutes ?? 5}
            onChange={(e) =>
              onChange({
                ...config,
                window_minutes: Math.max(1, parseInt(e.target.value, 10) || 5),
              })
            }
            className="bg-white/5 border-white/10 text-white text-sm w-24"
          />
          <p className="text-white/30 text-[11px]">
            Replies arriving within this many minutes of the email being sent
            will trigger the TRUE branch.
          </p>
        </div>
      )}
    </div>
  );
}
