import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ConditionConfig } from "@/types/workflow";

const CONDITION_OPTIONS: { value: ConditionConfig["condition_type"]; label: string }[] = [
  { value: "EMAIL_SENT", label: "Email sent" },
  { value: "EMAIL_FAILED", label: "Email failed" },
  { value: "CALL_COMPLETED", label: "Call completed" },
  { value: "CALL_FAILED", label: "Call failed" },
];

interface Props {
  config: ConditionConfig;
  onChange: (next: ConditionConfig) => void;
}

export default function ConditionConfigPanel({ config, onChange }: Props) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">Condition</Label>
        <Select
          value={config.condition_type}
          onValueChange={(v) =>
            onChange({ condition_type: v as ConditionConfig["condition_type"] })
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
        <p className="text-white/30 text-[11px]">
          The TRUE branch fires when this condition is met; FALSE otherwise.
        </p>
      </div>
    </div>
  );
}
