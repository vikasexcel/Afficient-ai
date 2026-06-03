import { api } from "./auth";

export type VoiceProvider = {
  id: string;
  label: string;
  enabled: boolean;
};

export type RegistryVoice = {
  provider: string;
  voice_id: string;
  name: string;
  gender: string;
  accent: string;
  language: string;
  description: string | null;
};

export type VoiceRegistry = {
  providers: VoiceProvider[];
  genders: string[];
  accents: string[];
  voices: RegistryVoice[];
};

/** Curated, human-friendly voices for the Voice Settings dropdowns.
 *  Voice IDs are managed server-side; the client never hardcodes them. */
export async function getVoiceRegistry(): Promise<VoiceRegistry> {
  const res = await api.get<VoiceRegistry>("/tts/voice-registry");
  return res.data;
}

export type VoicePreviewInput = {
  voice_id?: string | null;
  provider?: string | null;
  text?: string;
};

/** Synthesize a sample clip and return an object URL for <audio> playback.
 *  Caller is responsible for revoking the URL when done. */
export async function previewVoice(
  input: VoicePreviewInput
): Promise<string> {
  const res = await api.post("/tts/voice-preview", input, {
    responseType: "blob",
  });
  const blob = res.data as Blob;
  return URL.createObjectURL(blob);
}
