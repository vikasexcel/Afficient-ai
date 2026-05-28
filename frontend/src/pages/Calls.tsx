import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Mic, MicOff, PhoneOff, Radio, User } from "lucide-react";

import AppLayout from "@/components/layout/AppLayout";
import { Button } from "@/components/ui/button";
import { useMe } from "@/store/me";
import { useLiveKit, type ParticipantInfo } from "@/store/livekit";

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

  const [draftRoom, setDraftRoom] = useState<string>(defaultRoomName());

  useEffect(() => {
    return () => {
      // If the page unmounts while connected, clean up.
      if (useLiveKit.getState().status === "connected") {
        useLiveKit.getState().disconnect();
      }
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
      toast.success(`Joined ${name}`);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to join room";
      toast.error(message);
    }
  }

  async function handleLeave() {
    await disconnect();
    toast.message("Left the call");
    setDraftRoom(defaultRoomName());
  }

  return (
    <AppLayout>
      <div className="max-w-3xl space-y-6">
        <div>
          <h1
            className="text-[22px] font-semibold text-white"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            Calls
          </h1>
          <p className="text-[13px] text-white/35 mt-0.5">
            Audio rooms powered by LiveKit
          </p>
        </div>

        {!isConnected ? (
          <JoinForm
            roomName={draftRoom}
            onChange={setDraftRoom}
            onJoin={handleJoin}
            disabled={isConnecting}
            connecting={isConnecting}
            error={error}
          />
        ) : (
          <LiveRoom
            roomName={roomName ?? ""}
            participants={participants}
            micEnabled={micEnabled}
            onToggleMic={() => toggleMic()}
            onLeave={handleLeave}
          />
        )}
      </div>
    </AppLayout>
  );
}

function JoinForm({
  roomName,
  onChange,
  onJoin,
  disabled,
  connecting,
  error,
}: {
  roomName: string;
  onChange: (v: string) => void;
  onJoin: () => void;
  disabled: boolean;
  connecting: boolean;
  error: string | null;
}) {
  return (
    <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-6">
      <label className="block text-[11px] font-medium text-white/40 tracking-wide mb-2">
        Room name
      </label>
      <input
        value={roomName}
        onChange={(e) => onChange(e.target.value)}
        placeholder="call-2026-05-28"
        className="w-full bg-white/[0.04] border border-white/[0.09] focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/10 rounded-[8px] px-3 py-2.5 text-[13px] text-white placeholder-white/20 outline-none transition-all"
      />

      {error && (
        <div className="mt-4 px-3 py-2.5 rounded-[8px] bg-red-500/8 border border-red-500/20 text-[12px] text-red-400">
          {error}
        </div>
      )}

      <Button
        onClick={onJoin}
        disabled={disabled}
        className="mt-5 w-full bg-violet-600 hover:bg-violet-500 text-white"
      >
        {connecting ? "Joining…" : "Join room"}
      </Button>

      <p className="text-[11px] text-white/30 mt-4 leading-relaxed">
        A new room is created on the server if it doesn't exist. Your browser
        will ask for microphone permission once you join.
      </p>
    </div>
  );
}

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
      <div className="bg-white/[0.03] border border-white/[0.07] rounded-[12px] p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-violet-500/15 text-violet-300">
              <Radio size={15} />
            </span>
            <div>
              <div className="text-[14px] font-semibold text-white">
                {roomName}
              </div>
              <div className="text-[11px] text-white/35">
                {participants.length} participant{participants.length === 1 ? "" : "s"}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
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
