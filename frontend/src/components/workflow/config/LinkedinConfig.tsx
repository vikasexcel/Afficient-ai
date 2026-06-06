import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { LinkedinConfig } from "@/types/workflow";

const VARIABLES = [
  "{{firstName}}",
  "{{lastName}}",
  "{{company}}",
  "{{jobTitle}}",
  "{{email}}",
  "{{phone}}",
];

interface Props {
  config: LinkedinConfig;
  onChange: (next: LinkedinConfig) => void;
}

export default function LinkedinConfigPanel({ config, onChange }: Props) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">Action</Label>
        <Select
          value={config.action}
          onValueChange={(v) =>
            onChange({ ...config, action: v as LinkedinConfig["action"] })
          }
        >
          <SelectTrigger className="bg-white/5 border-white/10 text-white text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-[#1a1a2e] border-white/10">
            <SelectItem value="CONNECT" className="text-white focus:bg-white/10">Connect request</SelectItem>
            <SelectItem value="MESSAGE" className="text-white focus:bg-white/10">Send message</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {config.action === "MESSAGE" && (
        <>
          <div className="flex flex-col gap-1.5">
            <Label className="text-white/70 text-xs uppercase tracking-widest">Message</Label>
            <Textarea
              value={config.message}
              onChange={(e) => onChange({ ...config, message: e.target.value })}
              placeholder={"Hi {{firstName}}, I'd love to connect…"}
              rows={6}
              className="bg-white/5 border-white/10 text-white placeholder:text-white/25 text-sm resize-none"
            />
          </div>

          <div className="flex flex-col gap-2">
            <p className="text-white/40 text-[11px] uppercase tracking-widest">Available variables</p>
            <div className="flex flex-wrap gap-1.5">
              {VARIABLES.map((v) => (
                <span
                  key={v}
                  className="px-2 py-0.5 rounded bg-sky-900/40 border border-sky-700/40 text-sky-300 text-[11px] font-mono cursor-pointer select-all"
                  title="Click to select"
                >
                  {v}
                </span>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
