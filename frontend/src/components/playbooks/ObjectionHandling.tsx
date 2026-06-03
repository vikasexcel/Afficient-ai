import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Plus, ShieldAlert, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  OBJECTION_TYPE_OPTIONS,
  objectionTypeLabel,
  type ObjectionType,
} from "@/lib/playbookObjections";
import type { PlaybookObjection } from "@/services/playbook";

const selectClass =
  "w-full h-9 bg-white/[0.04] border border-white/[0.09] rounded-[8px] px-3 text-[13px] text-white disabled:opacity-50";

function newObjection(): PlaybookObjection {
  const preset = OBJECTION_TYPE_OPTIONS[0];
  return {
    objection_type: preset.value,
    objection_trigger: preset.defaultTrigger,
    objection_response: "",
    fallback_response: null,
  };
}

type Props = {
  objections: PlaybookObjection[];
  canEdit: boolean;
  onChange: (next: PlaybookObjection[]) => void;
};

export default function ObjectionHandling({
  objections,
  canEdit,
  onChange,
}: Props) {
  const [openIndex, setOpenIndex] = useState<number | null>(
    objections.length ? 0 : null
  );

  function patch(index: number, patch: Partial<PlaybookObjection>) {
    onChange(objections.map((o, i) => (i === index ? { ...o, ...patch } : o)));
  }

  function onTypeChange(index: number, type: ObjectionType) {
    const preset = OBJECTION_TYPE_OPTIONS.find((o) => o.value === type);
    const current = objections[index];
    patch(index, {
      objection_type: type,
      objection_trigger:
        !current.objection_trigger?.trim() && preset?.defaultTrigger
          ? preset.defaultTrigger
          : current.objection_trigger,
    });
  }

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-white/45 leading-snug">
        Define how the AI should respond when prospects raise common objections.
        Responses are woven into the conversation naturally — not read verbatim.
      </p>

      {objections.length === 0 && (
        <div className="text-[12px] text-white/40 border border-dashed border-white/[0.1] rounded-[8px] px-3 py-4 text-center">
          No objection rules yet. Add one to guide the AI on live calls.
        </div>
      )}

      {objections.map((obj, i) => {
        const open = openIndex === i;
        return (
          <div
            key={`obj-${i}-${obj.objection_type}`}
            className="border border-white/[0.08] rounded-[10px] bg-white/[0.02] overflow-hidden"
          >
            <button
              type="button"
              className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-white/[0.03]"
              onClick={() => setOpenIndex(open ? null : i)}
            >
              {open ? (
                <ChevronDown size={14} className="text-white/40 shrink-0" />
              ) : (
                <ChevronRight size={14} className="text-white/40 shrink-0" />
              )}
              <ShieldAlert size={14} className="text-violet-300 shrink-0" />
              <span className="text-[13px] text-white font-medium truncate flex-1">
                {objectionTypeLabel(obj.objection_type)}
              </span>
              {obj.objection_trigger && (
                <span className="text-[10px] text-white/35 truncate max-w-[140px] hidden sm:inline">
                  {obj.objection_trigger}
                </span>
              )}
            </button>

            {open && (
              <div className="px-3 pb-3 space-y-3 border-t border-white/[0.06] pt-3">
                <Field label="Objection type">
                  <select
                    disabled={!canEdit}
                    className={selectClass}
                    value={obj.objection_type}
                    onChange={(e) =>
                      onTypeChange(i, e.target.value as ObjectionType)
                    }
                  >
                    {OBJECTION_TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </Field>

                <Field label="Trigger phrase">
                  <Input
                    disabled={!canEdit}
                    className="bg-white/[0.04] border-white/[0.09] text-[13px]"
                    value={obj.objection_trigger}
                    onChange={(e) =>
                      patch(i, { objection_trigger: e.target.value })
                    }
                    placeholder='e.g. "Not interested"'
                  />
                  <p className="text-[10px] text-white/40 mt-1">
                    What the prospect might say. Similar phrases are matched
                    automatically.
                  </p>
                </Field>

                <Field label="Response" required>
                  <Textarea
                    disabled={!canEdit}
                    rows={3}
                    className="bg-white/[0.04] border-white/[0.09] text-[13px] min-h-[72px]"
                    value={obj.objection_response}
                    onChange={(e) =>
                      patch(i, { objection_response: e.target.value })
                    }
                    placeholder="Fair enough, but all I want to do is show you how we can increase qualified meetings without increasing your costs."
                  />
                </Field>

                <Field label="Fallback response">
                  <Textarea
                    disabled={!canEdit}
                    rows={2}
                    className="bg-white/[0.04] border-white/[0.09] text-[13px] min-h-[56px]"
                    value={obj.fallback_response ?? ""}
                    onChange={(e) =>
                      patch(i, {
                        fallback_response: e.target.value || null,
                      })
                    }
                    placeholder="Would it be unreasonable to spend 10 minutes seeing how it works?"
                  />
                  <p className="text-[10px] text-white/40 mt-1">
                    Softer follow-up if they still resist.
                  </p>
                </Field>

                {canEdit && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="text-rose-200/80"
                    onClick={() => {
                      onChange(objections.filter((_, j) => j !== i));
                      setOpenIndex(null);
                    }}
                  >
                    <Trash2 size={13} className="mr-1.5" />
                    Remove
                  </Button>
                )}
              </div>
            )}
          </div>
        );
      })}

      {canEdit && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            const next = [...objections, newObjection()];
            onChange(next);
            setOpenIndex(next.length - 1);
          }}
        >
          <Plus size={14} className="mr-1.5" />
          Add objection
        </Button>
      )}
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="text-[12px] text-white/70 block mb-1.5">
        {label}
        {required && <span className="text-red-400/90 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}
