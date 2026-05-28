import { api } from "./auth";

export type CreateRoomInput = {
  name: string;
  empty_timeout?: number;
  max_participants?: number;
  metadata?: string;
};

export type Room = {
  sid: string | null;
  name: string;
  empty_timeout: number;
  max_participants: number;
  creation_time: number | null;
  num_participants: number;
  metadata: string | null;
};

export type TokenInput = {
  room: string;
  identity: string;
  name?: string;
  metadata?: string;
  ttl_minutes?: number;
  can_publish?: boolean;
  can_subscribe?: boolean;
  can_publish_data?: boolean;
};

export type TokenResult = {
  token: string;
  url: string;
  room: string;
  identity: string;
  expires_at: string;
};

export type LiveKitSession = {
  id: string;
  room_name: string;
  livekit_sid: string | null;
  status: string;
  created_by: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export async function createRoom(input: CreateRoomInput): Promise<Room> {
  const res = await api.post<Room>("/livekit/rooms", input);
  return res.data;
}

export async function listRooms(): Promise<Room[]> {
  const res = await api.get<{ rooms: Room[] }>("/livekit/rooms");
  return res.data.rooms;
}

export async function getRoom(name: string): Promise<Room> {
  const res = await api.get<Room>(`/livekit/rooms/${encodeURIComponent(name)}`);
  return res.data;
}

export async function deleteRoom(name: string): Promise<void> {
  await api.delete(`/livekit/rooms/${encodeURIComponent(name)}`);
}

export async function issueToken(input: TokenInput): Promise<TokenResult> {
  const res = await api.post<TokenResult>("/livekit/tokens", input);
  return res.data;
}

export async function getSession(roomName: string): Promise<LiveKitSession> {
  const res = await api.get<LiveKitSession>(
    `/livekit/sessions/${encodeURIComponent(roomName)}`
  );
  return res.data;
}
