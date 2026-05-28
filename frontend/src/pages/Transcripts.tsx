import { useMemo, useState } from "react";
import {
  Clock,
  Copy,
  Download,
  FileText,
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  Search,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";

import AppLayout from "@/components/layout/AppLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Direction = "inbound" | "outbound";
type Sentiment = "positive" | "neutral" | "negative";

type TurnSpeaker = "agent" | "lead";

type Turn = {
  speaker: TurnSpeaker;
  at: string;
  text: string;
};

type Transcript = {
  id: string;
  lead: string;
  company: string;
  agent: string;
  direction: Direction;
  duration: string;
  startedAt: string;
  sentiment: Sentiment;
  summary: string;
  tags: string[];
  turns: Turn[];
};

const TRANSCRIPTS: Transcript[] = [
  {
    id: "tr_001",
    lead: "Aarav Sharma",
    company: "Northwind Labs",
    agent: "Aditi R.",
    direction: "outbound",
    duration: "6m 12s",
    startedAt: "Today · 14:22",
    sentiment: "positive",
    summary:
      "Aarav confirmed budget approval for Q3 and asked for a tailored demo focused on outbound dialer flows. Demo scheduled for next Tuesday.",
    tags: ["Demo scheduled", "Budget confirmed"],
    turns: [
      {
        speaker: "agent",
        at: "00:00",
        text: "Hi Aarav, thanks for picking up. This is Aditi from Aifficient — is now a quick moment to chat about your outbound stack?",
      },
      {
        speaker: "lead",
        at: "00:08",
        text: "Sure, I have about ten minutes before my next call.",
      },
      {
        speaker: "agent",
        at: "00:11",
        text: "Perfect. Last time we spoke you mentioned your team was juggling two dialers — has that changed?",
      },
      {
        speaker: "lead",
        at: "00:18",
        text: "It actually got worse. We just absorbed another team and they bring a third tool. We have budget approved for Q3 to consolidate.",
      },
      {
        speaker: "agent",
        at: "00:32",
        text: "Great signal. Would a 30-minute tailored demo focused on dialer flows work next Tuesday?",
      },
      {
        speaker: "lead",
        at: "00:40",
        text: "Tuesday 4pm IST works. Send the invite to me and our ops lead.",
      },
    ],
  },
  {
    id: "tr_002",
    lead: "Priya Iyer",
    company: "Brightpath",
    agent: "Karan S.",
    direction: "inbound",
    duration: "3m 48s",
    startedAt: "Today · 11:04",
    sentiment: "neutral",
    summary:
      "Priya asked about integrations with HubSpot and pricing tiers. Sent integration docs and pricing PDF after the call.",
    tags: ["Pricing", "Integration"],
    turns: [
      {
        speaker: "lead",
        at: "00:00",
        text: "Hi, I was looking at your site — do you integrate with HubSpot natively?",
      },
      {
        speaker: "agent",
        at: "00:05",
        text: "Hi Priya, yes — bi-directional sync for contacts, calls, and notes. Are you on the Pro or Enterprise HubSpot tier?",
      },
      {
        speaker: "lead",
        at: "00:14",
        text: "Pro for now, planning to move up.",
      },
      {
        speaker: "agent",
        at: "00:18",
        text: "Got it. Pro is fully supported. I'll send our integration doc and the pricing breakdown right after this call.",
      },
    ],
  },
  {
    id: "tr_003",
    lead: "Daniel Cohen",
    company: "Helio Energy",
    agent: "Riya M.",
    direction: "outbound",
    duration: "8m 51s",
    startedAt: "Yesterday · 17:38",
    sentiment: "positive",
    summary:
      "Strong fit. Daniel wants to pilot with 5 reps for 30 days starting in two weeks. Contract draft going out today.",
    tags: ["Pilot", "Contract", "Hot"],
    turns: [
      {
        speaker: "agent",
        at: "00:00",
        text: "Daniel, thanks for the time. I want to keep this tight — last call you said pilot was on the table if we could prove ramp-up under two weeks.",
      },
      {
        speaker: "lead",
        at: "00:11",
        text: "Right. And the call quality has to be airtight, we're in regulated territory.",
      },
      {
        speaker: "agent",
        at: "00:17",
        text: "Understood. We're SOC 2 Type II, and all calls are stored in your region. Pilot with 5 reps for 30 days, starting in two weeks — workable?",
      },
      {
        speaker: "lead",
        at: "00:28",
        text: "Workable. Send the contract today, I'll loop in legal.",
      },
    ],
  },
  {
    id: "tr_004",
    lead: "Lucas Ferreira",
    company: "Viacore",
    agent: "Karan S.",
    direction: "outbound",
    duration: "2m 10s",
    startedAt: "2 days ago · 09:14",
    sentiment: "negative",
    summary:
      "Lucas signed with a competitor last quarter. Marked lost; revisit in 6 months when their contract is up.",
    tags: ["Lost", "Revisit Q4"],
    turns: [
      {
        speaker: "agent",
        at: "00:00",
        text: "Lucas, hi — circling back on our conversation from March.",
      },
      {
        speaker: "lead",
        at: "00:04",
        text: "Appreciate it, but we signed with another vendor last quarter. Locked in for a year.",
      },
      {
        speaker: "agent",
        at: "00:10",
        text: "Understood. Mind if I reach back out in Q4 closer to renewal?",
      },
      {
        speaker: "lead",
        at: "00:14",
        text: "Yes, that's fine.",
      },
    ],
  },
  {
    id: "tr_005",
    lead: "Mei Tanaka",
    company: "OrbitFin",
    agent: "Aditi R.",
    direction: "inbound",
    duration: "5m 02s",
    startedAt: "3 days ago · 15:50",
    sentiment: "positive",
    summary:
      "Mei reviewed the contract and signed off. Asked about onboarding timeline — kickoff scheduled for Monday.",
    tags: ["Closed-Won", "Onboarding"],
    turns: [
      {
        speaker: "lead",
        at: "00:00",
        text: "Hey, contract is signed. What's next on your side?",
      },
      {
        speaker: "agent",
        at: "00:04",
        text: "Congrats and welcome! Onboarding kicks off Monday — you'll get an email today with the kickoff doc and Slack channel invite.",
      },
      {
        speaker: "lead",
        at: "00:14",
        text: "Perfect.",
      },
    ],
  },
];

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
  const [selectedId, setSelectedId] = useState<string>(TRANSCRIPTS[0].id);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return TRANSCRIPTS;
    return TRANSCRIPTS.filter(
      (t) =>
        t.lead.toLowerCase().includes(q) ||
        t.company.toLowerCase().includes(q) ||
        t.agent.toLowerCase().includes(q) ||
        t.summary.toLowerCase().includes(q) ||
        t.tags.some((tag) => tag.toLowerCase().includes(q))
    );
  }, [query]);

  const selected =
    TRANSCRIPTS.find((t) => t.id === selectedId) ?? filtered[0] ?? null;

  return (
    <AppLayout>
      <div className="space-y-5 max-w-6xl">
        <div>
          <h1 className="text-2xl font-medium text-white">Transcripts</h1>
          <p className="text-[13px] text-white/40 mt-1">
            Searchable call transcripts with AI summaries. Backend wiring coming
            soon.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-4 min-h-[640px]">
          <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] overflow-hidden flex flex-col">
            <div className="p-3 border-b border-white/[0.05]">
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

            <div className="flex-1 overflow-y-auto">
              {filtered.length === 0 ? (
                <div className="py-12 text-center text-[12px] text-white/45">
                  No transcripts match "{query}".
                </div>
              ) : (
                filtered.map((t) => {
                  const active = selected?.id === t.id;
                  const DirIcon =
                    t.direction === "inbound" ? PhoneIncoming : PhoneOutgoing;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setSelectedId(t.id)}
                      className={cn(
                        "w-full text-left px-4 py-3 border-b border-white/[0.04] transition-colors",
                        active
                          ? "bg-violet-500/[0.06]"
                          : "hover:bg-white/[0.03]"
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[13px] text-white truncate">
                          {t.lead}
                        </div>
                        <SentimentDot sentiment={t.sentiment} />
                      </div>
                      <div className="text-[11px] text-white/45 mt-0.5 truncate">
                        {t.company}
                      </div>
                      <div className="flex items-center gap-3 mt-2 text-[11px] text-white/40">
                        <span className="inline-flex items-center gap-1">
                          <DirIcon size={11} />
                          {t.direction}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <Clock size={11} />
                          {t.duration}
                        </span>
                        <span className="truncate">{t.startedAt}</span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {selected ? (
            <TranscriptDetail transcript={selected} />
          ) : (
            <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] flex items-center justify-center text-[13px] text-white/45 min-h-[480px]">
              Select a transcript to view details.
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}

function TranscriptDetail({ transcript: t }: { transcript: Transcript }) {
  const DirIcon = t.direction === "inbound" ? PhoneIncoming : PhoneOutgoing;

  function copySummary() {
    navigator.clipboard
      .writeText(t.summary)
      .then(() => toast.success("Summary copied"))
      .catch(() => toast.error("Failed to copy"));
  }

  return (
    <div className="rounded-[12px] border border-white/[0.06] bg-white/[0.02] flex flex-col overflow-hidden">
      <div className="p-5 border-b border-white/[0.05]">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-[16px] font-medium text-white truncate">
                {t.lead}
              </h2>
              <span
                className={cn(
                  "inline-flex items-center h-5 px-2 rounded-full border text-[10px] font-medium",
                  SENTIMENT_STYLES[t.sentiment].className
                )}
              >
                {SENTIMENT_STYLES[t.sentiment].label}
              </span>
            </div>
            <div className="text-[12px] text-white/45 mt-0.5">
              {t.company} · with {t.agent}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              className="border-white/[0.08] bg-white/[0.03] text-white/80 hover:bg-white/[0.06] hover:text-white"
              onClick={() => toast.message("Downloading transcript")}
            >
              <Download size={13} />
              Export
            </Button>
            <Button
              size="sm"
              className="bg-violet-600 hover:bg-violet-500 text-white"
              onClick={() => toast.message("Recall is queued")}
            >
              <Phone size={13} />
              Call again
            </Button>
          </div>
        </div>

        <div className="flex items-center gap-3 mt-4 text-[11px] text-white/50">
          <span className="inline-flex items-center gap-1">
            <DirIcon size={12} />
            {t.direction}
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock size={12} />
            {t.duration}
          </span>
          <span>{t.startedAt}</span>
        </div>
      </div>

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
        <p className="text-[13px] text-white/80 leading-relaxed mt-3">
          {t.summary}
        </p>
        {t.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {t.tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center h-5 px-2 rounded-full bg-white/[0.05] border border-white/[0.08] text-[11px] text-white/70"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <div className="flex items-center gap-2 mb-4 text-[11px] font-medium text-white/45 uppercase tracking-wider">
          <FileText size={11} />
          Transcript
        </div>
        <div className="space-y-3">
          {t.turns.map((turn, i) => (
            <TurnRow key={i} turn={turn} />
          ))}
        </div>
      </div>
    </div>
  );
}

function TurnRow({ turn }: { turn: Turn }) {
  const isAgent = turn.speaker === "agent";
  return (
    <div className="flex gap-3">
      <div
        className={cn(
          "shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-full border text-[10px] font-medium",
          isAgent
            ? "bg-violet-500/10 border-violet-500/25 text-violet-200"
            : "bg-white/[0.05] border-white/[0.08] text-white/75"
        )}
      >
        {isAgent ? "AI" : "L"}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[11px] text-white/45">
          <span className="font-medium text-white/65">
            {isAgent ? "Agent" : "Lead"}
          </span>
          <span>·</span>
          <span>{turn.at}</span>
        </div>
        <p className="text-[13px] text-white/85 leading-relaxed mt-1">
          {turn.text}
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
