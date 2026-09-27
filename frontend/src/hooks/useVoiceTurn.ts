import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/hooks/useSession";
import { useAudioQueue } from "@/hooks/useAudioQueue";
import { useRecorder } from "@/hooks/useRecorder";
import { useTeacherVoice } from "@/hooks/useTeacherVoice";
import type { SessionConfig } from "@/lib/api";
import { getRate } from "@/lib/storage";
import { onRateChange } from "@/lib/rate-events";
import { t } from "@/i18n";

export type MicState = "idle" | "recording" | "busy";

/**
 * Orchestrates a spoken turn: session + audio queue + recorder + barge-in.
 * The turn goes back to "idle" only when the stream finished AND the queue
 * drained (avoids flicker when a sentence ends before the next one arrives).
 * Tapping the mic while the teacher speaks interrupts her: it clears the
 * queue, aborts the running stream (its events are invalidated by generation
 * in useSession) and starts recording.
 *
 * Without a server voice for the language, the teacher's sentences are spoken
 * by an on-device browser voice, or not spoken at all if there is none.
 */
export function useVoiceTurn(config: SessionConfig) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const recorder = useRecorder();
  const voice = useTeacherVoice(config.user, config.lang);
  const browserMode = voice.source !== "server";
  const sessionRef = useRef<ReturnType<typeof useSession> | null>(null);
  const streamDone = useRef(true);
  // Opening audio blocked by iOS (no recent gesture): the UI offers a
  // "listen" button instead of draining the queue silently.
  const [audioBlocked, setAudioBlocked] = useState(false);

  const queue = useAudioQueue(
    audioRef,
    () => {
      if (streamDone.current) {
        sessionRef.current?.setState((s) => (s === "speaking" ? "idle" : s));
      }
    },
    () => setAudioBlocked(true),
    { voice: voice.browserVoice, lang: config.lang },
  );

  const session = useSession(config, {
    onAudioChunk: queue.enqueue,
    // Only in browser mode: when a server voice exists, a missing URL means one
    // sentence failed to synthesize, and mixing two voices would be worse.
    onTextChunk: browserMode ? queue.enqueueText : undefined,
    onStreamStart: () => {
      streamDone.current = false;
      // Length scale the backend will apply to this turn's chunks. Needed so
      // setPlaybackRate() (on-the-fly toggle) computes the right ratio.
      queue.notifyTurnLs(getRate(config.user));
    },
    onStreamEnd: () => {
      streamDone.current = true;
      if (!queue.isPlaying()) {
        // Functional update: do not overwrite "recording" after a barge-in.
        sessionRef.current?.setState((s) => (s === "speaking" || s === "thinking" ? "idle" : s));
      }
    },
  });
  useEffect(() => {
    sessionRef.current = session;
  });

  // The opening can arrive while the "starting" screen is mounted, with no
  // <audio> in the DOM, and the queue would wait forever. When the state turns
  // "speaking" the view with the <audio> is mounted: restart the queue. If the
  // browser blocks autoplay (iOS without a recent gesture), onBlocked fires and
  // the UI offers "Listen".
  useEffect(() => {
    if (session.state === "speaking" && queue.hasPending() && !queue.isPlaying()) {
      queue.resume();
    }
  }, [session.state, queue]);

  const interruptible = session.state === "speaking";

  const onMic = useCallback(async () => {
    queue.unlock(); // enable autoplay of the chunks inside the gesture (iOS)
    setAudioBlocked(false);
    if (recorder.state === "recording") {
      const rec = await recorder.stop();
      if (rec.blob.size > 0) await session.sendAudioStream(rec.blob, rec.filename);
    } else if (session.state === "idle" || session.state === "speaking") {
      if (session.state === "speaking" || !streamDone.current) {
        // Barge-in: cut the audio and the stream before recording.
        queue.reset();
        session.cancelStream();
      }
      await recorder.start();
      session.setState("recording");
    }
  }, [queue, recorder, session]);

  const sendText = useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      queue.unlock(); // gesture: the click on Send
      setAudioBlocked(false);
      await session.sendTextStream(text.trim());
    },
    [queue, session],
  );

  // Tap on "listen" when iOS blocked autoplay: the gesture resumes the queue.
  const resumeAudio = useCallback(() => {
    setAudioBlocked(false);
    queue.resume();
  }, [queue]);

  const lastTurn = session.turns.length > 0 ? session.turns[session.turns.length - 1] : null;
  const canReplay = Boolean(
    lastTurn &&
    (lastTurn.audio_urls.length > 0 ||
      (browserMode && voice.browserVoice && lastTurn.reply.trim())),
  );

  const replay = useCallback(() => {
    const turns = session.turns;
    const last = turns.length > 0 ? turns[turns.length - 1] : null;
    if (!last) return;
    queue.reset();
    setAudioBlocked(false);
    if (last.audio_urls.length > 0) last.audio_urls.forEach((u) => queue.enqueue(u));
    else if (browserMode && last.reply.trim()) queue.enqueueText(last.reply);
  }, [queue, session.turns, browserMode]);

  // On-the-fly speed: apply playbackRate to the <audio> playing now. The
  // header toggle emits the event through rate-events; subscribing here avoids
  // lifting state (RateToggle lives in the header, the audio in ActiveSession).
  const setPlaybackRate = queue.setPlaybackRate;
  useEffect(() => {
    return onRateChange((ls) => setPlaybackRate(ls));
  }, [setPlaybackRate]);

  const micState: MicState =
    recorder.state === "recording"
      ? "recording"
      : session.state === "thinking" || session.state === "uploading"
        ? "busy"
        : "idle"; // "speaking" can be tapped: barge-in

  const micLabel = interruptible
    ? t("call.interrupt")
    : session.state === "thinking" || session.state === "uploading"
      ? t("call.thinking")
      : t("call.idle");

  return {
    session,
    recorder,
    audioRef,
    queue,
    voice,
    micState,
    micLabel,
    audioBlocked,
    canReplay,
    onMic,
    sendText,
    resumeAudio,
    replay,
  };
}
