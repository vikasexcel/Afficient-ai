import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleDashed,
  CircleX,
  Copy,
  Loader2,
  MessageCircleHeart,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useMe, canManageMembers } from "@/store/me";
import {
  archivePlaybook,
  createPlaybook,
  duplicatePlaybook,
  getPlaybook,
  listPlaybooks,
  publishPlaybook,
  testPlaybook,
  updatePlaybook,
  type PlaybookDetail,
  type PlaybookFramework,
  type PlaybookSummary,
} from "@/services/playbook";
import { listPersonas, type Persona } from "@/services/ai";
import PlaybookFieldEditor from "@/components/playbooks/PlaybookFieldEditor";
import PlaybookBranchEditor from "@/components/playbooks/PlaybookBranchEditor";
import {
  defaultFieldsForFramework,
  frameworkSwitchMessage,
  shouldReplaceFieldsOnFrameworkChange,
} from "@/lib/playbookFieldPresets";
import {
  FRAMEWORK_META,
  FRAMEWORK_PILL_CLASS,
  QUAL_STATUS_META,
  STATUS_META,
  personaLabel,
} from "@/lib/playbookCopy";

const FRAMEWORKS: PlaybookFramework[] = ["BANT", "MEDDICC", "CUSTOM"];

function applyFrameworkChange(
  detail: PlaybookDetail,
  newFramework: PlaybookFramework
): PlaybookDetail | null {
  if (newFramework === detail.framework) return detail;
  if (
    shouldReplaceFieldsOnFrameworkChange(
      detail.fields,
      detail.framework,
      newFramework
    )
  ) {
    if (!window.confirm(frameworkSwitchMessage(newFramework))) return null;
    return {
      ...detail,
      framework: newFramework,
      fields: defaultFieldsForFramework(newFramework),
    };
  }
  return { ...detail, framework: newFramework };
}

type TestResultData = {
  score: number;
  status: string;
  newly: string[];
  fired: string[];
};

export default function Playbooks() {
  const me = useMe((s) => s.data);
  const canEdit = canManageMembers(me?.role);

  const [playbooks, setPlaybooks] = useState<PlaybookSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PlaybookDetail | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [testText, setTestText] = useState(
    "We have budget approved for Q3 and I'm the VP of Sales."
  );
  const [testResult, setTestResult] = useState<TestResultData | null>(null);

  async function loadList() {
    setLoading(true);
    try {
      const rows = await listPlaybooks();
      setPlaybooks(rows);
      if (rows.length && !selectedId) setSelectedId(rows[0].id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load playbooks");
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id: string) {
    try {
      const pb = await getPlaybook(id);
      setDetail(pb);
      setTestResult(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load playbook");
    }
  }

  useEffect(() => {
    loadList();
    listPersonas().then(setPersonas).catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedId) loadDetail(selectedId);
  }, [selectedId]);

  async function handleCreate() {
    setSaving(true);
    try {
      const pb = await createPlaybook({
        name: `New playbook ${playbooks.length + 1}`,
        framework: "BANT",
        persona_name: "outbound_sdr",
      });
      toast.success("Playbook created");
      await loadList();
      setSelectedId(pb.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Create failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    if (!detail) return;
    setSaving(true);
    try {
      const updated = await updatePlaybook(detail.id, {
        name: detail.name,
        description: detail.description ?? undefined,
        framework: detail.framework,
        persona_name: detail.persona_name,
        system_prompt: detail.system_prompt ?? undefined,
        opening_line: detail.opening_line ?? undefined,
        default_objective: detail.default_objective ?? undefined,
        fields: detail.fields.map((f) => ({
          key: f.key,
          display_name: f.display_name,
          description: f.description ?? undefined,
          weight: f.weight,
          required: f.required,
          cue_patterns: f.cue_patterns,
          position: f.position,
        })),
        branches: detail.branches ?? [],
      });
      setDetail(updated);
      toast.success("Saved");
      await loadList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handlePublish() {
    if (!detail) return;
    setSaving(true);
    try {
      const updated = await publishPlaybook(detail.id);
      setDetail(updated);
      toast.success(`Published v${updated.version}`);
      await loadList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Publish failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleArchive() {
    if (!detail) return;
    if (!window.confirm(`Archive "${detail.name}"? You can still see it under archived.`))
      return;
    try {
      const archived = await archivePlaybook(detail.id);
      setDetail(archived);
      await loadList();
      toast.success("Archived");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Archive failed");
    }
  }

  async function handleDuplicate() {
    if (!detail) return;
    try {
      const dup = await duplicatePlaybook(detail.id);
      setSelectedId(dup.id);
      toast.success("Duplicated");
      await loadList();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Duplicate failed");
    }
  }

  async function handleTest() {
    if (!detail) return;
    setSaving(true);
    try {
      const res = await testPlaybook(detail.id, { user_text: testText });
      const after = res.qualification_after as {
        score?: number;
        status?: string;
      };
      setTestResult({
        score: after.score ?? 0,
        status: after.status ?? "in_progress",
        newly: res.newly_set_fields ?? [],
        fired: res.branches_fired ?? [],
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Test failed");
    } finally {
      setSaving(false);
    }
  }

  const selectedPersona = useMemo(
    () => personas.find((p) => p.name === detail?.persona_name),
    [personas, detail?.persona_name]
  );

  return (
    <AppLayout>
      <div className="max-w-6xl space-y-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-[22px] font-semibold text-white">Playbooks</h1>
            <p className="text-[13px] text-white/45 mt-0.5">
              Set up how the AI agent talks, qualifies, and adapts on a call.
              No code.
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={loadList}
              disabled={loading}
            >
              <RefreshCw size={14} className="mr-1.5" />
              Refresh
            </Button>
            {canEdit && (
              <Button size="sm" onClick={handleCreate} disabled={saving}>
                <Plus size={14} className="mr-1.5" />
                New playbook
              </Button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-5 items-start">
          {/* SIDEBAR */}
          <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-2 space-y-1">
            {loading && (
              <div className="flex items-center gap-2 text-[12px] text-white/45 p-2">
                <Loader2 size={14} className="animate-spin" /> Loading…
              </div>
            )}
            {!loading && playbooks.length === 0 && (
              <div className="text-[12px] text-white/45 p-3 text-center">
                No playbooks yet.
              </div>
            )}
            {playbooks.map((pb) => (
              <button
                key={pb.id}
                type="button"
                onClick={() => setSelectedId(pb.id)}
                className={`w-full text-left rounded-[8px] px-3 py-2.5 transition-colors ${
                  selectedId === pb.id
                    ? "bg-violet-500/10 border border-violet-500/25"
                    : "hover:bg-white/[0.04] border border-transparent"
                }`}
              >
                <div className="text-[13px] text-white font-medium truncate">
                  {pb.name}
                </div>
                <div className="flex items-center gap-1.5 mt-1">
                  <span
                    className={`text-[10px] rounded-full border px-1.5 py-0.5 ${
                      FRAMEWORK_PILL_CLASS[pb.framework]
                    }`}
                  >
                    {FRAMEWORK_META[pb.framework].label}
                  </span>
                  <span
                    className={`text-[10px] rounded-full border px-1.5 py-0.5 ${
                      STATUS_META[pb.status].pill
                    }`}
                  >
                    {STATUS_META[pb.status].label}
                  </span>
                </div>
              </button>
            ))}
          </div>

          {/* DETAIL */}
          {detail ? (
            <div className="space-y-4">
              {/* Card: Identity */}
              <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-5 space-y-4">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="flex-1 min-w-[260px]">
                    <Input
                      value={detail.name}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setDetail({ ...detail, name: e.target.value })
                      }
                      className="text-[16px] font-semibold bg-transparent border-0 px-0 h-9 focus-visible:ring-0 shadow-none"
                      placeholder="Playbook name"
                    />
                    <Input
                      value={detail.description ?? ""}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setDetail({
                          ...detail,
                          description: e.target.value || null,
                        })
                      }
                      className="text-[12px] text-white/55 bg-transparent border-0 px-0 h-7 focus-visible:ring-0 shadow-none"
                      placeholder="Add a short description…"
                    />
                  </div>
                  <div className="flex items-center gap-1.5 pt-1">
                    <span
                      title={STATUS_META[detail.status].description}
                      className={`text-[10px] rounded-full border px-2 py-0.5 ${
                        STATUS_META[detail.status].pill
                      }`}
                    >
                      {STATUS_META[detail.status].label}
                    </span>
                    <span className="text-[10px] text-white/40">
                      v{detail.version}
                    </span>
                  </div>
                </div>
              </div>

              {/* Card: How it sounds */}
              <Card
                icon={<MessageCircleHeart size={14} className="text-violet-300" />}
                title="How the agent sounds"
                subtitle="Pick the tone and what it says first."
              >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <FieldLabel label="Agent style">
                    <select
                      value={detail.persona_name}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setDetail({ ...detail, persona_name: e.target.value })
                      }
                      className="w-full h-9 bg-white/[0.04] border border-white/[0.09] rounded-[8px] px-3 text-[13px] text-white"
                    >
                      {(personas.length
                        ? personas
                        : [
                            {
                              name: "outbound_sdr",
                              description: "",
                              default_objective: "",
                            },
                          ]
                      ).map((p) => (
                        <option key={p.name} value={p.name}>
                          {personaLabel(p.name)}
                        </option>
                      ))}
                    </select>
                    {selectedPersona?.description && (
                      <p className="text-[11px] text-white/45 mt-1.5 leading-snug">
                        {selectedPersona.description}
                      </p>
                    )}
                  </FieldLabel>

                  <FieldLabel label="Goal of the call">
                    <Input
                      value={detail.default_objective ?? ""}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setDetail({
                          ...detail,
                          default_objective: e.target.value || null,
                        })
                      }
                      placeholder={
                        selectedPersona?.default_objective ||
                        "e.g. book a 15-minute discovery call"
                      }
                    />
                    <p className="text-[10px] text-white/40 mt-1">
                      Leave blank to use the agent style&apos;s default.
                    </p>
                  </FieldLabel>
                </div>

                <FieldLabel label="Opening line">
                  <Input
                    disabled={!canEdit}
                    value={detail.opening_line ?? ""}
                    onChange={(e) =>
                      setDetail({
                        ...detail,
                        opening_line: e.target.value || null,
                      })
                    }
                    placeholder='e.g. "Hi, this is the AI agent for Acme — got a minute?"'
                  />
                </FieldLabel>
              </Card>

              {/* Card: Qualification */}
              <Card
                icon={<Users size={14} className="text-violet-300" />}
                title="Qualification framework"
                subtitle="What the agent should learn during the call."
              >
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {FRAMEWORKS.map((fw) => {
                    const meta = FRAMEWORK_META[fw];
                    const selected = detail.framework === fw;
                    return (
                      <button
                        key={fw}
                        type="button"
                        disabled={!canEdit}
                        onClick={() => {
                          const next = applyFrameworkChange(detail, fw);
                          if (next) setDetail(next);
                        }}
                        className={`text-left rounded-[10px] border p-3 transition-colors ${
                          selected
                            ? "bg-violet-500/10 border-violet-500/30"
                            : "bg-white/[0.02] border-white/[0.07] hover:border-white/[0.15]"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="text-[13px] font-medium text-white">
                            {meta.label}
                          </div>
                          {selected && (
                            <CircleCheck
                              size={14}
                              className="text-violet-300"
                            />
                          )}
                        </div>
                        <div className="text-[11px] text-white/55 mt-0.5">
                          {meta.tagline}
                        </div>
                        <div className="text-[10px] text-white/40 mt-1.5 leading-snug">
                          {meta.subtitle}
                        </div>
                      </button>
                    );
                  })}
                </div>

                <PlaybookFieldEditor
                  framework={detail.framework}
                  fields={detail.fields}
                  canEdit={canEdit}
                  onChange={(fields) => setDetail({ ...detail, fields })}
                />
              </Card>

              {/* Card: Branch rules */}
              <Card
                icon={<Sparkles size={14} className="text-violet-300" />}
                title="Smart branching"
                subtitle="Adapt mid-call when conditions are met (e.g. switch persona once qualified)."
              >
                <PlaybookBranchEditor
                  branches={detail.branches ?? []}
                  fields={detail.fields}
                  personas={personas}
                  canEdit={canEdit}
                  onChange={(branches) => setDetail({ ...detail, branches })}
                />
              </Card>

              {/* Advanced (collapsed) */}
              <div className="rounded-[12px] border border-white/[0.07] bg-white/[0.02]">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((v) => !v)}
                  className="w-full flex items-center gap-2 px-4 py-3 text-left hover:bg-white/[0.02] rounded-[12px]"
                >
                  {showAdvanced ? (
                    <ChevronDown size={14} className="text-white/40" />
                  ) : (
                    <ChevronRight size={14} className="text-white/40" />
                  )}
                  <span className="text-[12px] text-white/65">
                    Advanced: replace the system prompt entirely
                  </span>
                </button>
                {showAdvanced && (
                  <div className="px-4 pb-4 space-y-2">
                    <Textarea
                      rows={5}
                      disabled={!canEdit}
                      value={detail.system_prompt ?? ""}
                      onChange={(e) =>
                        setDetail({
                          ...detail,
                          system_prompt: e.target.value || null,
                        })
                      }
                      placeholder="Leave blank to use the agent style template. When set, this replaces the persona prompt entirely."
                    />
                    <p className="text-[11px] text-white/40">
                      Most users don&apos;t need this. The agent style template
                      already adapts to the persona, framework, and branches.
                    </p>
                  </div>
                )}
              </div>

              {/* Action bar */}
              {canEdit && (
                <div className="sticky bottom-3 z-10 bg-black/60 backdrop-blur border border-white/[0.08] rounded-[12px] px-3 py-2 flex flex-wrap gap-2 items-center justify-between">
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={handleSave} disabled={saving}>
                      {saving ? (
                        <Loader2 size={14} className="mr-1.5 animate-spin" />
                      ) : null}
                      Save changes
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={handlePublish}
                      disabled={saving}
                    >
                      <Send size={13} className="mr-1.5" />
                      Publish
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleDuplicate}
                    >
                      <Copy size={13} className="mr-1.5" />
                      Duplicate
                    </Button>
                    {detail.status !== "archived" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={handleArchive}
                        className="text-rose-200/80 hover:text-rose-100"
                      >
                        <Trash2 size={13} className="mr-1.5" />
                        Archive
                      </Button>
                    )}
                  </div>
                </div>
              )}

              {/* Test card */}
              <Card
                icon={<Sparkles size={14} className="text-violet-300" />}
                title="Try a sample line"
                subtitle="Paste what the lead might say. We'll show you what gets scored."
              >
                <Textarea
                  rows={3}
                  value={testText}
                  onChange={(e) => setTestText(e.target.value)}
                  placeholder='e.g. "Yes, we have $50k for Q3 and I am the VP of Sales."'
                />
                <Button
                  size="sm"
                  className="mt-3"
                  onClick={handleTest}
                  disabled={saving}
                >
                  Run test turn
                </Button>
                {testResult && <TestResult result={testResult} detail={detail} />}
              </Card>
            </div>
          ) : (
            <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-10 text-center text-white/40">
              <BookOpen size={26} className="mx-auto mb-2 opacity-40" />
              <div className="text-[13px]">Select a playbook to edit</div>
              <p className="text-[11px] mt-1 text-white/35">
                Or create a new one from the top right.
              </p>
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}

function FieldLabel({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wide font-medium text-white/40 mb-1.5">
        {label}
      </label>
      {children}
    </div>
  );
}

function Card({
  icon,
  title,
  subtitle,
  children,
}: {
  icon?: React.ReactNode;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-5 space-y-4">
      <div>
        <div className="flex items-center gap-2 text-[13px] font-medium text-white/85">
          {icon}
          {title}
        </div>
        {subtitle && (
          <p className="text-[11px] text-white/45 mt-0.5">{subtitle}</p>
        )}
      </div>
      {children}
    </div>
  );
}

function TestResult({
  result,
  detail,
}: {
  result: TestResultData;
  detail: PlaybookDetail;
}) {
  const meta = QUAL_STATUS_META[result.status] ?? QUAL_STATUS_META.in_progress;
  const fieldByKey = new Map(detail.fields.map((f) => [f.key, f]));
  const branchById = new Map(
    (detail.branches ?? []).map((b) => [b.id, b])
  );
  const StatusIcon =
    result.status === "qualified"
      ? CircleCheck
      : result.status === "disqualified"
      ? CircleX
      : CircleDashed;
  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <ScoreRing value={result.score} />
        <div className="flex-1 min-w-[180px]">
          <div
            className={`inline-flex items-center gap-1.5 text-[11px] rounded-full border px-2 py-0.5 ${meta.pill}`}
          >
            <StatusIcon size={12} />
            {meta.label}
          </div>
          <div className="text-[12px] text-white/60 mt-1">
            Score {result.score} / 100
          </div>
        </div>
      </div>

      <ResultRow
        label="Newly answered"
        emptyText="No fields matched this turn."
      >
        {result.newly.map((k) => {
          const f = fieldByKey.get(k);
          return (
            <span
              key={k}
              className="text-[11px] rounded-full border border-emerald-400/25 bg-emerald-500/10 text-emerald-200 px-2 py-0.5"
            >
              {f?.display_name ?? k}
            </span>
          );
        })}
      </ResultRow>

      <ResultRow
        label="Branches that fired"
        emptyText="No branch rules triggered."
      >
        {result.fired.map((id) => {
          const b = branchById.get(id);
          return (
            <span
              key={id}
              className="text-[11px] rounded-full border border-violet-400/25 bg-violet-500/10 text-violet-100 px-2 py-0.5"
            >
              {b?.name ?? id}
            </span>
          );
        })}
      </ResultRow>
    </div>
  );
}

function ResultRow({
  label,
  emptyText,
  children,
}: {
  label: string;
  emptyText: string;
  children: React.ReactNode;
}) {
  const arr = Array.isArray(children) ? children : [children];
  const isEmpty = arr.length === 0 || arr.every((c) => !c);
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-white/40 mb-1">
        {label}
      </div>
      {isEmpty ? (
        <div className="text-[11px] text-white/40">{emptyText}</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">{children}</div>
      )}
    </div>
  );
}

function ScoreRing({ value }: { value: number }) {
  const v = Math.max(0, Math.min(100, value));
  const radius = 22;
  const c = 2 * Math.PI * radius;
  const dash = (v / 100) * c;
  const color =
    v >= 75 ? "#34d399" : v >= 40 ? "#fbbf24" : "#f87171";
  return (
    <div className="relative w-[58px] h-[58px]">
      <svg viewBox="0 0 60 60" className="w-full h-full -rotate-90">
        <circle
          cx="30"
          cy="30"
          r={radius}
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="6"
          fill="none"
        />
        <circle
          cx="30"
          cy="30"
          r={radius}
          stroke={color}
          strokeWidth="6"
          fill="none"
          strokeDasharray={`${dash} ${c}`}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-[14px] font-semibold text-white">
        {v}
      </div>
    </div>
  );
}
