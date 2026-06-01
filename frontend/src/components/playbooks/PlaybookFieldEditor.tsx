import { useState } from "react";
import { Plus, Trash2, ChevronDown, ChevronRight, Target } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import KeywordChips from "@/components/playbooks/KeywordChips";
import {
  defaultFieldsForFramework,
  fieldsMatchFramework,
  joinPatterns,
  splitPatterns,
} from "@/lib/playbookFieldPresets";
import { deriveFieldKey, FRAMEWORK_META } from "@/lib/playbookCopy";
import type { PlaybookField, PlaybookFramework } from "@/services/playbook";

type Props = {
  framework: PlaybookFramework;
  fields: PlaybookField[];
  canEdit: boolean;
  onChange: (fields: PlaybookField[]) => void;
};

export default function PlaybookFieldEditor({
  framework,
  fields,
  canEdit,
  onChange,
}: Props) {
  const mismatched =
    framework !== "CUSTOM" && !fieldsMatchFramework(fields, framework);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  function toggle(index: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function updateField(index: number, patch: Partial<PlaybookField>) {
    onChange(fields.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  }

  function ensureUniqueKey(base: string, exceptIndex: number): string {
    const existing = new Set(
      fields.map((f, i) => (i === exceptIndex ? "" : f.key))
    );
    if (!existing.has(base)) return base;
    let n = 2;
    while (existing.has(`${base}_${n}`)) n += 1;
    return `${base}_${n}`;
  }

  function updateDisplayName(index: number, displayName: string) {
    const current = fields[index];
    const wasAutoKey = current.key === deriveFieldKey(current.display_name);
    const patch: Partial<PlaybookField> = { display_name: displayName };
    if (wasAutoKey) {
      const base = deriveFieldKey(displayName);
      patch.key = ensureUniqueKey(base, index);
    }
    updateField(index, patch);
  }

  function removeField(index: number) {
    onChange(
      fields
        .filter((_, i) => i !== index)
        .map((f, i) => ({ ...f, position: i }))
    );
  }

  function addField() {
    const display = "New field";
    const baseKey = ensureUniqueKey(deriveFieldKey(display), -1);
    onChange([
      ...fields,
      {
        key: baseKey,
        display_name: display,
        weight: 1,
        required: false,
        cue_patterns: [],
        position: fields.length,
      },
    ]);
    setExpanded((prev) => new Set(prev).add(fields.length));
  }

  function loadFrameworkDefaults() {
    if (
      !window.confirm(
        `Replace all fields with ${framework} defaults? Unsaved field edits will be lost.`
      )
    ) {
      return;
    }
    onChange(defaultFieldsForFramework(framework));
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[12px] font-medium text-white/70 flex items-center gap-1.5">
            <Target size={13} className="text-violet-300" />
            Things to discover ({fields.length})
          </div>
          <p className="text-[11px] text-white/40 mt-0.5">
            What the agent should learn during the call.{" "}
            {framework !== "CUSTOM" && FRAMEWORK_META[framework].tagline}
          </p>
        </div>
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            {framework !== "CUSTOM" && mismatched && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={loadFrameworkDefaults}
              >
                Load {framework} defaults
              </Button>
            )}
            <Button type="button" size="sm" variant="outline" onClick={addField}>
              <Plus size={14} className="mr-1" />
              Add field
            </Button>
          </div>
        )}
      </div>

      {mismatched && (
        <p className="text-[11px] text-amber-200/90 bg-amber-500/10 border border-amber-500/20 rounded-[8px] px-3 py-2">
          These fields don&apos;t match {framework} defaults. Load defaults or
          edit manually, then save.
        </p>
      )}

      {framework === "CUSTOM" && fields.length === 0 && (
        <p className="text-[12px] text-white/45 bg-white/[0.02] border border-dashed border-white/10 rounded-[8px] px-3 py-4 text-center">
          Custom playbooks start with no fields. Add fields below or pick BANT /
          MEDDICC for a preset.
        </p>
      )}

      <div className="space-y-2">
        {fields.map((f, index) => {
          const isOpen = expanded.has(index);
          const keywordCount = splitPatterns(f.cue_patterns ?? []).keywords.length;
          const advancedCount = splitPatterns(f.cue_patterns ?? []).advanced.length;
          return (
            <div
              key={`${f.key}-${index}`}
              className="rounded-[10px] border border-white/[0.07] bg-white/[0.02]"
            >
              <button
                type="button"
                onClick={() => toggle(index)}
                className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-white/[0.02] rounded-t-[10px]"
              >
                {isOpen ? (
                  <ChevronDown size={14} className="text-white/40 shrink-0" />
                ) : (
                  <ChevronRight size={14} className="text-white/40 shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[13px] text-white">
                      {f.display_name}
                    </span>
                    {f.required && (
                      <span className="text-[10px] uppercase tracking-wider rounded-full border border-amber-400/25 bg-amber-500/10 text-amber-200 px-1.5 py-0.5">
                        Required
                      </span>
                    )}
                    <span className="text-[10px] text-white/35">
                      weight {f.weight}
                    </span>
                  </div>
                  <div className="text-[11px] text-white/40 mt-0.5">
                    {keywordCount} keyword{keywordCount === 1 ? "" : "s"}
                    {advancedCount > 0 && ` · ${advancedCount} advanced`}
                  </div>
                </div>
                {canEdit && (
                  <span
                    role="button"
                    tabIndex={0}
                    aria-label={`Remove ${f.display_name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      removeField(index);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.stopPropagation();
                        removeField(index);
                      }
                    }}
                    className="text-red-400/70 hover:text-red-300 p-1 rounded cursor-pointer"
                  >
                    <Trash2 size={13} />
                  </span>
                )}
              </button>

              {isOpen && (
                <div className="px-3 pb-3 pt-1 space-y-3 border-t border-white/[0.05]">
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className="sm:col-span-2">
                      <label className="block text-[10px] uppercase tracking-wide text-white/40 mb-1">
                        Display name
                      </label>
                      <Input
                        value={f.display_name}
                        disabled={!canEdit}
                        onChange={(e) =>
                          updateDisplayName(index, e.target.value)
                        }
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] uppercase tracking-wide text-white/40 mb-1">
                        Importance
                      </label>
                      <select
                        value={f.weight}
                        disabled={!canEdit}
                        onChange={(e) =>
                          updateField(index, {
                            weight: parseInt(e.target.value, 10) || 1,
                          })
                        }
                        className="w-full h-9 bg-white/[0.04] border border-white/[0.09] rounded-[8px] px-3 text-[13px] text-white"
                      >
                        <option value={1}>Low (×1)</option>
                        <option value={2}>Medium (×2)</option>
                        <option value={3}>High (×3)</option>
                      </select>
                    </div>
                  </div>

                  <label className="flex items-center gap-2 text-[12px] text-white/70 cursor-pointer select-none w-fit">
                    <input
                      type="checkbox"
                      checked={f.required}
                      disabled={!canEdit}
                      onChange={(e) =>
                        updateField(index, { required: e.target.checked })
                      }
                    />
                    Required for &quot;qualified&quot; status
                  </label>

                  <CuePatternEditor
                    field={f}
                    canEdit={canEdit}
                    onChange={(cue_patterns) =>
                      updateField(index, { cue_patterns })
                    }
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CuePatternEditor({
  field,
  canEdit,
  onChange,
}: {
  field: PlaybookField;
  canEdit: boolean;
  onChange: (next: string[]) => void;
}) {
  const patterns = field.cue_patterns ?? [];
  const split = splitPatterns(patterns);
  const [showAdvanced, setShowAdvanced] = useState(split.advanced.length > 0);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-[10px] uppercase tracking-wide text-white/40">
          Trigger keywords
        </label>
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-[10px] text-white/40 hover:text-white/70 underline-offset-2 hover:underline"
        >
          {showAdvanced ? "Hide regex" : "Advanced (regex)"}
        </button>
      </div>
      <p className="text-[11px] text-white/35 -mt-1">
        When the lead says any of these, this field is marked answered.
      </p>

      <KeywordChips
        values={split.keywords}
        disabled={!canEdit}
        placeholder='Type a keyword and press Enter (e.g. "budget", "VP of Sales")'
        onChange={(keywords) =>
          onChange(joinPatterns({ keywords, advanced: split.advanced }))
        }
      />

      {showAdvanced && (
        <div>
          <label className="block text-[10px] text-white/45 mb-1">
            Advanced regex patterns (one per line)
          </label>
          <Textarea
            rows={2}
            disabled={!canEdit}
            className="font-mono text-[11px]"
            value={split.advanced.join("\n")}
            onChange={(e) => {
              const advanced = e.target.value
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean);
              onChange(joinPatterns({ keywords: split.keywords, advanced }));
            }}
            placeholder={String.raw`\b(q[1-4]|h[12])\b`}
          />
          <p className="text-[10px] text-white/35 mt-1">
            Patterns are matched against lowercased transcript text.
          </p>
        </div>
      )}
    </div>
  );
}
