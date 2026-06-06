import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { WaitConfig } from "@/types/workflow";

interface Props {
  config: WaitConfig;
  onChange: (next: WaitConfig) => void;
}

export default function WaitConfigPanel({ config, onChange }: Props) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">Wait duration</Label>
        <div className="flex gap-2 items-center">
          <Input
            type="number"
            min={1}
            value={config.duration}
            onChange={(e) =>
              onChange({ ...config, duration: Math.max(1, parseInt(e.target.value, 10) || 1) })
            }
            className="bg-white/5 border-white/10 text-white text-sm w-24"
          />
          <Select
            value={config.unit}
            onValueChange={(v) =>
              onChange({ ...config, unit: v as WaitConfig["unit"] })
            }
          >
            <SelectTrigger className="bg-white/5 border-white/10 text-white text-sm flex-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#1a1a2e] border-white/10">
              <SelectItem value="minutes" className="text-white focus:bg-white/10">minutes</SelectItem>
              <SelectItem value="hours" className="text-white focus:bg-white/10">hours</SelectItem>
              <SelectItem value="days" className="text-white focus:bg-white/10">days</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <p className="text-white/30 text-[11px]">
          Node label updates live: <span className="text-amber-400/70 font-mono">WAIT ({config.duration} {config.unit})</span>
        </p>
      </div>
    </div>
  );
}
