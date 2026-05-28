import { create } from "zustand";
import {
  ConnectionState,
  Participant,
  RemoteParticipant,
  RemoteTrack,
  RemoteTrackPublication,
  Room,
  RoomEvent,
  Track,
  type RoomConnectOptions,
} from "livekit-client";

import {
  createRoom,
  deleteRoom,
  getRoom,
  issueToken,
} from "@/services/livekit";

export type ParticipantInfo = {
  identity: string;
  name?: string;
  isSpeaking: boolean;
  isLocal: boolean;
  isMicMuted: boolean;
  audioLevel: number;
};

type Status = "idle" | "connecting" | "connected" | "error";

type LiveKitStore = {
  room: Room | null;
  roomName: string | null;
  identity: string | null;
  status: Status;
  error: string | null;
  micEnabled: boolean;
  participants: ParticipantInfo[];

  connect: (opts: ConnectOptions) => Promise<void>;
  disconnect: () => Promise<void>;
  toggleMic: () => Promise<void>;
  reset: () => void;
};

type ConnectOptions = {
  /** Room to join. Created if it doesn't exist. */
  roomName: string;
  /** Stable identity for this participant. */
  identity: string;
  /** Display name shown to others. Defaults to identity. */
  displayName?: string;
};

function snapshotParticipants(room: Room): ParticipantInfo[] {
  const list: ParticipantInfo[] = [
    toInfo(room.localParticipant, true),
    ...Array.from(room.remoteParticipants.values()).map((p) => toInfo(p, false)),
  ];
  return list;
}

function toInfo(p: Participant, isLocal: boolean): ParticipantInfo {
  const micPub = p.getTrackPublication(Track.Source.Microphone);
  return {
    identity: p.identity,
    name: p.name || undefined,
    isSpeaking: p.isSpeaking,
    isLocal,
    isMicMuted: micPub ? micPub.isMuted : true,
    audioLevel: p.audioLevel ?? 0,
  };
}

export const useLiveKit = create<LiveKitStore>((set, get) => ({
  room: null,
  roomName: null,
  identity: null,
  status: "idle",
  error: null,
  micEnabled: true,
  participants: [],

  async connect({ roomName, identity, displayName }) {
    if (get().status === "connecting" || get().status === "connected") {
      return;
    }
    set({ status: "connecting", error: null, roomName, identity });

    try {
      // Ensure the room exists. If creation fails because it already exists,
      // fall back to a plain lookup so we don't surface a misleading error.
      try {
        await createRoom({ name: roomName });
      } catch {
        await getRoom(roomName);
      }

      const tokenResult = await issueToken({
        room: roomName,
        identity,
        name: displayName ?? identity,
      });

      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });

      const refresh = () => set({ participants: snapshotParticipants(room) });

      room
        .on(RoomEvent.ParticipantConnected, refresh)
        .on(RoomEvent.ParticipantDisconnected, refresh)
        .on(RoomEvent.TrackSubscribed, (track: RemoteTrack, _pub: RemoteTrackPublication, p: RemoteParticipant) => {
          if (track.kind === Track.Kind.Audio) {
            // Attach to a hidden audio element so the user hears remote audio.
            const el = track.attach();
            el.dataset.livekitParticipant = p.identity;
            el.style.display = "none";
            document.body.appendChild(el);
          }
          refresh();
        })
        .on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
          track.detach().forEach((el) => el.remove());
          refresh();
        })
        .on(RoomEvent.ActiveSpeakersChanged, refresh)
        .on(RoomEvent.TrackMuted, refresh)
        .on(RoomEvent.TrackUnmuted, refresh)
        .on(RoomEvent.LocalTrackPublished, refresh)
        .on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
          if (state === ConnectionState.Disconnected) {
            get().reset();
          }
        });

      const connectOpts: RoomConnectOptions = { autoSubscribe: true };
      await room.connect(tokenResult.url, tokenResult.token, connectOpts);
      await room.localParticipant.setMicrophoneEnabled(true);

      set({
        room,
        status: "connected",
        micEnabled: true,
        participants: snapshotParticipants(room),
      });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to join room";
      set({ status: "error", error: message, room: null });
      throw err;
    }
  },

  async disconnect() {
    const { room, roomName } = get();
    if (room) {
      await room.disconnect();
    }
    // Best-effort cleanup of the server-side room. We swallow errors so the
    // UI always returns to idle even if the API is unreachable.
    if (roomName) {
      try {
        await deleteRoom(roomName);
      } catch {
        // ignore
      }
    }
    get().reset();
  },

  async toggleMic() {
    const { room, micEnabled } = get();
    if (!room) return;
    const next = !micEnabled;
    await room.localParticipant.setMicrophoneEnabled(next);
    set({
      micEnabled: next,
      participants: snapshotParticipants(room),
    });
  },

  reset() {
    document
      .querySelectorAll<HTMLAudioElement>("audio[data-livekit-participant]")
      .forEach((el) => el.remove());
    set({
      room: null,
      roomName: null,
      identity: null,
      status: "idle",
      error: null,
      micEnabled: true,
      participants: [],
    });
  },
}));
