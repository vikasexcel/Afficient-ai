import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  Upload,
  Voicemail,
  XCircle,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { formatAuthError } from "@/services/auth";
import {
  getVoicemailConfig,
  setVoicemailConfig,
} from "@/services/campaign";
import { listCalls, type TelephonyCall } from "@/services/telephony";
import type { CampaignOut, VoicemailConfig } from "@/types/campaign";

type Fallback = "human" | "voicemail";

const ACCEPT = ".mp3,.wav,audio/mpeg,audio/wav,audio/x-wav,audio/wave";
const MAX_BYTES = 5 * 1024 * 1024;

type Props = {
  campaign: CampaignOut;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful save so the parent can refresh. */
  onSaved?: () => void;
};

export default function VoicemailDialog({
  campaign,
  open,
  onOpenChange,
  onSaved,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);

  const [enabled, setEnabled] = useState(false);
  const [retryOnVoicemail, setRetryOnVoicemail] = useState(false);
  const [fallback, setFallback] = useState<Fallback>("human");
  const [recordingUrl, setRecordingUrl] = useState("");
  const [savedUrl, setSavedUrl] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const [lastDrop, setLastDrop] = useState<TelephonyCall | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const cfg = await getVoicemailConfig(campaign.id);
      setEnabled(cfg.voicemail_enabled);
      setRetryOnVoicemail(cfg.retry_on_voicemail);
      setFallback((cfg.amd_unknown_fallback as Fallback) ?? "human");
      setSavedUrl(cfg.voicemail_message_url ?? null);
      setRecordingUrl("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } catch (err) {
      toast.error(formatAuthError(err) || "Failed to load voicemail config");
    } finally {
      setLoading(false);
    }

    // Best-effort: find the most recent voicemail drop for this campaign.
    try {
      const calls = await listCalls({ limit: 200 });
      const dropped = calls
        .filter((c) => c.campaign_id === campaign.id && c.voicemail_dropped)
        .sort((a, b) =>
          (b.voicemail_dropped_at ?? "").localeCompare(
            a.voicemail_dropped_at ?? ""
          )
        );
      setLastDrop(dropped[0] ?? null);
    } catch {
      setLastDrop(null);
    }
  }, [campaign.id]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  function pickFile(f: File | null) {
    if (!f) {
      setFile(null);
      return;
    }
    const okExt = /\.(mp3|wav)$/i.test(f.name);
    if (!okExt) {
      toast.error("Only MP3 or WAV files are supported");
      return;
    }
    if (f.size > MAX_BYTES) {
      toast.error("File too large — max 5 MB");
      return;
    }
    setFile(f);
    // A freshly uploaded file takes precedence over a typed URL.
    setRecordingUrl("");
  }

  const hasRecordingSource =
    Boolean(file) || recordingUrl.trim().length > 0 || Boolean(savedUrl);

  async function handleSave() {
    if (enabled && !hasRecordingSource) {
      toast.error(
        "Enable voicemail drop requires a recording — upload a file or set a URL"
      );
      return;
    }
    setSaving(true);
    setProgress(file ? 0 : null);
    try {
      const payload: Parameters<typeof setVoicemailConfig>[1] = {
        voicemail_enabled: enabled,
        retry_on_voicemail: retryOnVoicemail,
        amd_unknown_fallback: fallback,
      };
      if (file) {
        payload.file = file;
      } else if (recordingUrl.trim()) {
        payload.voicemail_message_url = recordingUrl.trim();
      }

      const res = await setVoicemailConfig(campaign.id, payload, {
        onUploadProgress: (p) => setProgress(p),
      });
      applyResult(res);
      toast.success("Voicemail settings saved");
      onSaved?.();
    } catch (err) {
      toast.error(formatAuthError(err) || "Could not save voicemail settings");
    } finally {
      setSaving(false);
      setProgress(null);
    }
  }

  function applyResult(res: VoicemailConfig & { campaign_id: string }) {
    setEnabled(res.voicemail_enabled);
    setRetryOnVoicemail(res.retry_on_voicemail);
    setFallback((res.amd_unknown_fallback as Fallback) ?? "human");
    setSavedUrl(res.voicemail_message_url ?? null);
    setFile(null);
    setRecordingUrl("");
    if (fileRef.current) fileRef.current.value = "";
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg p-0 gap-0 bg-[#0c0c10] border border-white/[0.08]">
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-white/[0.06]">
          <div className="flex items-start gap-3">
            <div className="h-9 w-9 shrink-0 rounded-[10px] bg-violet-500/10 border border-violet-500/25 flex items-center justify-center">
              <Voicemail size={16} className="text-violet-300" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="text-[15px] text-white">
                Voicemail drop
              </DialogTitle>
              <DialogDescription className="text-[12px] text-white/45 mt-0.5 truncate">
                {campaign.name} — AMD detection &amp; voicemail playback
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-16 text-white/45">
            <Loader2 size={16} className="animate-spin mr-2" />
            Loading configuration…
          </div>
        ) : (
          <div className="max-h-[68vh] overflow-y-auto px-5 py-5 space-y-5">
            {/* Current configuration summary */}
            <div className="grid grid-cols-2 gap-2">
              <StatusCard
                label="Voicemail"
                ok={enabled}
                okText="Enabled"
                offText="Disabled"
              />
              <StatusCard
                label="Recording"
                ok={Boolean(savedUrl)}
                okText="Configured"
                offText="Missing"
              />
              <StatusCard
                label="Retry on voicemail"
                ok={retryOnVoicemail}
                okText="On"
                offText="Off"
              />
              <div className="rounded-[10px] border border-white/[0.07] bg-white/[0.02] px-3 py-2">
                <div className="text-[10px] uppercase tracking-wide text-white/35">
                  Last voicemail drop
                </div>
                <div className="text-[12px] text-white/80 mt-0.5 truncate">
                  {lastDrop?.voicemail_dropped_at
                    ? new Date(lastDrop.voicemail_dropped_at).toLocaleString()
                    : "—"}
                </div>
              </div>
            </div>

            <Separator className="bg-white/[0.05]" />

            {/* Enable toggle */}
            <ToggleRow
              title="Enable voicemail drop"
              hint="When AMD detects a machine, play a recording instead of bridging the AI agent"
              checked={enabled}
              onChange={setEnabled}
            />

            {/* Recording */}
            <div className="space-y-2.5">
              <Label className="text-[11px] font-medium text-white/55">
                Recording (MP3 or WAV, max 5 MB)
              </Label>

              {savedUrl && !file && (
                <div className="flex items-center justify-between gap-2 rounded-[10px] border border-emerald-500/20 bg-emerald-500/[0.06] px-3 py-2">
                  <div className="min-w-0 flex items-center gap-2 text-[12px] text-emerald-200">
                    <CheckCircle2 size={13} className="shrink-0" />
                    <span className="truncate">Recording configured</span>
                  </div>
                  <a
                    href={savedUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[11px] text-emerald-300 hover:text-emerald-200 inline-flex items-center gap-1 shrink-0"
                  >
                    Open <ExternalLink size={11} />
                  </a>
                </div>
              )}

              <div className="flex items-center gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  accept={ACCEPT}
                  className="hidden"
                  onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => fileRef.current?.click()}
                  disabled={saving}
                  className="border-white/[0.1] bg-white/[0.02] text-white/85 hover:bg-white/[0.06]"
                >
                  <Upload size={13} />
                  {file ? "Change file" : "Upload file"}
                </Button>
                {file && (
                  <span className="text-[12px] text-white/70 truncate">
                    {file.name}{" "}
                    <span className="text-white/35">
                      ({(file.size / 1024).toFixed(0)} KB)
                    </span>
                  </span>
                )}
              </div>

              {progress != null && (
                <div className="space-y-1">
                  <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                    <div
                      className="h-full bg-violet-500 transition-all"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <div className="text-[11px] text-white/45">
                    Uploading… {progress}%
                  </div>
                </div>
              )}

              <div className="flex items-center gap-2 text-[11px] text-white/30">
                <span className="h-px flex-1 bg-white/[0.06]" />
                or paste a public URL
                <span className="h-px flex-1 bg-white/[0.06]" />
              </div>

              <Input
                placeholder="https://cdn.example.com/voicemail.mp3"
                value={recordingUrl}
                disabled={saving || Boolean(file)}
                onChange={(e) => setRecordingUrl(e.target.value)}
                className="h-9 bg-white/[0.03] border-white/[0.09] text-[13px]"
              />
              <p className="text-[11px] text-white/35 leading-snug">
                Twilio fetches the recording from its own cloud, so the URL must
                be publicly reachable over HTTPS (no localhost / private hosts).
              </p>
            </div>

            <Separator className="bg-white/[0.05]" />

            {/* Retry on voicemail */}
            <ToggleRow
              title="Retry on voicemail"
              hint="Schedule another attempt when a call reaches voicemail"
              checked={retryOnVoicemail}
              onChange={setRetryOnVoicemail}
            />

            {/* Unknown fallback */}
            <div className="space-y-1.5">
              <Label className="text-[11px] font-medium text-white/55">
                Unknown answer fallback
              </Label>
              <Select
                value={fallback}
                onValueChange={(v) => setFallback(v as Fallback)}
              >
                <SelectTrigger className="w-full h-9 bg-white/[0.03] border-white/[0.09] text-[13px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent
                  className="bg-[#111114] border-white/[0.08]"
                  position="popper"
                >
                  <SelectItem value="human">
                    Continue as human (run AI conversation)
                  </SelectItem>
                  <SelectItem value="voicemail">
                    Treat as voicemail (drop recording)
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[11px] text-white/35 leading-snug">
                What to do when AMD can&apos;t classify the answer.
              </p>
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-white/[0.06] bg-white/[0.015]">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-white/55 hover:text-white"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={handleSave}
            disabled={saving || loading}
            className="bg-violet-600 hover:bg-violet-500 text-white"
          >
            {saving ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <CheckCircle2 size={13} />
            )}
            Save settings
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ToggleRow({
  title,
  hint,
  checked,
  onChange,
}: {
  title: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between rounded-[10px] border border-white/[0.07] bg-white/[0.02] px-3 py-2.5 cursor-pointer gap-3">
      <div className="min-w-0">
        <div className="text-[13px] text-white">{title}</div>
        <div className="text-[11px] text-white/45 mt-0.5">{hint}</div>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  );
}

function StatusCard({
  label,
  ok,
  okText,
  offText,
}: {
  label: string;
  ok: boolean;
  okText: string;
  offText: string;
}) {
  return (
    <div className="rounded-[10px] border border-white/[0.07] bg-white/[0.02] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-white/35">
        {label}
      </div>
      <div
        className={cn(
          "text-[12px] mt-0.5 inline-flex items-center gap-1",
          ok ? "text-emerald-300" : "text-white/45"
        )}
      >
        {ok ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
        {ok ? okText : offText}
      </div>
    </div>
  );
}
