import { useEffect, useMemo, useState } from "react";
import {
  Clock,
  Copy,
  Download,
  FileText,
  Loader2,
  Phone,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  finalizeCall,
  getTranscript,
  listCalls,
  type CallListEntry,
  type CallSummary,
  type QualificationSnapshot,
  type TranscriptEntry,
} from "@/services/ai";
import {
  initiateCall,
  listCalls as listTelephonyCalls,
  type TelephonyCall,
} from "@/services/telephony";

type Sentiment = "positive" | "neutral" | "negative";

function sentimentFor(c: CallListEntry): Sentiment {
  const score = c.qualification_score ?? 0;
  if (c.qualification_status === "qualified" || score >= 60) return "positive";
  if (c.qualification_status === "disqualified") return "negative";
  return "neutral";
}

function formatDuration(ms: number | null): string | null {
  if (ms == null || ms <= 0) return null;
  const totalSec = Math.round(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min === 0) return `${sec}s`;
  return `${min}m ${sec.toString().padStart(2, "0")}s`;
}

function formatRelative(iso: string): string {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return iso;
  const diff = Date.now() - ts;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

const SENTIMENT_STYLES: Record<Sentiment, { label: string; className: string }> =
  {
    positive: {
      label: "Positive",
      className: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
    },
    neutral: {
      label: "Neutral",
      className: "bg-white/[0.06] text-white/70 border-white/[0.1]",
    },
    negative: {
      label: "Negative",
      className: "bg-red-500/10 text-red-300 border-red-500/25",
    },
  };

export default function Transcripts() {
  const [query, setQuery] = useState("");
  const [calls, setCalls] = useState<CallListEntry[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Telephony records keyed by LiveKit room name (== AI call_id). Used to
  // recover the original phone number + lead for the "Call Again" action,
  // since the AI call list doesn't carry the destination number.
  const [phoneByRoom, setPhoneByRoom] = useState<Record<string, TelephonyCall>>(
    {}
  );

  async function loadCalls() {
    setLoadingList(true);
    setListError(null);
    try {
      const rows = await listCalls(50);
      setCalls(rows);
      if (rows.length > 0 && !selectedId) {
        setSelectedId(rows[0].call_id);
      }
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || (err as Error)?.message || "Failed to load calls";
      setListError(detail);
    } finally {
      setLoadingList(false);
    }
  }

  async function loadPhoneCalls() {
    try {
      const rows = await listTelephonyCalls({ limit: 200 });
      const map: Record<string, TelephonyCall> = {};
      for (const r of rows) {
        // Keep the most recent record per room (rows are newest-first).
        if (r.room_name && !map[r.room_name]) map[r.room_name] = r;
      }
      setPhoneByRoom(map);
    } catch (err) {
      // Non-fatal: the page still renders; Call Again stays disabled.
      console.error("Failed to load telephony calls for recall", err);
    }
  }

  async function refreshAll() {
    await Promise.all([loadCalls(), loadPhoneCalls()]);
  }

  useEffect(() => {
    loadCalls();
    loadPhoneCalls();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return calls;
    return calls.filter(
      (c) =>
        c.call_id.toLowerCase().includes(q) ||
        (c.summary ?? "").toLowerCase().includes(q) ||
        (c.playbook_name ?? c.persona ?? "").toLowerCase().includes(q)
    );
  }, [query, calls]);

  const selected = calls.find((c) => c.call_id === selectedId) ?? null;

  return (
    <AppLayout>
      <div className="flex flex-col gap-5 w-full min-w-0 lg:h-full lg:overflow-hidden">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 shrink-0">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-medium text-white">
              Transcripts
            </h1>
            <p className="text-[13px] text-white/40 mt-1">
              Real call transcripts and AI-generated summaries from GPT-4o.
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="border-white/[0.08] bg-white/[0.03] text-white/80 hover:bg-white/[0.06] hover:text-white self-start"
            onClick={loadCalls}
            disabled={loadingList}
          >
            <RefreshCw
              size={13}
              className={loadingList ? "animate-spin" : ""}
            />
            Refresh
          </Button>
        </div>

        <div className="flex flex-col lg:flex-row gap-4 lg:flex-1 lg:min-h-0 lg:overflow-hidden">
          <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] overflow-hidden flex flex-col w-full lg:w-[320px] xl:w-[360px] lg:shrink-0 max-h-[420px] lg:max-h-none lg:min-h-0">
            <div className="p-3 border-b border-white/[0.05] shrink-0">
              <div className="relative">
                <Search
                  size={14}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/35"
                />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search transcripts"
                  className="pl-8 h-9 bg-white/[0.03] border-white/[0.08] text-[13px]"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto min-h-0">
              {listError ? (
                <div className="py-8 px-4 text-[12px] text-red-300">
                  {listError}
                </div>
              ) : loadingList ? (
                <div className="py-12 text-center text-[12px] text-white/45">
                  Loading…
                </div>
              ) : filtered.length === 0 ? (
                <div className="py-12 px-6 text-center text-[12px] text-white/45 space-y-2">
                  <FileText
                    size={20}
                    className="mx-auto text-white/30"
                  />
                  <p>No AI calls yet.</p>
                  <p className="text-[11px] text-white/35">
                    Start a conversation from the Calls page — transcripts and
                    summaries will appear here automatically.
                  </p>
                </div>
              ) : (
                filtered.map((c) => {
                  const active = selected?.call_id === c.call_id;
                  const sent = sentimentFor(c);
                  return (
                    <button
                      key={c.call_id}
                      type="button"
                      onClick={() => setSelectedId(c.call_id)}
                      className={cn(
                        "w-full text-left px-4 py-3 border-b border-white/[0.04] transition-colors",
                        active
                          ? "bg-violet-500/[0.06]"
                          : "hover:bg-white/[0.03]"
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[13px] text-white truncate font-mono">
                          {c.call_id}
                        </div>
                        <SentimentDot sentiment={sent} />
                      </div>
                      <div className="text-[11px] text-white/45 mt-0.5 truncate">
                        {c.playbook_name ?? c.persona ?? "—"} ·{" "}
                        {c.framework ?? "BANT"}
                        {c.playbook_version ? ` · v${c.playbook_version}` : ""}
                      </div>
                      <div className="flex items-center gap-3 mt-2 text-[11px] text-white/40">
                        <span className="inline-flex items-center gap-1">
                          <FileText size={11} />
                          {c.total_turns} turns
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <Clock size={11} />
                          {formatRelative(c.updated_at)}
                        </span>
                        {formatDuration(c.duration_ms) && (
                          <span>{formatDuration(c.duration_ms)}</span>
                        )}
                        {c.qualification_score != null && (
                          <span className="ml-auto text-violet-300 font-medium">
                            {c.qualification_score}/100
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {selected ? (
            <TranscriptDetail
              call={selected}
              phoneCall={phoneByRoom[selected.call_id] ?? null}
              onChanged={loadCalls}
              onRecall={refreshAll}
            />
          ) : (
            <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] flex items-center justify-center text-[13px] text-white/45 w-full min-w-0 lg:flex-1 min-h-[480px] lg:min-h-0 lg:h-full">
              {calls.length === 0 && !loadingList
                ? "Run a conversation from the Calls page to populate this view."
                : "Select a transcript to view details."}
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

function TranscriptDetail({
  call,
  phoneCall,
  onChanged,
  onRecall,
}: {
  call: CallListEntry;
  phoneCall: TelephonyCall | null;
  onChanged: () => Promise<void> | void;
  onRecall: () => Promise<void> | void;
}) {
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [summary, setSummary] = useState<CallSummary | null>(null);
  const [calling, setCalling] = useState(false);

  const recallNumber = phoneCall?.to_number ?? null;

  async function handleCallAgain() {
    if (!recallNumber) {
      toast.error(
        "No phone number on record for this transcript — can't redial."
      );
      return;
    }
    setCalling(true);
    try {
      const newCall = await initiateCall({
        to_number: recallNumber,
        lead_name: phoneCall?.lead_name ?? undefined,
        lead_id: phoneCall?.lead_id ?? undefined,
        lead_phone: phoneCall?.lead_phone ?? undefined,
        campaign_id: phoneCall?.campaign_id ?? undefined,
        // Playbook lives on the AI call; persona is the fallback.
        playbook_id: call.playbook_id ?? undefined,
        persona: call.playbook_id ? undefined : call.persona ?? undefined,
      });
      toast.success(
        `Calling ${newCall.to_number}${
          newCall.lead_name ? ` (${newCall.lead_name})` : ""
        } — new call started`
      );
      await onRecall();
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || (err as Error)?.message || "Failed to start call";
      console.error("Call Again failed", err);
      toast.error(detail);
    } finally {
      setCalling(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSummary(null);
    getTranscript(call.call_id)
      .then((res) => {
        if (cancelled) return;
        setEntries(res.entries);
      })
      .catch((err) => {
        if (cancelled) return;
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail || (err as Error)?.message || "Failed to load transcript";
        setError(detail);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [call.call_id]);

  async function copySummary() {
    const text = summary?.summary ?? call.summary;
    if (!text) {
      toast.message("No summary yet — finalize the call first.");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Summary copied");
    } catch {
      toast.error("Failed to copy");
    }
  }

  async function handleFinalize() {
    setFinalizing(true);
    try {
      const res = await finalizeCall(call.call_id);
      setSummary(res);
      toast.success("Call finalized");
      await onChanged();
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || (err as Error)?.message || "Failed to finalize";
      toast.error(detail);
    } finally {
      setFinalizing(false);
    }
  }

  const displaySummary = summary?.summary ?? call.summary;
  const displayQualification: QualificationSnapshot | null =
    summary?.qualification ?? null;

  const sent = sentimentFor(call);
  const sentStyle = SENTIMENT_STYLES[sent];

  return (
    <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] flex flex-col overflow-hidden w-full min-w-0 lg:flex-1 lg:h-full lg:min-h-0">
      <div className="p-4 sm:p-5 border-b border-white/[0.05] shrink-0 sticky top-0 z-10">
        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[14px] sm:text-[15px] font-mono text-white truncate min-w-0 max-w-full">
                {call.call_id}
              </h2>
              <span
                className={cn(
                  "inline-flex items-center h-5 px-2 rounded-full border text-[10px] font-medium",
                  sentStyle.className
                )}
              >
                {sentStyle.label}
              </span>
            </div>
            <div className="text-[12px] text-white/45 mt-0.5">
              {call.playbook_name ?? call.persona ?? "—"} ·{" "}
              {call.framework ?? "BANT"}
              {call.playbook_version ? ` · v${call.playbook_version}` : ""} ·{" "}
              {call.qualification_status ?? "in progress"}
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <Button
              variant="outline"
              size="sm"
              className="border-white/[0.08] bg-white/[0.03] text-white/80 hover:bg-white/[0.06] hover:text-white"
              onClick={handleFinalize}
              disabled={finalizing}
            >
              <Sparkles size={13} />
              {finalizing ? "Finalizing…" : "Finalize"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="border-white/[0.08] bg-white/[0.03] text-white/80 hover:bg-white/[0.06] hover:text-white"
              onClick={() =>
                downloadJson(`${call.call_id}.json`, { call, entries })
              }
            >
              <Download size={13} />
              Export
            </Button>
            <Button
              size="sm"
              className="bg-violet-600 hover:bg-violet-500 text-white"
              onClick={handleCallAgain}
              disabled={calling || !recallNumber}
              title={
                recallNumber
                  ? `Redial ${recallNumber}`
                  : "No phone number on record for this transcript"
              }
            >
              {calling ? (
                <>
                  <Loader2 size={13} className="animate-spin" />
                  Calling…
                </>
              ) : (
                <>
                  <Phone size={13} />
                  Call again
                </>
              )}
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-4 text-[11px] text-white/50">
          <span className="inline-flex items-center gap-1">
            <Clock size={12} />
            {formatRelative(call.updated_at)}
          </span>
          {formatDuration(call.duration_ms) && (
            <span className="inline-flex items-center gap-1">
              <Clock size={12} />
              {formatDuration(call.duration_ms)}
            </span>
          )}
          <span>{call.total_turns} turns</span>
          <span>{call.total_tokens} tokens</span>
          {call.qualification_score != null && (
            <span className="sm:ml-auto text-violet-300">
              score {call.qualification_score}/100
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
      {(displaySummary || displayQualification) && (
        <div className="p-5 border-b border-white/[0.05] bg-violet-500/[0.03]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center justify-center h-6 w-6 rounded-[6px] bg-violet-500/15 border border-violet-500/25 text-violet-200">
                <Sparkles size={12} />
              </span>
              <span className="text-[12px] font-medium text-white/85">
                AI summary
              </span>
            </div>
            <button
              type="button"
              onClick={copySummary}
              className="inline-flex items-center gap-1 text-[11px] text-white/55 hover:text-white/85 transition-colors"
            >
              <Copy size={11} />
              Copy
            </button>
          </div>
          {displaySummary ? (
            <p className="text-[13px] text-white/80 leading-relaxed mt-3 whitespace-pre-wrap">
              {displaySummary}
            </p>
          ) : (
            <p className="text-[12px] text-white/45 mt-3 italic">
              No summary yet — click Finalize to generate one with GPT-4o.
            </p>
          )}
          {displayQualification &&
            displayQualification.answered_fields.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {displayQualification.answered_fields.map((f) => (
                  <span
                    key={f}
                    className="inline-flex items-center h-5 px-2 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-[11px] text-emerald-300"
                  >
                    {f}
                  </span>
                ))}
              </div>
            )}
        </div>
      )}

      <div className="p-5">
        <div className="flex items-center gap-2 mb-4 text-[11px] font-medium text-white/45 uppercase tracking-wider">
          <FileText size={11} />
          Transcript {entries.length > 0 && `· ${entries.length} entries`}
        </div>

        {loading && (
          <div className="text-[12px] text-white/45">Loading transcript…</div>
        )}
        {error && (
          <div className="text-[12px] text-red-300 bg-red-500/10 border border-red-500/20 rounded-[8px] px-3 py-2">
            {error}
          </div>
        )}
        {!loading && !error && entries.length === 0 && (
          <div className="text-[12px] text-white/45 italic">
            No transcript entries yet for this call.
          </div>
        )}

        <div className="space-y-3">
          {entries.map((turn, i) => (
            <TurnRow key={i} turn={turn} />
          ))}
        </div>
      </div>
      </div>
    </div>
  );
}

function TurnRow({ turn }: { turn: TranscriptEntry }) {
  const isAssistant = turn.role === "assistant";
  const isUser = turn.role === "user";
  const tag = isAssistant ? "AI" : isUser ? "U" : turn.role.slice(0, 1).toUpperCase();
  const label = isAssistant ? "Assistant" : isUser ? "User" : turn.role;

  return (
    <div className="flex gap-3">
      <div
        className={cn(
          "shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-full border text-[10px] font-medium",
          isAssistant
            ? "bg-violet-500/10 border-violet-500/25 text-violet-200"
            : isUser
            ? "bg-white/[0.05] border-white/[0.08] text-white/75"
            : "bg-sky-500/10 border-sky-500/25 text-sky-200"
        )}
      >
        {tag}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[11px] text-white/45">
          <span className="font-medium text-white/65">{label}</span>
          <span>·</span>
          <span>{new Date(turn.ts).toLocaleTimeString()}</span>
          {turn.latency_ms != null && (
            <>
              <span>·</span>
              <span className="text-violet-300/70">{turn.latency_ms}ms</span>
            </>
          )}
        </div>
        <p className="text-[13px] text-white/85 leading-relaxed mt-1 whitespace-pre-wrap">
          {turn.content}
        </p>
      </div>
    </div>
  );
}

function SentimentDot({ sentiment }: { sentiment: Sentiment }) {
  const color =
    sentiment === "positive"
      ? "bg-emerald-400"
      : sentiment === "negative"
      ? "bg-red-400"
      : "bg-white/40";
  return <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", color)} />;
}

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
