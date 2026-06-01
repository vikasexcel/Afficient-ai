import { useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";

import { Input } from "@/components/ui/input";

type Props = {
  values: string[];
  disabled?: boolean;
  placeholder?: string;
  onChange: (next: string[]) => void;
};

export default function KeywordChips({
  values,
  disabled,
  placeholder,
  onChange,
}: Props) {
  const [draft, setDraft] = useState("");

  function commit() {
    const t = draft.trim();
    if (!t) return;
    if (values.some((v) => v.toLowerCase() === t.toLowerCase())) {
      setDraft("");
      return;
    }
    onChange([...values, t]);
    setDraft("");
  }

  function remove(index: number) {
    onChange(values.filter((_, i) => i !== index));
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && !draft && values.length) {
      e.preventDefault();
      onChange(values.slice(0, -1));
    }
  }

  return (
    <div className="flex flex-wrap gap-1.5 items-center rounded-[8px] border border-white/[0.09] bg-white/[0.04] px-2 py-1.5 min-h-[36px]">
      {values.map((v, i) => (
        <span
          key={`${v}-${i}`}
          className="inline-flex items-center gap-1 rounded-full bg-violet-500/15 border border-violet-400/25 text-[11px] text-violet-100 px-2 py-0.5"
        >
          {v}
          {!disabled && (
            <button
              type="button"
              onClick={() => remove(i)}
              className="text-violet-200/70 hover:text-white"
              aria-label={`Remove ${v}`}
            >
              <X size={11} />
            </button>
          )}
        </span>
      ))}
      <Input
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
        placeholder={values.length === 0 ? placeholder : ""}
        className="flex-1 min-w-[120px] h-7 border-0 bg-transparent shadow-none focus-visible:ring-0 px-1 text-[12px]"
      />
    </div>
  );
}
