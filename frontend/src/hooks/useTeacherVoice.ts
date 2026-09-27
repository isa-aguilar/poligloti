import { useMemo, useSyncExternalStore } from "react";
import type { Lang } from "@/lib/api";
import { localVoicesFor, subscribeVoices, voicesSnapshot } from "@/lib/browserVoice";
import { useCapabilities } from "@/lib/capabilities";
import { getBrowserVoice } from "@/lib/storage";

/** Where the teacher's voice comes from for this language. */
export type VoiceSource = "server" | "browser" | "none";

export interface TeacherVoice {
  source: VoiceSource;
  /** The on-device voice to use when source is "browser". */
  browserVoice: SpeechSynthesisVoice | null;
  /** On-device voices for the target language (for the picker). */
  localVoices: SpeechSynthesisVoice[];
}

const noVoices: SpeechSynthesisVoice[] = [];

export function useTeacherVoice(user: string, lang: Lang, refresh = 0): TeacherVoice {
  const { caps } = useCapabilities();
  const server = caps.serverVoice(lang);
  const voices = useSyncExternalStore(subscribeVoices, voicesSnapshot, () => noVoices);
  return useMemo(() => {
    const local = localVoicesFor(voices, lang);
    if (server) return { source: "server", browserVoice: null, localVoices: local };
    const stored = getBrowserVoice(user, lang);
    const voice = local.find((v) => v.voiceURI === stored) ?? local[0] ?? null;
    return { source: voice ? "browser" : "none", browserVoice: voice, localVoices: local };
    // `refresh` re-reads the stored choice after the picker changes it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voices, lang, server, user, refresh]);
}
