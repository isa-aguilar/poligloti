import { useCallback, useEffect, useRef } from "react";
import { browserRate, speechSupported } from "@/lib/browserVoice";

// Minimal silent WAV (0 samples) to unlock the <audio> element on iOS inside a
// user gesture. After one successful play() in the gesture, iOS allows later
// programmatic play() calls (the chunks arrive async, outside the gesture).
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";

type Item = { kind: "url"; url: string } | { kind: "text"; text: string };

export interface BrowserSpeech {
  /** The on-device voice; null means text items are skipped (text only). */
  voice: SpeechSynthesisVoice | null;
  lang: string;
}

/**
 * Plays a queue in order on a single <audio> element. Items are server audio
 * URLs or, when the server has no voice for the language, text spoken with an
 * on-device browser voice. Streaming chunks are queued as they arrive; when the
 * queue empties, onDrained().
 */
export function useAudioQueue(
  audioRef: React.RefObject<HTMLAudioElement | null>,
  onDrained?: () => void,
  onBlocked?: () => void,
  speech?: BrowserSpeech,
) {
  const queue = useRef<Item[]>([]);
  const playing = useRef(false);
  // Length scale the backend used for the turn playing now. setPlaybackRate()
  // uses it to adjust the <audio> rate without re-synthesizing:
  // playbackRate = currentLs / targetLs.
  const currentLs = useRef(1.0);
  // Rate for browser-spoken text (applies from the next sentence).
  const textLs = useRef<number | null>(null);
  const drainedCb = useRef(onDrained);
  const blockedCb = useRef(onBlocked);
  const speechRef = useRef(speech);
  useEffect(() => {
    drainedCb.current = onDrained;
    blockedCb.current = onBlocked;
    speechRef.current = speech;
  });
  // Bumped by reset(): a cancelled utterance still fires onend later, and must
  // not advance the queue of the next turn.
  const generation = useRef(0);

  const playNext = useCallback(() => {
    const step = (): void => {
      const next = queue.current[0];
      if (!next) {
        playing.current = false;
        drainedCb.current?.();
        return;
      }

      if (next.kind === "text") {
        queue.current.shift();
        const sp = speechRef.current;
        if (!sp?.voice || !speechSupported() || !next.text.trim()) {
          step(); // no on-device voice: text only
          return;
        }
        playing.current = true;
        const u = new SpeechSynthesisUtterance(next.text);
        u.voice = sp.voice;
        u.lang = sp.voice.lang || sp.lang;
        u.rate = browserRate(textLs.current);
        const gen = generation.current;
        const advance = () => {
          if (gen === generation.current && playing.current) step();
        };
        u.onend = advance;
        u.onerror = advance;
        window.speechSynthesis.speak(u);
        return;
      }

      const el = audioRef.current;
      if (!el) {
        // The <audio> is not mounted yet (e.g. the opening arrives during the
        // "starting" screen): keep the items; resume() once it is mounted.
        playing.current = false;
        return;
      }
      queue.current.shift();
      playing.current = true;
      el.src = next.url;
      el.currentTime = 0;
      el.play().catch((e: unknown) => {
        if ((e as Partial<DOMException>)?.name === "NotAllowedError") {
          // Autoplay blocked (iOS without a recent gesture, e.g. the opening
          // audio): do NOT drain silently. Re-queue and tell the UI, so it offers
          // a "listen" button (the tap is the gesture that unlocks it).
          queue.current.unshift(next);
          playing.current = false;
          blockedCb.current?.();
          return;
        }
        step(); // a chunk that fails for another reason is skipped
      });
    };
    step();
  }, [audioRef]);

  // Resume the pending queue. Call INSIDE a user gesture.
  const resume = useCallback(() => {
    if (!playing.current) playNext();
  }, [playNext]);

  const enqueue = useCallback(
    (url: string) => {
      queue.current.push({ kind: "url", url });
      if (!playing.current) playNext();
    },
    [playNext],
  );

  const enqueueText = useCallback(
    (text: string) => {
      queue.current.push({ kind: "text", text });
      if (!playing.current) playNext();
    },
    [playNext],
  );

  const reset = useCallback(() => {
    generation.current++;
    queue.current = [];
    playing.current = false;
    const el = audioRef.current;
    if (el) el.pause();
    if (speechSupported()) window.speechSynthesis.cancel();
  }, [audioRef]);

  // Call INSIDE a user gesture (tap on the mic) so the chunks that arrive
  // later can autoplay.
  const unlock = useCallback(() => {
    if (playing.current) return;
    if (speechRef.current?.voice && speechSupported()) {
      // Same trick for speech synthesis: iOS only speaks after a gesture.
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(""));
    }
    const el = audioRef.current;
    if (!el) return;
    el.muted = true;
    el.src = SILENT_WAV;
    el.play()
      .then(() => {
        el.pause();
        el.muted = false;
      })
      .catch(() => {
        el.muted = false;
      });
  }, [audioRef]);

  const isPlaying = useCallback(() => playing.current, []);
  const hasPending = useCallback(() => queue.current.length > 0, []);

  // Wired to the <audio> onEnded in JSX (not addEventListener, because the
  // element does not exist on mount: it is not rendered during "starting").
  const onEnded = useCallback(() => playNext(), [playNext]);

  // Call when a turn starts: the length scale the backend will use for this
  // turn's chunks. Resets playbackRate: new audio already has its scale.
  const notifyTurnLs = useCallback(
    (ls: number | null) => {
      currentLs.current = ls ?? 1.0;
      textLs.current = ls;
      const el = audioRef.current;
      if (el) el.playbackRate = 1.0;
    },
    [audioRef],
  );

  // Speed change ON THE FLY: adjust the playbackRate of the <audio> playing
  // now, without waiting for the next turn. A chunk made with currentLs heard
  // at targetLs plays at currentLs/targetLs (length scale stretches,
  // playbackRate compresses). Browser speech picks it up from the next sentence.
  const setPlaybackRate = useCallback(
    (targetLs: number | null) => {
      textLs.current = targetLs;
      const target = targetLs ?? 1.0;
      const el = audioRef.current;
      if (!el) return;
      el.playbackRate = currentLs.current / target;
    },
    [audioRef],
  );

  return {
    enqueue,
    enqueueText,
    reset,
    unlock,
    resume,
    isPlaying,
    hasPending,
    onEnded,
    notifyTurnLs,
    setPlaybackRate,
  };
}
