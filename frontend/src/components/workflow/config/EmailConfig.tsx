import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { EmailConfig } from "@/types/workflow";

const VARIABLES = [
  "{{firstName}}",
  "{{lastName}}",
  "{{company}}",
  "{{jobTitle}}",
  "{{email}}",
  "{{phone}}",
];

interface Props {
  config: EmailConfig;
  onChange: (next: EmailConfig) => void;
}

export default function EmailConfigPanel({ config, onChange }: Props) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">Subject</Label>
        <Input
          value={config.subject}
          onChange={(e) => onChange({ ...config, subject: e.target.value })}
          placeholder="e.g. Hi {{firstName}}, quick question…"
          className="bg-white/5 border-white/10 text-white placeholder:text-white/25 text-sm"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label className="text-white/70 text-xs uppercase tracking-widest">Body</Label>
        <Textarea
          value={config.body}
          onChange={(e) => onChange({ ...config, body: e.target.value })}
          placeholder={"Hi {{firstName}},\n\nI wanted to reach out…"}
          rows={8}
          className="bg-white/5 border-white/10 text-white placeholder:text-white/25 text-sm resize-none"
        />
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-white/40 text-[11px] uppercase tracking-widest">Available variables</p>
        <div className="flex flex-wrap gap-1.5">
          {VARIABLES.map((v) => (
            <span
              key={v}
              className="px-2 py-0.5 rounded bg-violet-900/40 border border-violet-700/40 text-violet-300 text-[11px] font-mono cursor-pointer select-all"
              title="Click to select"
            >
              {v}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
