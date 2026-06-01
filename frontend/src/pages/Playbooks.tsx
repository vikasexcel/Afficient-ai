import { useEffect, useState } from "react";
import { BookOpen, Loader2, Plus, RefreshCw, Sparkles } from "lucide-react";
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

const FRAMEWORKS: PlaybookFramework[] = ["BANT", "MEDDICC", "CUSTOM"];

export default function Playbooks() {
  const me = useMe((s) => s.data);
  const canEdit = canManageMembers(me?.role);

  const [playbooks, setPlaybooks] = useState<PlaybookSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PlaybookDetail | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testText, setTestText] = useState(
    "We have budget approved for Q3 and I'm the VP of Sales."
  );
  const [testResult, setTestResult] = useState<string | null>(null);

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
        name: `New Playbook ${playbooks.length + 1}`,
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

  async function handleTest() {
    if (!detail) return;
    setSaving(true);
    try {
      const res = await testPlaybook(detail.id, { user_text: testText });
      setTestResult(
        `Score: ${(res.qualification_after as { score?: number }).score ?? "?"}/100\n` +
          `New fields: ${res.newly_set_fields.join(", ") || "none"}\n` +
          `Branches fired: ${res.branches_fired?.join(", ") || "none"}`
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Test failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppLayout>
      <div className="max-w-6xl space-y-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[22px] font-semibold text-white">Playbooks</h1>
            <p className="text-[13px] text-white/35 mt-0.5">
              Conversation prompts + BANT/MEDDICC qualification logic
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={loadList} disabled={loading}>
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
          <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-3 space-y-1">
            {loading && (
              <div className="flex items-center gap-2 text-[12px] text-white/45 p-2">
                <Loader2 size={14} className="animate-spin" /> Loading…
              </div>
            )}
            {!loading && playbooks.length === 0 && (
              <p className="text-[12px] text-white/45 p-2">No playbooks yet.</p>
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
                <div className="text-[13px] text-white font-medium">{pb.name}</div>
                <div className="text-[11px] text-white/40 mt-0.5">
                  {pb.framework} · {pb.status} · v{pb.version}
                </div>
              </button>
            ))}
          </div>

          {detail ? (
            <div className="space-y-4">
              <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-5 space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Field label="Name">
                    <Input
                      value={detail.name}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setDetail({ ...detail, name: e.target.value })
                      }
                    />
                  </Field>
                  <Field label="Status">
                    <div className="h-9 flex items-center text-[13px] text-white/70">
                      {detail.status} · version {detail.version}
                    </div>
                  </Field>
                  <Field label="Framework">
                    <select
                      value={detail.framework}
                      disabled={!canEdit}
                      onChange={(e) =>
                        setDetail({
                          ...detail,
                          framework: e.target.value as PlaybookFramework,
                        })
                      }
                      className="w-full h-9 bg-white/[0.04] border border-white/[0.09] rounded-[8px] px-3 text-[13px] text-white"
                    >
                      {FRAMEWORKS.map((f) => (
                        <option key={f} value={f}>
                          {f}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Persona">
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
                        : [{ name: "outbound_sdr", description: "", default_objective: "" }]
                      ).map((p) => (
                        <option key={p.name} value={p.name}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>

                <Field label="System prompt override (optional)">
                  <Textarea
                    rows={4}
                    disabled={!canEdit}
                    value={detail.system_prompt ?? ""}
                    onChange={(e) =>
                      setDetail({ ...detail, system_prompt: e.target.value || null })
                    }
                    placeholder="Leave blank to use the persona template"
                  />
                </Field>

                <Field label="Opening line">
                  <Input
                    disabled={!canEdit}
                    value={detail.opening_line ?? ""}
                    onChange={(e) =>
                      setDetail({ ...detail, opening_line: e.target.value || null })
                    }
                  />
                </Field>

                <Field label="Branch rules (JSON)">
                  <Textarea
                    rows={8}
                    disabled={!canEdit}
                    className="font-mono text-[11px]"
                    value={JSON.stringify(detail.branches ?? [], null, 2)}
                    onChange={(e) => {
                      try {
                        const parsed = JSON.parse(e.target.value) as unknown;
                        if (Array.isArray(parsed)) {
                          setDetail({ ...detail, branches: parsed });
                        }
                      } catch {
                        /* allow invalid JSON while typing */
                      }
                    }}
                    placeholder='[{"id":"handoff","name":"...","when":{},"then":{}}]'
                  />
                  <p className="text-[10px] text-white/35 mt-1">
                    Fires after each turn when conditions match. Actions: switch_persona,
                    dynamic_block, objective, end_call.
                  </p>
                </Field>

                <div>
                  <div className="text-[11px] font-medium text-white/40 mb-2">
                    Qualification fields ({detail.fields.length})
                  </div>
                  <div className="space-y-2">
                    {detail.fields.map((f) => (
                      <div
                        key={f.key}
                        className="rounded-[8px] border border-white/[0.07] bg-white/[0.02] px-3 py-2"
                      >
                        <div className="text-[12px] text-white">
                          {f.display_name}{" "}
                          <span className="text-white/35">({f.key})</span>
                        </div>
                        <div className="text-[11px] text-white/40">
                          weight {f.weight}
                          {f.required ? " · required" : ""}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {canEdit && (
                  <div className="flex flex-wrap gap-2 pt-2">
                    <Button size="sm" onClick={handleSave} disabled={saving}>
                      Save draft
                    </Button>
                    <Button size="sm" variant="secondary" onClick={handlePublish} disabled={saving}>
                      Publish
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        if (!detail) return;
                        const dup = await duplicatePlaybook(detail.id);
                        setSelectedId(dup.id);
                        toast.success("Duplicated");
                        await loadList();
                      }}
                    >
                      Duplicate
                    </Button>
                    {detail.status !== "archived" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          if (!detail) return;
                          const archived = await archivePlaybook(detail.id);
                          setDetail(archived);
                          await loadList();
                        }}
                      >
                        Archive
                      </Button>
                    )}
                  </div>
                )}
              </div>

              <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-5">
                <div className="flex items-center gap-2 text-[12px] font-medium text-white/60 mb-3">
                  <Sparkles size={14} className="text-violet-300" />
                  Test qualification
                </div>
                <Textarea
                  rows={3}
                  value={testText}
                  onChange={(e) => setTestText(e.target.value)}
                />
                <Button size="sm" className="mt-3" onClick={handleTest} disabled={saving}>
                  Run test turn
                </Button>
                {testResult && (
                  <pre className="mt-3 text-[12px] text-white/70 whitespace-pre-wrap bg-black/20 rounded-[8px] p-3">
                    {testResult}
                  </pre>
                )}
              </div>
            </div>
          ) : (
            <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-8 text-center text-white/40">
              <BookOpen size={24} className="mx-auto mb-2 opacity-40" />
              Select a playbook to edit
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-[11px] font-medium text-white/40 mb-1.5">
        {label}
      </label>
      {children}
    </div>
  );
}
