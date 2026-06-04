import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Bot,
  CheckCircle2,
  FileText,
  Loader2,
  Mic,
  MicOff,
  Phone,
  PhoneCall,
  PhoneOff,
  Radio,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  User,
  Waves,
  X,
} from "lucide-react";

import AppLayout from "@/components/layout/AppLayout";
import { microphoneUnavailableReason } from "@/lib/media";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useMe } from "@/store/me";
import { useLiveKit, type ParticipantInfo } from "@/store/livekit";
import { useAI, type ChatBubble } from "@/store/ai";
import { transcribe, type TranscriptEvent } from "@/services/stt";
import {
  getPlaybookForDialer,
  type PlaybookDetail,
  type PlaybookSummary,
} from "@/services/playbook";
import { previewOpeningLine } from "@/lib/playbookCompany";
import { personaLabel } from "@/lib/playbookCopy";
import { describeCall, friendlyActionError } from "@/lib/callError";
import { useActivePlaybooks } from "@/hooks/useActivePlaybooks";
import {
  cancelCall,
  deleteCall,
  initiateCall,
  listCalls,
  retryCall,
  type AnswerType,
  type TelephonyCall,
} from "@/services/telephony";

function defaultRoomName(): string {
  const date = new Date();
  const stamp =
    date.toISOString().slice(0, 10).replace(/-/g, "") +
    "-" +
    Math.random().toString(36).slice(2, 6);
  return `call-${stamp}`;
}

export default function Calls() {
  const me = useMe((s) => s.data);

  const {
    status,
    error,
    roomName,
    participants,
    micEnabled,
    connect,
    disconnect,
    toggleMic,
  } = useLiveKit();

  const aiStart = useAI((s) => s.start);
  const aiReset = useAI((s) => s.reset);

  const [draftRoom, setDraftRoom] = useState<string>(defaultRoomName());
  const [playbookId, setPlaybookId] = useState<string>("");
  const [mode, setMode] = useState<"browser" | "phone">("browser");
  const {
    playbooks,
    reload: reloadPlaybooks,
    loading: playbooksLoading,
  } = useActivePlaybooks(true);

  useEffect(() => {
    if (playbooks.length === 0) return;
    setPlaybookId((current) => {
      if (!current || !playbooks.some((p) => p.id === current)) {
        return playbooks[0].id;
      }
      return current;
    });
  }, [playbooks]);

  useEffect(() => {
    return () => {
      if (useLiveKit.getState().status === "connected") {
        useLiveKit.getState().disconnect();
      }
      useAI.getState().reset();
    };
  }, []);

  const identity = useMemo(() => {
    if (me?.id) return `user-${me.id}`;
    return `guest-${Math.random().toString(36).slice(2, 8)}`;
  }, [me?.id]);

  const isConnected = status === "connected";
  const isConnecting = status === "connecting";

  async function handleJoin() {
    const name = draftRoom.trim();
    if (!name) {
      toast.error("Please enter a room name");
      return;
    }
    try {
      await connect({
        roomName: name,
        identity,
        displayName: me?.full_name || identity,
      });
      aiStart({ callId: name, playbookId: playbookId || undefined });
      toast.success(`Joined ${name}`);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to join room";
      toast.error(message);
    }
  }

  async function handleLeave() {
    await disconnect();
    aiReset();
    toast.message("Left the call");
    setDraftRoom(defaultRoomName());
  }

  return (
    <AppLayout>
      <div className="max-w-6xl space-y-6">
        <div>
          <h1
            className="text-[20px] sm:text-[22px] font-semibold text-white"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            Calls
          </h1>
          <p className="text-[12px] sm:text-[13px] text-white/35 mt-0.5">
            LiveKit audio rooms · GPT-4o assistant · Deepgram transcription ·
            Twilio outbound dialer
          </p>
        </div>

        {/* Mode tabs: browser-test room vs. real PSTN dialer */}
        <div className="inline-flex max-w-full overflow-x-auto rounded-[10px] border border-white/[0.07] bg-white/[0.02] p-1">
          <button
            type="button"
            onClick={() => setMode("browser")}
            className={`px-3 py-1.5 text-[12px] font-medium rounded-[7px] transition-colors ${
              mode === "browser"
                ? "bg-white/[0.08] text-white"
                : "text-white/50 hover:text-white/80"
            }`}
          >
            Browser test room
          </button>
          <button
            type="button"
            onClick={() => setMode("phone")}
            className={`px-3 py-1.5 text-[12px] font-medium rounded-[7px] transition-colors flex items-center gap-1.5 ${
              mode === "phone"
                ? "bg-white/[0.08] text-white"
                : "text-white/50 hover:text-white/80"
            }`}
          >
            <Phone size={12} />
            Phone dialer
          </button>
        </div>

        {mode === "browser" ? (
          !isConnected ? (
            <JoinForm
              roomName={draftRoom}
              onChange={setDraftRoom}
              onJoin={handleJoin}
              disabled={isConnecting}
              connecting={isConnecting}
              error={error}
              persona={playbookId}
              onPersonaChange={setPlaybookId}
              personas={playbooks}
            />
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[minmax(0,1fr)_380px] gap-5 items-start">
              <LiveRoom
                roomName={roomName ?? ""}
                participants={participants}
                micEnabled={micEnabled}
                onToggleMic={() => toggleMic()}
                onLeave={handleLeave}
              />
              <AIAssistantPanel />
            </div>
          )
        ) : (
          <PhoneDialerSection
            playbooks={playbooks}
            playbooksLoading={playbooksLoading}
            defaultPlaybookId={playbookId}
            onPlaybookChange={setPlaybookId}
            onRefreshPlaybooks={reloadPlaybooks}
          />
        )}
      </div>
    </AppLayout>
  );
}

// ---------------------------------------------------------------------------
// Join form
// ---------------------------------------------------------------------------

function JoinForm({
  roomName,
  onChange,
  onJoin,
  disabled,
  connecting,
  error,
  persona,
  onPersonaChange,
  personas,
}: {
  roomName: string;
  onChange: (v: string) => void;
  onJoin: () => void;
  disabled: boolean;
  connecting: boolean;
  error: string | null;
  persona: string;
  onPersonaChange: (v: string) => void;
  personas: PlaybookSummary[];
}) {
  const micWarning = microphoneUnavailableReason();

  return (
    <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-6 max-w-2xl">
      {micWarning && (
        <div className="mb-4 px-3 py-2.5 rounded-[8px] bg-amber-500/10 border border-amber-500/25 text-[12px] text-amber-200/90 leading-relaxed">
          {micWarning}
        </div>
      )}

      <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-2">
        Room name
      </label>
      <input
        value={roomName}
        onChange={(e) => onChange(e.target.value)}
        placeholder="call-2026-05-28"
        className="w-full bg-white/[0.04] border border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10 rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all"
      />

      <label className="block text-[11px] font-medium text-white/40 tracking-wide mt-5 mb-2">
        Playbook
      </label>
      <select
        value={persona}
        onChange={(e) => onPersonaChange(e.target.value)}
        className="w-full bg-white/[0.04] border border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10 rounded-[8px] px-3 py-2.5 text-[13px] text-white outline-none transition-all"
      >
        {personas.length === 0 ? (
          <option value="">No active playbooks</option>
        ) : (
          personas.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.framework})
            </option>
          ))
        )}
      </select>

      {error && (
        <div className="mt-4 px-3 py-2.5 rounded-[8px] bg-red-500/8 border border-red-500/20 text-[12px] text-red-400">
          {error}
        </div>
      )}

      <Button
        onClick={onJoin}
        disabled={disabled || !!micWarning}
        className="mt-5 w-full bg-violet-600 hover:bg-violet-500 text-white"
      >
        {connecting ? "Joining…" : "Join room"}
      </Button>

      <p className="text-[11px] text-white/30 mt-4 leading-relaxed">
        A new LiveKit room is created if it doesn't exist. Your browser will
        ask for microphone permission. Once joined, the GPT-4o assistant panel
        opens — type to converse, or use "Live transcribe" to verify your mic
        through Deepgram.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LiveKit room view
// ---------------------------------------------------------------------------

function LiveRoom({
  roomName,
  participants,
  micEnabled,
  onToggleMic,
  onLeave,
}: {
  roomName: string;
  participants: ParticipantInfo[];
  micEnabled: boolean;
  onToggleMic: () => void;
  onLeave: () => void;
}) {
  return (
    <div className="space-y-5">
      <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-4 sm:p-5">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-violet-500/15 text-violet-300 shrink-0">
              <Radio size={15} />
            </span>
            <div className="min-w-0">
              <div className="text-[14px] font-semibold text-white truncate">
                {roomName}
              </div>
              <div className="text-[11px] text-white/35">
                {participants.length} participant
                {participants.length === 1 ? "" : "s"}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <Button
              variant={micEnabled ? "secondary" : "destructive"}
              size="sm"
              onClick={onToggleMic}
            >
              {micEnabled ? <Mic size={14} /> : <MicOff size={14} />}
              {micEnabled ? "Mute" : "Unmute"}
            </Button>
            <Button variant="destructive" size="sm" onClick={onLeave}>
              <PhoneOff size={14} />
              Leave
            </Button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {participants.map((p) => (
          <ParticipantTile key={p.identity} p={p} />
        ))}
      </div>

      <LiveTranscribePanel roomName={roomName} />
    </div>
  );
}

function ParticipantTile({ p }: { p: ParticipantInfo }) {
  return (
    <div
      className={`rounded-[10px] border p-4 transition-colors ${
        p.isSpeaking
          ? "border-violet-400/60 bg-violet-500/[0.08]"
          : "border-white/[0.07] bg-white/[0.03]"
      }`}
    >
      <div className="flex items-center gap-2.5">
        <span className="inline-flex items-center justify-center w-9 h-9 rounded-full bg-white/[0.06] text-white/60">
          <User size={15} />
        </span>
        <div className="min-w-0">
          <div className="text-[13px] font-medium text-white truncate">
            {p.name || p.identity}
            {p.isLocal && (
              <span className="ml-1.5 text-[10px] text-violet-300">you</span>
            )}
          </div>
          <div className="flex items-center gap-1 text-[11px] text-white/35">
            {p.isMicMuted ? (
              <>
                <MicOff size={11} /> muted
              </>
            ) : (
              <>
                <Mic size={11} /> live
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deepgram live-transcribe smoke panel
// ---------------------------------------------------------------------------

function LiveTranscribePanel({ roomName }: { roomName: string }) {
  const [running, setRunning] = useState(false);
  const [duration, setDuration] = useState(10);
  const [events, setEvents] = useState<TranscriptEvent[]>([]);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);

  async function handleRun() {
    setRunning(true);
    setEvents([]);
    setLatencyMs(null);
    try {
      const result = await transcribe({
        room: roomName,
        duration_seconds: duration,
      });
      setEvents(result.events);
      setLatencyMs(result.duration_ms);
      const finals = result.events.filter((e) => e.kind === "final").length;
      toast.success(
        `Deepgram: ${result.events.length} events (${finals} final) in ${result.duration_ms}ms`
      );
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || (err as Error)?.message || "Transcribe failed";
      toast.error(detail);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="rounded-[12px] border border-white/[0.07] bg-white/[0.02] p-4 sm:p-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="inline-flex items-center justify-center w-7 h-7 rounded-[7px] bg-sky-500/15 text-sky-300 shrink-0">
            <Waves size={13} />
          </span>
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-white">
              Live transcribe
            </div>
            <div className="text-[11px] text-white/40">
              Pipes your mic into Deepgram for a quick STT check
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <select
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            disabled={running}
            className="bg-white/[0.04] border border-white/[0.09] rounded-[6px] px-2 py-1 text-[12px] text-white outline-none"
          >
            <option value={5}>5s</option>
            <option value={10}>10s</option>
            <option value={20}>20s</option>
            <option value={30}>30s</option>
          </select>
          <Button size="sm" disabled={running} onClick={handleRun}>
            {running ? "Listening…" : "Transcribe"}
          </Button>
        </div>
      </div>

      {events.length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="text-[11px] text-white/40">
            {events.length} events · session {latencyMs}ms
          </div>
          <div className="max-h-48 overflow-y-auto rounded-[8px] border border-white/[0.05] bg-black/30 p-3 space-y-1 font-mono">
            {events.map((e, i) => (
              <div
                key={i}
                className={`text-[11px] ${
                  e.kind === "final"
                    ? "text-emerald-300"
                    : e.kind === "partial"
                    ? "text-white/55"
                    : "text-violet-300"
                }`}
              >
                <span className="text-white/30">
                  {String(e.ts_ms).padStart(5, " ")}ms
                </span>{" "}
                <span className="uppercase tracking-wide">{e.kind}</span>
                {e.text && <span className="text-white/85"> · {e.text}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// GPT-4o assistant panel
// ---------------------------------------------------------------------------

function AIAssistantPanel() {
  const callId = useAI((s) => s.callId);
  const status = useAI((s) => s.status);
  const bubbles = useAI((s) => s.bubbles);
  const error = useAI((s) => s.error);
  const qualification = useAI((s) => s.qualification);
  const summary = useAI((s) => s.summary);
  const send = useAI((s) => s.send);
  const finalize = useAI((s) => s.finalize);

  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [bubbles.length, status]);

  async function handleSend() {
    const trimmed = draft.trim();
    if (!trimmed || status !== "idle") return;
    setDraft("");
    await send(trimmed);
  }

  async function handleFinalize() {
    const result = await finalize();
    if (result) {
      toast.success("Call finalized — summary generated");
    }
  }

  if (!callId) return null;

  return (
    <div className="rounded-[12px] border border-white/[0.07] bg-white/[0.02] flex flex-col h-[520px] sm:h-[600px] lg:h-[640px] lg:sticky lg:top-4">
      <div className="px-4 py-3 border-b border-white/[0.05] flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="inline-flex items-center justify-center w-7 h-7 rounded-[7px] bg-violet-500/15 text-violet-300 shrink-0">
            <Sparkles size={13} />
          </span>
          <div className="min-w-0">
            <div className="text-[13px] font-medium text-white">
              GPT-4o assistant
            </div>
            <div className="text-[11px] text-white/40 truncate">
              call · {callId}
            </div>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={status !== "idle" || bubbles.length === 0}
          onClick={handleFinalize}
          className="border-white/[0.08] bg-white/[0.03] text-white/80 hover:bg-white/[0.06] hover:text-white"
        >
          <CheckCircle2 size={13} />
          {status === "finalizing" ? "Finalizing…" : "Finalize"}
        </Button>
      </div>

      {qualification && (
        <div className="px-4 py-2.5 border-b border-white/[0.05] bg-violet-500/[0.03]">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-white/55">
              {qualification.framework} · {qualification.status.replace(/_/g, " ")}
            </span>
            <span className="text-violet-300 font-medium">
              {qualification.score}/100
            </span>
          </div>
          {qualification.answered_fields.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {qualification.answered_fields.map((f) => (
                <span
                  key={f}
                  className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300"
                >
                  {f}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 space-y-3"
      >
        {bubbles.length === 0 && (
          <div className="text-center text-[12px] text-white/40 pt-12">
            <Bot size={20} className="mx-auto mb-2 text-white/30" />
            Type a message to start the conversation. The assistant tracks BANT
            qualification across turns.
          </div>
        )}
        {bubbles.map((b) => (
          <Bubble key={b.id} bubble={b} />
        ))}
        {status === "sending" && (
          <div className="text-[11px] text-white/40 italic px-1">
            GPT-4o is thinking…
          </div>
        )}
        {error && (
          <div className="text-[12px] text-red-300 bg-red-500/10 border border-red-500/20 rounded-[8px] px-3 py-2">
            {error}
          </div>
        )}
        {summary?.summary && (
          <div className="mt-4 rounded-[10px] border border-violet-500/25 bg-violet-500/[0.06] p-3">
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-violet-200">
              <FileText size={11} />
              Call summary
            </div>
            <p className="text-[12px] text-white/85 leading-relaxed mt-2 whitespace-pre-wrap">
              {summary.summary}
            </p>
          </div>
        )}
      </div>

      <div className="border-t border-white/[0.05] p-3">
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Type a message…"
            disabled={status !== "idle"}
            className="flex-1 bg-white/[0.04] border border-white/[0.09] focus:border-violet-500/50 rounded-[8px] px-3 py-2 text-[13px] text-white placeholder-white/30 outline-none disabled:opacity-50"
          />
          <Button
            onClick={handleSend}
            disabled={status !== "idle" || !draft.trim()}
            className="bg-violet-600 hover:bg-violet-500 text-white"
          >
            <Send size={13} />
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Phone dialer (Twilio PSTN → LiveKit SIP → AI agent)
// ---------------------------------------------------------------------------

function PhoneDialerSection({
  playbooks,
  playbooksLoading,
  defaultPlaybookId,
  onPlaybookChange,
  onRefreshPlaybooks,
}: {
  playbooks: PlaybookSummary[];
  playbooksLoading: boolean;
  defaultPlaybookId: string;
  onPlaybookChange: (v: string) => void;
  onRefreshPlaybooks: () => void;
}) {
  const [calls, setCalls] = useState<TelephonyCall[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [answerFilter, setAnswerFilter] = useState<AnswerType | "all">("all");

  async function refresh() {
    setLoading(true);
    try {
      const data = await listCalls({
        limit: 20,
        answered_by: answerFilter === "all" ? undefined : answerFilter,
      });
      setCalls(data);
    } catch (err) {
      toast.error(friendlyActionError(err, "Failed to load calls."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick, answerFilter]);

  // Poll while any call is in a non-terminal state.
  useEffect(() => {
    const inFlight = calls.some(
      (c) =>
        c.status === "queued" ||
        c.status === "initiated" ||
        c.status === "ringing" ||
        c.status === "in-progress"
    );
    if (!inFlight) return;
    const id = setInterval(() => setRefreshTick((t) => t + 1), 3000);
    return () => clearInterval(id);
  }, [calls]);

  // Remove a deleted call from the list immediately (optimistic), so the
  // card disappears without waiting for the next refetch.
  function removeLocally(callId: string) {
    setCalls((prev) => prev.filter((c) => c.id !== callId));
  }

  return (
    // Parent is height-constrained and clips overflow so neither column can
    // push the page; each column scrolls on its own (lg+). On mobile the
    // columns stack and scroll with the page as usual.
    <div className="grid grid-cols-1 lg:grid-cols-[380px_minmax(0,1fr)] xl:grid-cols-[420px_minmax(0,1fr)] gap-5 items-stretch lg:h-[calc(100vh-13rem)] lg:overflow-hidden">
      <div className="lg:h-full lg:overflow-y-auto lg:pr-1">
        <DialerForm
          playbooks={playbooks}
          playbooksLoading={playbooksLoading}
          defaultPlaybookId={defaultPlaybookId}
          onPlaybookChange={onPlaybookChange}
          onRefreshPlaybooks={onRefreshPlaybooks}
          onPlaced={() => {
            setRefreshTick((t) => t + 1);
            onRefreshPlaybooks();
          }}
        />
      </div>
      <div className="min-h-0 lg:h-full">
        <RecentPhoneCalls
          calls={calls}
          loading={loading}
          answerFilter={answerFilter}
          onAnswerFilterChange={setAnswerFilter}
          onRefresh={() => setRefreshTick((t) => t + 1)}
          onDeleted={removeLocally}
        />
      </div>
    </div>
  );
}

function DialerForm({
  playbooks,
  playbooksLoading,
  defaultPlaybookId,
  onPlaybookChange,
  onRefreshPlaybooks,
  onPlaced,
}: {
  playbooks: PlaybookSummary[];
  playbooksLoading: boolean;
  defaultPlaybookId: string;
  onPlaybookChange: (v: string) => void;
  onRefreshPlaybooks: () => void;
  onPlaced: () => void;
}) {
  const [toNumber, setToNumber] = useState("");
  const [leadName, setLeadName] = useState("");
  const [playbookId, setPlaybookId] = useState(defaultPlaybookId);
  const [playbookPreview, setPlaybookPreview] = useState<PlaybookDetail | null>(
    null
  );
  const [playbookLoading, setPlaybookLoading] = useState(false);
  const [playbookLoadError, setPlaybookLoadError] = useState<string | null>(
    null
  );
  const [dialing, setDialing] = useState(false);

  const dialOpeningPreview = playbookPreview
    ? previewOpeningLine(playbookPreview)
    : null;

  useEffect(() => {
    setPlaybookId(defaultPlaybookId);
  }, [defaultPlaybookId]);

  useEffect(() => {
    if (!playbookId) {
      setPlaybookPreview(null);
      setPlaybookLoadError(null);
      return;
    }
    let alive = true;
    setPlaybookLoading(true);
    setPlaybookLoadError(null);
    getPlaybookForDialer(playbookId)
      .then((pb) => {
        if (!alive) return;
        setPlaybookPreview(pb);
        setPlaybookLoadError(null);
      })
      .catch((err) => {
        if (!alive) return;
        setPlaybookPreview(null);
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ||
          (err instanceof Error ? err.message : "Could not load playbook");
        setPlaybookLoadError(detail);
      })
      .finally(() => alive && setPlaybookLoading(false));
    return () => {
      alive = false;
    };
  }, [playbookId]);

  const validNumber = /^\+[1-9]\d{6,14}$/.test(toNumber.trim());

  async function handleDial() {
    if (!validNumber) {
      toast.error("Enter a phone number in E.164 format (e.g. +14155551234)");
      return;
    }
    if (!playbookId) {
      toast.error("Select a published playbook before placing a call.");
      return;
    }
    if (playbookLoadError) {
      toast.error(playbookLoadError);
      return;
    }
    if (playbookLoading || !playbookPreview) {
      toast.error("Wait for the playbook to finish loading, or pick another.");
      return;
    }
    if (playbookPreview.status !== "active") {
      toast.error("Only published (active) playbooks can be used on calls.");
      return;
    }
    setDialing(true);
    try {
      const call = await initiateCall({
        to_number: toNumber.trim(),
        lead_name: leadName.trim() || undefined,
        playbook_id: playbookId,
      });
      toast.success(
        `Dialing ${call.to_number} — sid ${call.call_sid ?? "(pending)"}`
      );
      onPlaced();
      setToNumber("");
      setLeadName("");
    } catch (err) {
      toast.error(friendlyActionError(err, "Could not place the call."));
    } finally {
      setDialing(false);
    }
  }

  return (
    <div className="rounded-[12px] border border-white/[0.07] bg-white/[0.03] p-5">
      <div className="flex items-center gap-2 mb-4">
        <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-emerald-500/15 text-emerald-300">
          <PhoneCall size={14} />
        </span>
        <div>
          <div className="text-[14px] font-semibold text-white">
            Outbound dialer
          </div>
          <div className="text-[11px] text-white/40">
            Twilio PSTN → LiveKit SIP → AI agent
          </div>
        </div>
      </div>

      <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-1.5">
        Destination number (E.164)
      </label>
      <input
        value={toNumber}
        onChange={(e) => setToNumber(e.target.value)}
        placeholder="+14155551234"
        className="w-full bg-white/[0.04] border border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10 rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all font-mono"
      />
      {toNumber && !validNumber && (
        <div className="mt-1 text-[11px] text-amber-300">
          Must start with “+” and have 7–15 digits.
        </div>
      )}

      <label className="block text-[11px] font-medium text-white/40 tracking-wide mt-4 mb-1.5">
        Lead name (optional)
      </label>
      <input
        value={leadName}
        onChange={(e) => setLeadName(e.target.value)}
        placeholder="Jane Doe"
        className="w-full bg-white/[0.04] border border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10 rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all"
      />

      <div className="flex items-center justify-between mt-4 mb-1.5">
        <label className="text-[11px] font-medium text-white/40 tracking-wide">
          Playbook (published)
        </label>
        <button
          type="button"
          onClick={onRefreshPlaybooks}
          disabled={playbooksLoading}
          className="text-[10px] text-violet-300/80 hover:text-violet-200 flex items-center gap-1"
        >
          <RefreshCw
            size={11}
            className={playbooksLoading ? "animate-spin" : ""}
          />
          Refresh list
        </button>
      </div>
      <select
        value={playbookId}
        onChange={(e) => {
          setPlaybookId(e.target.value);
          onPlaybookChange(e.target.value);
        }}
        disabled={playbooks.length === 0}
        className="w-full bg-white/[0.04] border border-white/[0.09] focus:border-violet-500/50 rounded-[8px] px-3 py-2.5 text-[13px] text-white outline-none disabled:opacity-50"
      >
        {playbooks.length === 0 ? (
          <option value="">
            {playbooksLoading
              ? "Loading playbooks…"
              : "No published playbooks — publish one in Playbooks"}
          </option>
        ) : (
          playbooks.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))
        )}
      </select>

      {playbookLoading && (
        <div className="mt-2 flex items-center gap-2 text-[11px] text-white/45">
          <Loader2 size={12} className="animate-spin" />
          Loading playbook configuration…
        </div>
      )}

      {playbookLoadError && (
        <div className="mt-2 text-[11px] text-rose-300/90 leading-snug">
          {playbookLoadError}
        </div>
      )}

      {playbookPreview && !playbookLoadError && (
        <div className="mt-3 rounded-[8px] border border-violet-500/20 bg-violet-500/5 px-3 py-2.5 space-y-1">
          <div className="text-[13px] font-semibold text-white">
            {playbookPreview.name}
          </div>
          <div className="text-[10px] text-white/40 font-mono truncate">
            ID {playbookPreview.id}
          </div>
          <div className="text-[11px] font-medium text-violet-200/90 pt-1">
            This call will follow this playbook
          </div>
          <ul className="text-[11px] text-white/50 space-y-0.5 leading-snug">
            <li>
              Style: {personaLabel(playbookPreview.persona_name)}
              {playbookPreview.voice_name
                ? ` · Voice: ${playbookPreview.voice_name}`
                : ""}
            </li>
            <li>
              Framework: {playbookPreview.framework} ·{" "}
              {playbookPreview.fields.length} qualification field
              {playbookPreview.fields.length === 1 ? "" : "s"}
            </li>
            {playbookPreview.default_objective && (
              <li>Goal: {playbookPreview.default_objective}</li>
            )}
            {playbookPreview.agent_name && (
              <li>Agent name: {playbookPreview.agent_name}</li>
            )}
            {playbookPreview.company_name && (
              <li>Company: {playbookPreview.company_name}</li>
            )}
            {dialOpeningPreview && (
              <li className="truncate" title={dialOpeningPreview}>
                Opening: {dialOpeningPreview}
              </li>
            )}
            {(playbookPreview.branches?.length ?? 0) > 0 && (
              <li>
                {playbookPreview.branches!.length} smart branch rule
                {playbookPreview.branches!.length === 1 ? "" : "s"}
              </li>
            )}
          </ul>
        </div>
      )}

      <Button
        onClick={handleDial}
        disabled={
          dialing ||
          !validNumber ||
          !playbookId ||
          playbookLoading ||
          !!playbookLoadError ||
          !playbookPreview
        }
        className="mt-5 w-full bg-emerald-600 hover:bg-emerald-500 text-white"
      >
        {dialing ? (
          <>
            <Loader2 size={13} className="animate-spin" />
            Dialing…
          </>
        ) : (
          <>
            <PhoneCall size={13} />
            Place call
          </>
        )}
      </Button>

      <p className="text-[11px] text-white/30 mt-4 leading-relaxed">
        Voice, opening line, qualification, and branching all come from the
        selected playbook. Only the destination number and optional lead name
        are set here.
      </p>
    </div>
  );
}

function RecentPhoneCalls({
  calls,
  loading,
  answerFilter,
  onAnswerFilterChange,
  onRefresh,
  onDeleted,
}: {
  calls: TelephonyCall[];
  loading: boolean;
  answerFilter: AnswerType | "all";
  onAnswerFilterChange: (v: AnswerType | "all") => void;
  onRefresh: () => void;
  onDeleted: (callId: string) => void;
}) {
  const filters: { id: AnswerType | "all"; label: string }[] = [
    { id: "all", label: "All" },
    { id: "human", label: "Human" },
    { id: "voicemail", label: "Voicemail" },
    { id: "unknown", label: "Unknown" },
  ];
  return (
    <div className="rounded-[12px] border border-white/[0.07] bg-white/[0.03] flex flex-col h-full max-h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-white/[0.05] flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-7 h-7 rounded-[7px] bg-violet-500/15 text-violet-300">
            <Phone size={13} />
          </span>
          <div>
            <div className="text-[13px] font-medium text-white">
              Recent calls
            </div>
            <div className="text-[11px] text-white/40">
              {calls.length} call{calls.length === 1 ? "" : "s"}
            </div>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={loading}
          className="border-white/[0.08] bg-white/[0.03] text-white/80 hover:bg-white/[0.06]"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
          Refresh
        </Button>
      </div>

      {/* Answer-type filter (AMD): Human / Voicemail / Unknown */}
      <div className="px-4 py-2 border-b border-white/[0.05] flex items-center gap-1.5 shrink-0 overflow-x-auto">
        {filters.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => onAnswerFilterChange(f.id)}
            className={`px-2.5 py-1 text-[11px] font-medium rounded-full transition-colors whitespace-nowrap ${
              answerFilter === f.id
                ? "bg-violet-500/20 text-violet-200"
                : "bg-white/[0.03] text-white/50 hover:text-white/80"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {calls.length === 0 ? (
        <div className="px-4 py-10 text-center text-[12px] text-white/40">
          {loading ? "Loading…" : "No calls yet. Dial one to see it here."}
        </div>
      ) : (
        <ul className="divide-y divide-white/[0.05] overflow-y-auto flex-1 min-h-0">
          {calls.map((c) => (
            <CallRow
              key={c.id}
              call={c}
              onChanged={onRefresh}
              onDeleted={onDeleted}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function CallRow({
  call,
  onChanged,
  onDeleted,
}: {
  call: TelephonyCall;
  onChanged: () => void;
  onDeleted: (callId: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const terminal = ["completed", "failed", "busy", "no-answer", "canceled"].includes(
    call.status
  );

  const friendly = describeCall(call);

  async function handleCancel() {
    setBusy(true);
    try {
      await cancelCall(call.id);
      toast.message("Call canceled");
      onChanged();
    } catch (err) {
      toast.error(friendlyActionError(err, "Could not cancel the call."));
    } finally {
      setBusy(false);
    }
  }

  async function handleRetry() {
    setBusy(true);
    try {
      const r = await retryCall(call.id);
      toast.success(
        `Retry placed — new sid ${r.new_call.call_sid ?? "(pending)"}`
      );
      onChanged();
    } catch (err) {
      toast.error(friendlyActionError(err, "Could not retry the call."));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    try {
      await deleteCall(call.id);
      onDeleted(call.id); // remove from the list immediately
      toast.success("Call record deleted");
    } catch (err) {
      toast.error(
        friendlyActionError(err, "Could not delete the call record.")
      );
      // Re-sync in case the optimistic assumption was wrong.
      onChanged();
    } finally {
      setBusy(false);
      setConfirmOpen(false);
    }
  }

  return (
    <li className="px-4 py-3">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-white">
            <span className="font-mono truncate max-w-[12rem]">
              {call.to_number}
            </span>
            {call.lead_name && (
              <span className="text-white/45 truncate max-w-[10rem]">
                · {call.lead_name}
              </span>
            )}
            <StatusPill call={call} />
            <AnswerTypePill call={call} />
            {call.direction === "inbound" && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-500/15 text-sky-300">
                inbound
              </span>
            )}
          </div>

          {/* Friendly failure reason — wraps cleanly for long messages. */}
          {friendly.reason && (
            <div className="mt-1.5 text-[12px] text-white/70 leading-snug break-words">
              <span className="text-white/40">Reason: </span>
              {friendly.reason}
            </div>
          )}

          <div className="text-[11px] text-white/35 mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
            <span className="truncate max-w-[14rem]" title={call.room_name}>
              room {call.room_name}
            </span>
            {call.call_sid && (
              <span title={call.call_sid}>
                sid {call.call_sid.slice(0, 10)}…
              </span>
            )}
            {call.duration_seconds != null && (
              <span>{call.duration_seconds}s</span>
            )}
            {call.price != null && (
              <span>
                {call.price} {call.price_unit}
              </span>
            )}
            {call.retry_count > 0 && <span>retry #{call.retry_count}</span>}
            {/* Raw technical detail kept available via tooltip only. */}
            {friendly.rawDetail && (
              <span
                className="text-white/30 truncate max-w-[14rem] cursor-help"
                title={friendly.rawDetail}
              >
                details
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {!terminal && (
            <Button
              variant="destructive"
              size="sm"
              disabled={busy}
              onClick={handleCancel}
            >
              <X size={12} />
              Cancel
            </Button>
          )}
          {friendly.canRetry && (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={handleRetry}
              className="border-white/[0.08] bg-white/[0.03] text-white/80 hover:bg-white/[0.06]"
            >
              <RefreshCw size={12} />
              Retry
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => setConfirmOpen(true)}
            aria-label="Delete call record"
            className="text-white/45 hover:text-red-300 hover:bg-red-500/[0.08]"
          >
            <Trash2 size={12} />
            Delete
          </Button>
        </div>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent className="bg-[#111114] border border-white/[0.08]">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">
              Delete this call record?
            </AlertDialogTitle>
            <AlertDialogDescription className="text-white/55">
              Are you sure you want to delete this call record? This removes the
              call and its history and cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              disabled={busy}
              className="border-white/[0.1] bg-white/[0.02] text-white/80 hover:bg-white/[0.06]"
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={busy}
              onClick={(e) => {
                e.preventDefault();
                void handleDelete();
              }}
            >
              {busy ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
}

function StatusPill({ call }: { call: TelephonyCall }) {
  const { statusLabel, tone } = describeCall(call);
  const toneClass: Record<string, string> = {
    neutral: "bg-white/[0.06] text-white/55",
    info: "bg-sky-500/15 text-sky-300",
    progress: "bg-emerald-500/15 text-emerald-300",
    success: "bg-emerald-500/20 text-emerald-200",
    warning: "bg-amber-500/15 text-amber-300",
    error: "bg-red-500/15 text-red-300",
  };
  return (
    <span
      className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full ${toneClass[tone]}`}
    >
      {statusLabel}
    </span>
  );
}

function AnswerTypePill({ call }: { call: TelephonyCall }) {
  if (!call.amd_result) return null;
  const labelMap: Record<AnswerType, string> = {
    human: "Human",
    voicemail: "Voicemail",
    unknown: "Unknown",
  };
  const toneMap: Record<AnswerType, string> = {
    human: "bg-emerald-500/15 text-emerald-300",
    voicemail: "bg-amber-500/15 text-amber-300",
    unknown: "bg-white/[0.06] text-white/55",
  };
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className={`text-[10px] px-1.5 py-0.5 rounded-full ${toneMap[call.amd_result]}`}
      >
        {labelMap[call.amd_result]}
      </span>
      {call.voicemail_dropped && (
        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-500/15 text-violet-300">
          VM dropped
        </span>
      )}
    </span>
  );
}

function Bubble({ bubble }: { bubble: ChatBubble }) {
  const isUser = bubble.role === "user";
  return (
    <div className={`flex gap-2 ${isUser ? "flex-row-reverse" : ""}`}>
      <span
        className={`shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-medium ${
          isUser
            ? "bg-white/[0.06] text-white/80"
            : "bg-violet-500/15 text-violet-200"
        }`}
      >
        {isUser ? "U" : "AI"}
      </span>
      <div
        className={`max-w-[78%] px-3 py-2 rounded-[10px] text-[13px] leading-relaxed ${
          isUser
            ? "bg-violet-600/85 text-white"
            : "bg-white/[0.04] text-white/90 border border-white/[0.06]"
        }`}
      >
        <p className="whitespace-pre-wrap">{bubble.text}</p>
        {!isUser && bubble.latency_ms != null && (
          <div className="mt-1 text-[10px] text-white/40">
            {bubble.latency_ms}ms · {bubble.total_tokens ?? 0} tokens
          </div>
        )}
      </div>
    </div>
  );
}
