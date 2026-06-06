import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { CallConfig } from "@/types/workflow";

// Mock playbook list — replace when Playbook API is integrated.
const MOCK_PLAYBOOKS = [
  { id: "pb_intro", name: "Intro Call" },
  { id: "pb_demo", name: "Demo Call" },
  { id: "pb_followup", name: "Follow-Up" },
  { id: "pb_closing", name: "Closing Call" },
];

interface Props {
  config: CallConfig;
  onChange: (next: CallConfig) => void;
}

export default function CallConfigPanel({ config, onChange }: Props) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">Playbook</Label>
        <Select
          value={config.playbook_id || ""}
          onValueChange={(v) => onChange({ ...config, playbook_id: v })}
        >
          <SelectTrigger className="bg-white/5 border-white/10 text-white text-sm">
            <SelectValue placeholder="Select a playbook…" />
          </SelectTrigger>
          <SelectContent className="bg-[#1a1a2e] border-white/10">
            {MOCK_PLAYBOOKS.map((pb) => (
              <SelectItem key={pb.id} value={pb.id} className="text-white focus:bg-white/10">
                {pb.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-white/30 text-[11px]">Playbook API integration pending.</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">Retry count</Label>
        <Input
          type="number"
          min={0}
          max={10}
          value={config.retry_count}
          onChange={(e) =>
            onChange({ ...config, retry_count: Math.max(0, parseInt(e.target.value, 10) || 0) })
          }
          className="bg-white/5 border-white/10 text-white text-sm w-24"
        />
        <p className="text-white/30 text-[11px]">Number of retry attempts if the call fails.</p>
      </div>
    </div>
  );
}
