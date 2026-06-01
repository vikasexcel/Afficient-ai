import { useState } from "react";
import { Plus, Trash2, ChevronDown, ChevronRight, GitBranch } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { personaLabel } from "@/lib/playbookCopy";
import type {
  PlaybookBranch,
  PlaybookField,
} from "@/services/playbook";
import type { Persona } from "@/services/ai";

type Props = {
  branches: PlaybookBranch[];
  fields: PlaybookField[];
  personas: Persona[];
  canEdit: boolean;
  onChange: (next: PlaybookBranch[]) => void;
};

const QUAL_STATUSES = ["in_progress", "qualified", "disqualified"] as const;
const QUAL_STATUS_LABELS: Record<(typeof QUAL_STATUSES)[number], string> = {
  in_progress: "In progress",
  qualified: "Qualified",
  disqualified: "Disqualified",
};

function newBranch(index: number): PlaybookBranch {
  return {
    id: `branch_${Date.now().toString(36)}_${index}`,
    name: `Rule ${index + 1}`,
    priority: 100,
    once: true,
    when: {},
    then: {},
  };
}

function asString(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function asNumber(v: unknown): number | "" {
  return typeof v === "number" ? v : "";
}

function asBool(v: unknown): boolean {
  return typeof v === "boolean" ? v : false;
}

function asStringList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

function asStatuses(v: unknown): (typeof QUAL_STATUSES)[number][] {
  if (typeof v === "string") {
    return QUAL_STATUSES.includes(v as (typeof QUAL_STATUSES)[number])
      ? [v as (typeof QUAL_STATUSES)[number]]
      : [];
  }
  if (Array.isArray(v)) {
    return v.filter((s): s is (typeof QUAL_STATUSES)[number] =>
      QUAL_STATUSES.includes(s as (typeof QUAL_STATUSES)[number])
    );
  }
  return [];
}

export default function PlaybookBranchEditor({
  branches,
  fields,
  personas,
  canEdit,
  onChange,
}: Props) {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  function patchBranch(index: number, patch: Partial<PlaybookBranch>) {
    onChange(branches.map((b, i) => (i === index ? { ...b, ...patch } : b)));
  }

  function patchWhen(index: number, patch: Record<string, unknown>) {
    const current = branches[index];
    const nextWhen = { ...(current.when ?? {}), ...patch };
    Object.keys(patch).forEach((k) => {
      const v = patch[k];
      if (
        v === undefined ||
        v === "" ||
        (Array.isArray(v) && v.length === 0)
      ) {
        delete nextWhen[k];
      }
    });
    patchBranch(index, { when: nextWhen });
  }

  function patchThen(index: number, patch: Record<string, unknown>) {
    const current = branches[index];
    const nextThen = { ...(current.then ?? {}), ...patch };
    Object.keys(patch).forEach((k) => {
      const v = patch[k];
      if (v === undefined || v === "" || v === false) {
        delete nextThen[k];
      }
    });
    patchBranch(index, { then: nextThen });
  }

  function addBranch() {
    const idx = branches.length;
    onChange([...branches, newBranch(idx)]);
    setOpenIndex(idx);
  }

  function removeBranch(index: number) {
    onChange(branches.filter((_, i) => i !== index));
    if (openIndex === index) setOpenIndex(null);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[12px] font-medium text-white/70 flex items-center gap-1.5">
            <GitBranch size={13} className="text-violet-300" />
            Branch rules ({branches.length})
          </div>
          <p className="text-[11px] text-white/40 mt-0.5">
            Change the agent&apos;s behavior mid-call when conditions are met.
          </p>
        </div>
        {canEdit && (
          <Button type="button" size="sm" variant="outline" onClick={addBranch}>
            <Plus size={14} className="mr-1" />
            Add rule
          </Button>
        )}
      </div>

      {branches.length === 0 && (
        <div className="text-[12px] text-white/45 bg-white/[0.02] border border-dashed border-white/10 rounded-[8px] px-3 py-4 text-center">
          No branch rules. The agent will follow the persona for the whole call.
        </div>
      )}

      <div className="space-y-2">
        {branches.map((branch, index) => {
          const open = openIndex === index;
          const when = branch.when ?? {};
          const then = branch.then ?? {};
          const summary = describeBranch(branch);
          return (
            <div
              key={branch.id || index}
              className="rounded-[10px] border border-white/[0.08] bg-white/[0.02]"
            >
              <button
                type="button"
                onClick={() => setOpenIndex(open ? null : index)}
                className="w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-white/[0.02] rounded-t-[10px]"
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  {open ? (
                    <ChevronDown size={14} className="text-white/40 shrink-0" />
                  ) : (
                    <ChevronRight size={14} className="text-white/40 shrink-0" />
                  )}
                  <div className="min-w-0">
                    <div className="text-[13px] text-white truncate">
                      {branch.name || "Untitled rule"}
                    </div>
                    <div className="text-[11px] text-white/40 truncate">
                      {summary}
                    </div>
                  </div>
                </div>
                {canEdit && (
                  <span
                    role="button"
                    tabIndex={0}
                    aria-label={`Remove ${branch.name}`}
                    className="text-red-400/70 hover:text-red-300 p-1 rounded cursor-pointer"
                    onClick={(e) => {
                      e.stopPropagation();
                      removeBranch(index);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.stopPropagation();
                        removeBranch(index);
                      }
                    }}
                  >
                    <Trash2 size={13} />
                  </span>
                )}
              </button>

              {open && (
                <div className="px-3 pb-3 pt-1 space-y-4 border-t border-white/[0.05]">
                  <div>
                    <label className="block text-[10px] uppercase tracking-wide text-white/35 mb-1">
                      Rule name
                    </label>
                    <Input
                      value={branch.name}
                      disabled={!canEdit}
                      onChange={(e) =>
                        patchBranch(index, { name: e.target.value })
                      }
                      placeholder="e.g. Hand off when qualified"
                    />
                  </div>

                  {/* WHEN */}
                  <Section
                    badge="When"
                    badgeClass="bg-amber-500/10 text-amber-200 border-amber-400/25"
                    title="all of the following are true"
                  >
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[10px] text-white/45 mb-1">
                          Qualification status
                        </label>
                        <div className="flex flex-wrap gap-1.5">
                          {QUAL_STATUSES.map((s) => {
                            const selected = asStatuses(
                              when.qualification_status
                            ).includes(s);
                            return (
                              <button
                                key={s}
                                type="button"
                                disabled={!canEdit}
                                onClick={() => {
                                  const cur = asStatuses(
                                    when.qualification_status
                                  );
                                  const nextArr = cur.includes(s)
                                    ? cur.filter((x) => x !== s)
                                    : [...cur, s];
                                  patchWhen(index, {
                                    qualification_status:
                                      nextArr.length === 0
                                        ? undefined
                                        : nextArr.length === 1
                                        ? nextArr[0]
                                        : nextArr,
                                  });
                                }}
                                className={`text-[11px] rounded-full border px-2.5 py-1 transition-colors ${
                                  selected
                                    ? "bg-violet-500/15 text-violet-100 border-violet-400/30"
                                    : "bg-white/[0.03] text-white/60 border-white/10 hover:border-white/20"
                                }`}
                              >
                                {QUAL_STATUS_LABELS[s]}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      <ScoreRange
                        canEdit={canEdit}
                        min={asNumber(when.min_score)}
                        max={asNumber(when.max_score)}
                        onMinChange={(v) =>
                          patchWhen(index, { min_score: v })
                        }
                        onMaxChange={(v) =>
                          patchWhen(index, { max_score: v })
                        }
                      />
                    </div>

                    <FieldMultiSelect
                      label="Required: ALL of these fields must be answered"
                      fields={fields}
                      value={asStringList(when.fields_all_answered)}
                      disabled={!canEdit}
                      onChange={(v) =>
                        patchWhen(index, { fields_all_answered: v })
                      }
                    />
                    <FieldMultiSelect
                      label="At least one of these fields was answered"
                      fields={fields}
                      value={asStringList(when.fields_any_answered)}
                      disabled={!canEdit}
                      onChange={(v) =>
                        patchWhen(index, { fields_any_answered: v })
                      }
                    />
                    <FieldMultiSelect
                      label="One of these fields was just answered this turn"
                      fields={fields}
                      value={asStringList(when.field_set_this_turn)}
                      disabled={!canEdit}
                      onChange={(v) =>
                        patchWhen(index, { field_set_this_turn: v })
                      }
                    />
                  </Section>

                  {/* THEN */}
                  <Section
                    badge="Then"
                    badgeClass="bg-emerald-500/10 text-emerald-200 border-emerald-400/25"
                    title="apply these actions"
                  >
                    <div>
                      <label className="block text-[10px] text-white/45 mb-1">
                        Switch persona
                      </label>
                      <select
                        value={asString(then.switch_persona)}
                        disabled={!canEdit}
                        onChange={(e) =>
                          patchThen(index, {
                            switch_persona: e.target.value || undefined,
                          })
                        }
                        className="w-full h-9 bg-white/[0.04] border border-white/[0.09] rounded-[8px] px-3 text-[13px] text-white"
                      >
                        <option value="">— don&apos;t change —</option>
                        {personas.map((p) => (
                          <option key={p.name} value={p.name}>
                            {personaLabel(p.name)}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-[10px] text-white/45 mb-1">
                        New objective (optional)
                      </label>
                      <Input
                        value={asString(then.objective)}
                        disabled={!canEdit}
                        onChange={(e) =>
                          patchThen(index, {
                            objective: e.target.value || undefined,
                          })
                        }
                        placeholder="e.g. confirm a meeting in the next 7 days"
                      />
                    </div>

                    <div>
                      <label className="block text-[10px] text-white/45 mb-1">
                        Inject extra instructions (optional)
                      </label>
                      <Textarea
                        rows={2}
                        value={asString(then.dynamic_block)}
                        disabled={!canEdit}
                        onChange={(e) =>
                          patchThen(index, {
                            dynamic_block: e.target.value || undefined,
                          })
                        }
                        placeholder="e.g. Stop discovery — offer two specific meeting slots and confirm timezone."
                      />
                    </div>

                    <label className="flex items-center gap-2 text-[12px] text-white/70 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        disabled={!canEdit}
                        checked={asBool(then.end_call)}
                        onChange={(e) =>
                          patchThen(index, {
                            end_call: e.target.checked || undefined,
                          })
                        }
                      />
                      End the call
                    </label>
                  </Section>

                  <details className="text-[11px] text-white/40">
                    <summary className="cursor-pointer hover:text-white/60">
                      Advanced
                    </summary>
                    <div className="grid grid-cols-2 gap-3 mt-2">
                      <div>
                        <label className="block text-[10px] text-white/45 mb-1">
                          Priority (lower = earlier)
                        </label>
                        <Input
                          type="number"
                          value={branch.priority ?? 100}
                          disabled={!canEdit}
                          onChange={(e) =>
                            patchBranch(index, {
                              priority: parseInt(e.target.value, 10) || 100,
                            })
                          }
                        />
                      </div>
                      <label className="flex items-center gap-2 text-[12px] text-white/70 cursor-pointer pt-5">
                        <input
                          type="checkbox"
                          disabled={!canEdit}
                          checked={branch.once !== false}
                          onChange={(e) =>
                            patchBranch(index, { once: e.target.checked })
                          }
                        />
                        Fire only once per call
                      </label>
                    </div>
                  </details>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Section({
  badge,
  badgeClass,
  title,
  children,
}: {
  badge: string;
  badgeClass: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-[8px] bg-white/[0.02] border border-white/[0.05] p-3 space-y-3">
      <div className="flex items-center gap-2">
        <span
          className={`text-[10px] font-semibold uppercase tracking-wider rounded-full border px-2 py-0.5 ${badgeClass}`}
        >
          {badge}
        </span>
        <span className="text-[11px] text-white/45">{title}</span>
      </div>
      {children}
    </div>
  );
}

function ScoreRange({
  canEdit,
  min,
  max,
  onMinChange,
  onMaxChange,
}: {
  canEdit: boolean;
  min: number | "";
  max: number | "";
  onMinChange: (v: number | undefined) => void;
  onMaxChange: (v: number | undefined) => void;
}) {
  return (
    <div>
      <label className="block text-[10px] text-white/45 mb-1">
        Score range (0–100)
      </label>
      <div className="flex items-center gap-2">
        <Input
          type="number"
          min={0}
          max={100}
          placeholder="any"
          value={min}
          disabled={!canEdit}
          onChange={(e) => {
            const raw = e.target.value;
            onMinChange(raw === "" ? undefined : Math.min(100, Math.max(0, parseInt(raw, 10) || 0)));
          }}
        />
        <span className="text-[11px] text-white/40">to</span>
        <Input
          type="number"
          min={0}
          max={100}
          placeholder="any"
          value={max}
          disabled={!canEdit}
          onChange={(e) => {
            const raw = e.target.value;
            onMaxChange(raw === "" ? undefined : Math.min(100, Math.max(0, parseInt(raw, 10) || 0)));
          }}
        />
      </div>
    </div>
  );
}

function FieldMultiSelect({
  label,
  fields,
  value,
  disabled,
  onChange,
}: {
  label: string;
  fields: PlaybookField[];
  value: string[];
  disabled?: boolean;
  onChange: (next: string[]) => void;
}) {
  if (fields.length === 0) return null;
  return (
    <div>
      <label className="block text-[10px] text-white/45 mb-1">{label}</label>
      <div className="flex flex-wrap gap-1.5">
        {fields.map((f) => {
          const selected = value.includes(f.key);
          return (
            <button
              key={f.key}
              type="button"
              disabled={disabled}
              onClick={() =>
                onChange(
                  selected ? value.filter((k) => k !== f.key) : [...value, f.key]
                )
              }
              className={`text-[11px] rounded-full border px-2.5 py-1 transition-colors ${
                selected
                  ? "bg-violet-500/15 text-violet-100 border-violet-400/30"
                  : "bg-white/[0.03] text-white/55 border-white/10 hover:border-white/20"
              }`}
              title={f.key}
            >
              {f.display_name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function describeBranch(b: PlaybookBranch): string {
  const parts: string[] = [];
  const w = b.when ?? {};
  const t = b.then ?? {};
  const status = w.qualification_status;
  if (status) {
    const arr = Array.isArray(status) ? status : [String(status)];
    parts.push(`status: ${arr.join("/")}`);
  }
  if (typeof w.min_score === "number") parts.push(`score ≥ ${w.min_score}`);
  if (typeof w.max_score === "number") parts.push(`score ≤ ${w.max_score}`);
  const all = asStringList(w.fields_all_answered);
  if (all.length) parts.push(`all: ${all.join(", ")}`);
  const any = asStringList(w.fields_any_answered);
  if (any.length) parts.push(`any: ${any.join(", ")}`);

  const actions: string[] = [];
  if (typeof t.switch_persona === "string" && t.switch_persona)
    actions.push(`→ ${personaLabel(t.switch_persona)}`);
  if (typeof t.objective === "string" && t.objective) actions.push(`set objective`);
  if (typeof t.dynamic_block === "string" && t.dynamic_block)
    actions.push(`inject prompt`);
  if (t.end_call) actions.push("end call");

  if (parts.length === 0 && actions.length === 0) return "Always fires (no conditions)";
  if (parts.length === 0) return `Always · ${actions.join(", ")}`;
  if (actions.length === 0) return `When ${parts.join(", ")} (no actions yet)`;
  return `When ${parts.join(", ")} · ${actions.join(", ")}`;
}
