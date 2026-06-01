import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

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

  function updateField(index: number, patch: Partial<PlaybookField>) {
    onChange(
      fields.map((f, i) => (i === index ? { ...f, ...patch } : f))
    );
  }

  function removeField(index: number) {
    onChange(
      fields
        .filter((_, i) => i !== index)
        .map((f, i) => ({ ...f, position: i }))
    );
  }

  function addField() {
    const n = fields.length;
    onChange([
      ...fields,
      {
        key: `field_${n + 1}`,
        display_name: "New field",
        weight: 1,
        required: false,
        cue_patterns: [],
        position: n,
      },
    ]);
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
        <div className="text-[11px] font-medium text-white/40">
          Qualification fields ({fields.length})
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
        <p className="text-[11px] text-amber-300/80 bg-amber-500/10 border border-amber-500/20 rounded-[8px] px-3 py-2">
          Fields don&apos;t match {framework} defaults. Load defaults or edit
          manually, then save.
        </p>
      )}

      {framework === "CUSTOM" && fields.length === 0 && (
        <p className="text-[12px] text-white/45 bg-white/[0.02] border border-white/[0.07] rounded-[8px] px-3 py-4 text-center">
          CUSTOM playbooks start with no fields. Add fields below or pick BANT /
          MEDDICC to use a preset.
        </p>
      )}

      <div className="space-y-3">
        {fields.map((f, index) => (
          <div
            key={`${f.key}-${index}`}
            className="rounded-[8px] border border-white/[0.07] bg-white/[0.02] p-3 space-y-2"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 flex-1">
                <div>
                  <label className="block text-[10px] text-white/35 mb-1">
                    Display name
                  </label>
                  <Input
                    value={f.display_name}
                    disabled={!canEdit}
                    onChange={(e) =>
                      updateField(index, { display_name: e.target.value })
                    }
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-white/35 mb-1">
                    Key
                  </label>
                  <Input
                    value={f.key}
                    disabled={!canEdit}
                    className="font-mono text-[12px]"
                    onChange={(e) =>
                      updateField(index, {
                        key: e.target.value
                          .trim()
                          .toLowerCase()
                          .replace(/\s+/g, "_"),
                      })
                    }
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-white/35 mb-1">
                    Weight (1–10)
                  </label>
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={f.weight}
                    disabled={!canEdit}
                    onChange={(e) =>
                      updateField(index, {
                        weight: Math.min(
                          10,
                          Math.max(1, parseInt(e.target.value, 10) || 1)
                        ),
                      })
                    }
                  />
                </div>
                <div className="flex items-end pb-1">
                  <label className="flex items-center gap-2 text-[12px] text-white/70 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={f.required}
                      disabled={!canEdit}
                      className="rounded"
                      onChange={(e) =>
                        updateField(index, { required: e.target.checked })
                      }
                    />
                    Required
                  </label>
                </div>
              </div>
              {canEdit && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="text-red-400/80 hover:text-red-300 shrink-0"
                  onClick={() => removeField(index)}
                  aria-label={`Remove ${f.display_name}`}
                >
                  <Trash2 size={14} />
                </Button>
              )}
            </div>
            <CuePatternEditor
              field={f}
              canEdit={canEdit}
              onChange={(cue_patterns) => updateField(index, { cue_patterns })}
            />
          </div>
        ))}
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
        <label className="text-[10px] text-white/35">
          Trigger keywords{" "}
          <span className="text-white/30">
            (when the lead says any of these, this field is marked answered)
          </span>
        </label>
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-[10px] text-white/40 hover:text-white/70 underline-offset-2 hover:underline"
        >
          {showAdvanced ? "Hide regex" : "Advanced (regex)"}
        </button>
      </div>

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
          <label className="block text-[10px] text-white/35 mb-1">
            Advanced regex patterns (one per line) — bypasses keyword UI
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
