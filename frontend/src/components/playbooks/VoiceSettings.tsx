import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Play, Square } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  getVoiceRegistry,
  previewVoice,
  type RegistryVoice,
  type VoiceRegistry,
} from "@/services/tts";
import type { PlaybookDetail } from "@/services/playbook";

const PREVIEW_TEXT =
  "Hi, this is your AI agent. Thank you for taking my call.";

type VoicePatch = Partial<
  Pick<
    PlaybookDetail,
    | "voice_provider"
    | "voice_id"
    | "voice_name"
    | "voice_gender"
    | "voice_accent"
    | "voice_language"
  >
>;

const selectClass =
  "w-full h-9 bg-white/[0.04] border border-white/[0.09] rounded-[8px] px-3 text-[13px] text-white disabled:opacity-50";

function genderLabel(g: string): string {
  return g.charAt(0).toUpperCase() + g.slice(1);
}

export default function VoiceSettings({
  detail,
  canEdit,
  onChange,
}: {
  detail: PlaybookDetail;
  canEdit: boolean;
  onChange: (patch: VoicePatch) => void;
}) {
  const [registry, setRegistry] = useState<VoiceRegistry | null>(null);
  const [loading, setLoading] = useState(true);
  const [useCustom, setUseCustom] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  const provider = detail.voice_provider || "elevenlabs";

  useEffect(() => {
    let alive = true;
    getVoiceRegistry()
      .then((reg) => {
        if (!alive) return;
        setRegistry(reg);
        // Infer "custom" mode: a voice_id that isn't part of the curated
        // registry must have been pasted in by an advanced user.
        if (detail.voice_id) {
          const known = reg.voices.some(
            (v) => v.voice_id === detail.voice_id
          );
          setUseCustom(!known);
        }
      })
      .catch(() => {})
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id]);

  // Cleanup any audio/object URL on unmount.
  useEffect(() => {
    return () => {
      audioRef.current?.pause();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, []);

  const filteredVoices: RegistryVoice[] = useMemo(() => {
    if (!registry) return [];
    return registry.voices.filter((v) => {
      if (v.provider !== provider) return false;
      if (detail.voice_gender && v.gender !== detail.voice_gender) return false;
      if (detail.voice_accent && v.accent !== detail.voice_accent) return false;
      return true;
    });
  }, [registry, provider, detail.voice_gender, detail.voice_accent]);

  // When gender/accent change so the saved voice no longer matches, clear it
  // so the dropdown can't display a stale/hidden selection.
  useEffect(() => {
    if (useCustom || !registry || !detail.voice_id) return;
    const known = registry.voices.some((v) => v.voice_id === detail.voice_id);
    if (!known) return; // custom id pasted elsewhere — leave it alone
    const stillMatches = filteredVoices.some(
      (v) => v.voice_id === detail.voice_id
    );
    if (!stillMatches) {
      onChange({ voice_id: null, voice_name: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.voice_gender, detail.voice_accent, registry, useCustom]);

  function selectVoice(voiceId: string) {
    const v = registry?.voices.find((x) => x.voice_id === voiceId);
    if (!v) {
      onChange({ voice_id: voiceId || null });
      return;
    }
    onChange({
      voice_provider: v.provider,
      voice_id: v.voice_id,
      voice_name: v.name,
      voice_gender: v.gender,
      voice_accent: v.accent,
      voice_language: v.language,
    });
  }

  function toggleCustom(on: boolean) {
    setUseCustom(on);
    if (on) {
      // Switching to custom: clear the friendly name so it reads as custom.
      onChange({ voice_name: "Custom" });
    } else {
      // Switching back to dropdown: drop the custom id so the user re-picks.
      onChange({ voice_id: null, voice_name: null });
    }
  }

  function stopPreview() {
    audioRef.current?.pause();
    if (audioRef.current) audioRef.current.currentTime = 0;
    setPreviewing(false);
  }

  async function handlePreview() {
    if (previewing) {
      stopPreview();
      return;
    }
    setPreviewing(true);
    try {
      const url = await previewVoice({
        voice_id: detail.voice_id || undefined,
        provider,
        text: PREVIEW_TEXT,
      });
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => setPreviewing(false);
      audio.onerror = () => {
        setPreviewing(false);
        toast.error("Could not play the preview audio.");
      };
      await audio.play();
    } catch (err) {
      setPreviewing(false);
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ||
        (err instanceof Error ? err.message : "Preview failed");
      toast.error(msg);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[12px] text-white/45">
        <Loader2 size={14} className="animate-spin" /> Loading voices…
      </div>
    );
  }

  const providers = registry?.providers ?? [
    { id: "elevenlabs", label: "ElevenLabs", enabled: true },
  ];
  const genders = registry?.genders ?? ["female", "male"];
  const accents = registry?.accents ?? ["US", "UK"];
  // Voice dropdown is only usable once gender + accent are chosen and at
  // least one matching voice exists.
  const noVoicesAvailable =
    Boolean(detail.voice_gender) &&
    Boolean(detail.voice_accent) &&
    filteredVoices.length === 0;
  const voiceSelectDisabled = !canEdit || noVoicesAvailable;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Label label="Voice provider">
          <select
            className={selectClass}
            disabled={!canEdit}
            value={provider}
            onChange={(e) => onChange({ voice_provider: e.target.value })}
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id} disabled={!p.enabled}>
                {p.label}
                {p.enabled ? "" : " (coming soon)"}
              </option>
            ))}
          </select>
        </Label>

        <Label label="Use custom Voice ID">
          <div className="flex items-center gap-2 h-9">
            <Switch
              checked={useCustom}
              disabled={!canEdit}
              onCheckedChange={toggleCustom}
            />
            <span className="text-[12px] text-white/55">
              {useCustom
                ? "Paste any ElevenLabs Voice ID below"
                : "Pick from the dropdowns"}
            </span>
          </div>
        </Label>
      </div>

      {useCustom ? (
        <Label label="Custom Voice ID">
          <Input
            disabled={!canEdit}
            value={detail.voice_id ?? ""}
            onChange={(e) =>
              onChange({
                voice_id: e.target.value.trim() || null,
                voice_name: "Custom",
              })
            }
            placeholder="e.g. 21m00Tcm4TlvDq8ikWAM"
          />
          <p className="text-[10px] text-white/40 mt-1">
            Advanced: a custom Voice ID overrides the dropdown selection and is
            used as-is during calls.
          </p>
        </Label>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Label label="Gender">
            <select
              className={selectClass}
              disabled={!canEdit}
              value={detail.voice_gender ?? ""}
              onChange={(e) =>
                onChange({ voice_gender: e.target.value || null })
              }
            >
              <option value="">Any</option>
              {genders.map((g) => (
                <option key={g} value={g}>
                  {genderLabel(g)}
                </option>
              ))}
            </select>
          </Label>

          <Label label="Accent">
            <select
              className={selectClass}
              disabled={!canEdit}
              value={detail.voice_accent ?? ""}
              onChange={(e) =>
                onChange({ voice_accent: e.target.value || null })
              }
            >
              <option value="">Select…</option>
              {accents.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </Label>

          <Label label="Voice">
            <select
              className={selectClass}
              disabled={voiceSelectDisabled}
              value={detail.voice_id ?? ""}
              onChange={(e) => selectVoice(e.target.value)}
            >
              {noVoicesAvailable ? (
                <option value="">No voices available</option>
              ) : (
                <>
                  <option value="">Select a voice…</option>
                  {filteredVoices.map((v) => (
                    <option key={v.voice_id} value={v.voice_id}>
                      {v.name}
                      {v.accent ? ` · ${v.accent}` : ""}
                    </option>
                  ))}
                </>
              )}
            </select>
            {noVoicesAvailable && (
              <p className="text-[10px] text-amber-300/70 mt-1">
                No voices match this gender + accent.
              </p>
            )}
          </Label>
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handlePreview}
        >
          {previewing ? (
            <>
              <Square size={13} className="mr-1.5" />
              Stop
            </>
          ) : (
            <>
              <Play size={13} className="mr-1.5" />
              Preview voice
            </>
          )}
        </Button>
        <span className="text-[11px] text-white/40">
          {detail.voice_id
            ? `Plays: "${PREVIEW_TEXT}"`
            : "No voice set — preview uses the default voice."}
        </span>
      </div>
    </div>
  );
}

function Label({
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
