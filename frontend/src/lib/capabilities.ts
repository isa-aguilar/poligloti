import { createContext, useContext } from "react";
import type { HealthResponse, Lang } from "./api";

/**
 * What the backend's AI services can do right now, derived from GET /health.
 * The UI adapts to it instead of failing mid-session: no speech-to-text means
 * typing, no server voice means the browser voice, no vision model hides the
 * page photo, no word timestamps hides pronunciation practice.
 */
export interface Capabilities {
  /** Speech-to-text is configured: the learner can talk. */
  stt: boolean;
  /** Read-aloud scoring and minimal pairs: STT with word timestamps. */
  pronunciation: boolean;
  /** Why pronunciation practice is off, if it is: "stt" | "timestamps". */
  pronunciationOff: "stt" | "timestamps" | null;
  /** A vision model reads pages from a photo. */
  vision: boolean;
  /** The server has a voice for this target language. */
  serverVoice: (lang: Lang) => boolean;
}

export interface CapabilitiesState {
  health: HealthResponse | null;
  /** The first /health request has not answered yet. */
  loading: boolean;
  /** The backend itself did not answer /health. */
  unreachable: boolean;
  /** A retry (deep probe) is running. */
  checking: boolean;
  caps: Capabilities;
  refresh: () => Promise<void>;
}

export function deriveCapabilities(health: HealthResponse | null): Capabilities {
  // Unknown health (backend down): stay optimistic. Hiding features would not
  // help, nothing works until the server answers, and the banner says so.
  if (!health) {
    return {
      stt: true,
      pronunciation: true,
      pronunciationOff: null,
      vision: true,
      serverVoice: () => true,
    };
  }
  const { chat, stt, tts } = health.services;
  const pronunciationOff = !stt.configured
    ? "stt"
    : stt.word_timestamps === false
      ? "timestamps"
      : null;
  const ttsLangs = new Set(tts.configured ? tts.languages : []);
  return {
    stt: stt.configured,
    pronunciation: pronunciationOff === null,
    pronunciationOff,
    vision: Boolean(chat.vision),
    serverVoice: (lang) => ttsLangs.has(lang),
  };
}

export const CapabilitiesContext = createContext<CapabilitiesState>({
  health: null,
  loading: false,
  unreachable: false,
  checking: false,
  caps: deriveCapabilities(null),
  refresh: async () => undefined,
});

export function useCapabilities(): CapabilitiesState {
  return useContext(CapabilitiesContext);
}
