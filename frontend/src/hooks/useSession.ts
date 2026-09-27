import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  endSession,
  endSessionBeacon,
  sendAudioTurn,
  sendTextTurn,
  startSession,
  streamTurn,
  type Correction,
  type MinimalPair,
  type ScenarioInfo,
  type SessionConfig,
  type StreamMeta,
  type SessionEndResponse,
  type TurnResponse,
  type VocabItem,
  type WriteAction,
} from "@/lib/api";
import { t } from "@/i18n";

/** Error message readable by a non-technical learner. */
export function humanError(e: unknown): string {
  const err = e as Partial<Error> | undefined;
  if (err?.name === "TimeoutError" || err?.name === "AbortError") {
    return t("error.timeout");
  }
  if (e instanceof TypeError) return t("error.network"); // fetch: network down
  if (e instanceof ApiError) {
    // The server cannot do it at all (e.g. no word timestamps).
    if (e.code === "unsupported") return t("pron.timestamps");
    // AI service errors carry a message written for the learner.
    if (e.detail) return e.detail;
    if (e.status >= 500) return t("error.model");
    return `${t("error.generic")} (HTTP ${e.status})`;
  }
  return `${t("error.generic")}: ${err?.message ?? String(e)}`;
}

export type TurnState =
  "idle" | "starting" | "recording" | "uploading" | "thinking" | "speaking" | "error";

export interface TurnEntry {
  id: number;
  user: string;
  reply: string;
  corrections: Correction[];
  new_vocab: VocabItem[];
  suggested_followup: string;
  revised: string;
  audio_urls: string[];
}

const PENDING_ID = -1; // turn in progress while streaming (only one at a time)

function toEntry(res: TurnResponse): TurnEntry {
  return {
    id: res.turn,
    user: res.transcript,
    reply: res.reply,
    corrections: res.corrections,
    new_vocab: res.new_vocab,
    suggested_followup: res.suggested_followup,
    revised: res.revised ?? "",
    audio_urls: res.audio_url ? [res.audio_url] : [],
  };
}

function metaToEntry(meta: StreamMeta): TurnEntry {
  return {
    id: meta.turn,
    user: meta.transcript,
    reply: meta.reply,
    corrections: meta.corrections,
    new_vocab: meta.new_vocab,
    suggested_followup: meta.suggested_followup,
    revised: meta.revised ?? "",
    audio_urls: meta.audio_urls ?? [],
  };
}

interface UseSessionOpts {
  onAudioChunk?: (url: string) => void;
  /** Teacher text to speak with the browser voice (no server voice). */
  onTextChunk?: (text: string) => void;
  onStreamStart?: () => void;
  onStreamEnd?: () => void;
}

export function useSession(config: SessionConfig, opts: UseSessionOpts = {}) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<TurnEntry[]>([]);
  const [scenarioInfo, setScenarioInfo] = useState<ScenarioInfo | null>(null);
  const [referenceText, setReferenceText] = useState<string | null>(null);
  const [pairs, setPairs] = useState<MinimalPair[] | null>(null);
  const [state, setState] = useState<TurnState>("starting");
  const [error, setError] = useState<string | null>(null);
  // The session opening will arrive through streaming (defer_opening).
  const kickoffPendingRef = useRef(false);
  // Last send, for the "Retry" button of the error banner.
  const lastSendRef = useRef<
    | { kind: "text"; text: string; action: WriteAction }
    | { kind: "audio"; blob: Blob; filename: string }
    | { kind: "stream"; payload: { text?: string; audio?: Blob; filename?: string } }
    | null
  >(null);
  const startingRef = useRef(false);
  // Latest callbacks, read from async code. Declared before the start effect
  // so they are up to date when it runs.
  const cb = useRef(opts);
  const onAudioChunk = useRef<((url: string) => void) | undefined>(undefined);
  const onTextChunk = useRef<((text: string) => void) | undefined>(undefined);
  useEffect(() => {
    cb.current = opts;
    onAudioChunk.current = opts.onAudioChunk;
    onTextChunk.current = opts.onTextChunk;
  });

  useEffect(() => {
    if (startingRef.current) return;
    startingRef.current = true;
    let cancelled = false;
    (async () => {
      try {
        const res = await startSession(config);
        if (cancelled) return;
        setSessionId(res.session_id);
        setScenarioInfo(res.scenario_info);
        setReferenceText(res.reference_text ?? null);
        setPairs(res.pairs ?? null);
        if (res.opening_pending) {
          // The opening arrives through streaming (kickoff): first audio ~2s.
          // The stream drives the state: thinking, speaking, idle.
          kickoffPendingRef.current = true;
          return;
        }
        if (res.opening) {
          const entry = toEntry(res.opening);
          setTurns([entry]);
          if (entry.audio_urls.length > 0) {
            setState("speaking");
            entry.audio_urls.forEach((u) => onAudioChunk.current?.(u));
          } else if (onTextChunk.current && entry.reply) {
            setState("speaking");
            onTextChunk.current(entry.reply);
          } else {
            setState("idle");
          }
        } else {
          setState("idle");
        }
      } catch (e) {
        if (!cancelled) {
          // "error" as a state only when the start failed: there is no session
          // to keep. Turn failures are recoverable (see sendText etc.).
          setError(humanError(e));
          setState("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // config is stable (remount by key); changes do not restart the session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Clean close on unmount (or when the tab closes).
  const finishedRef = useRef(false);
  useEffect(() => {
    if (!sessionId) return;
    const close = () => {
      if (!finishedRef.current) endSessionBeacon(sessionId);
    };
    window.addEventListener("pagehide", close);
    return () => {
      window.removeEventListener("pagehide", close);
      if (!finishedRef.current) void endSession(sessionId).catch(() => undefined);
    };
  }, [sessionId]);

  /** Explicit close ("End session"): returns the post-session report.
   * After this, the unmount cleanup does not close again. */
  const finish = useCallback(
    async (endPage?: number): Promise<SessionEndResponse | null> => {
      if (!sessionId || finishedRef.current) return null;
      finishedRef.current = true;
      try {
        return await endSession(sessionId, endPage);
      } catch {
        return null; // the summary is best-effort; the session is closed anyway
      }
    },
    [sessionId],
  );

  // --- Blocking path (fallback + mode 5 writing) --------------------------
  const appendTurn = useCallback((res: TurnResponse) => {
    setTurns((prev) => [...prev, toEntry(res)]);
  }, []);

  const sendText = useCallback(
    async (text: string, action: WriteAction = "talk"): Promise<TurnResponse | null> => {
      if (!sessionId || !text.trim()) return null;
      lastSendRef.current = { kind: "text", text, action };
      setError(null);
      setState("thinking");
      try {
        const res = await sendTextTurn(sessionId, text.trim(), action);
        appendTurn(res);
        setState(res.audio_url ? "speaking" : "idle");
        return res;
      } catch (e) {
        // Recoverable: the session is still alive, the view stays mounted.
        setError(humanError(e));
        setState("idle");
        return null;
      }
    },
    [sessionId, appendTurn],
  );

  const sendAudio = useCallback(
    async (blob: Blob, filename = "turn.webm"): Promise<TurnResponse | null> => {
      if (!sessionId) return null;
      lastSendRef.current = { kind: "audio", blob, filename };
      setError(null);
      setState("thinking");
      try {
        const res = await sendAudioTurn(sessionId, blob, filename);
        appendTurn(res);
        setState(res.audio_url ? "speaking" : "idle");
        return res;
      } catch (e) {
        setError(humanError(e));
        setState("idle");
        return null;
      }
    },
    [sessionId, appendTurn],
  );

  // --- Streaming path (conversational modes) ------------------------------
  // Turn generation: cancelStream() bumps it so the events of a cancelled
  // stream (barge-in) do not overwrite the state of the new turn.
  const streamGenRef = useRef(0);
  const streamAbortRef = useRef<AbortController | null>(null);

  const runStreamFor = useCallback(
    async (
      sid: string,
      payload: { text?: string; audio?: Blob; filename?: string; kickoff?: boolean },
    ) => {
      lastSendRef.current = { kind: "stream", payload };
      const gen = ++streamGenRef.current;
      const ac = new AbortController();
      streamAbortRef.current = ac;
      const live = () => streamGenRef.current === gen;
      setError(null);
      setState("thinking");
      cb.current.onStreamStart?.();
      try {
        await streamTurn(
          sid,
          payload,
          {
            onTranscript: (text) => {
              if (!live()) return;
              // Leave "starting" as soon as the stream begins: the loading
              // screen gives way to CallView/ChatView, where "thinking" has
              // finer feedback (the opening is already on its way).
              setState((s) => (s === "starting" ? "thinking" : s));
              setTurns((prev) => [
                ...prev,
                {
                  id: PENDING_ID,
                  user: text,
                  reply: "",
                  corrections: [],
                  new_vocab: [],
                  suggested_followup: "",
                  revised: "",
                  audio_urls: [],
                },
              ]);
            },
            onAudio: (url, text) => {
              if (!live()) return;
              if (url) onAudioChunk.current?.(url);
              else if (text) onTextChunk.current?.(text);
              setState("speaking");
              setTurns((prev) =>
                prev.map((t) =>
                  t.id === PENDING_ID
                    ? {
                        ...t,
                        reply: t.reply ? `${t.reply} ${text}` : text,
                        audio_urls: url ? [...t.audio_urls, url] : t.audio_urls,
                      }
                    : t,
                ),
              );
            },
            onMeta: (meta) => {
              if (!live()) return;
              // Replace the assembled reply with the canonical one (correct spacing).
              setTurns((prev) => prev.map((t) => (t.id === PENDING_ID ? metaToEntry(meta) : t)));
            },
            onError: (err) => {
              if (!live()) return;
              setError(
                err.code === "unsupported" ? t("pron.timestamps") : err.detail || t("error.model"),
              );
              setState("idle");
              setTurns((prev) => prev.filter((t) => t.id !== PENDING_ID));
            },
            // onDone: the state goes back to "idle" when the audio queue drains.
          },
          { signal: ac.signal },
        );
      } catch (e) {
        if (!live()) return;
        setError(humanError(e));
        setState("idle");
        setTurns((prev) => prev.filter((t) => t.id !== PENDING_ID));
      } finally {
        if (live()) cb.current.onStreamEnd?.();
      }
    },
    [],
  );

  const runStream = useCallback(
    (payload: { text?: string; audio?: Blob; filename?: string; kickoff?: boolean }) => {
      if (!sessionId) return Promise.resolve();
      return runStreamFor(sessionId, payload);
    },
    [sessionId, runStreamFor],
  );

  // Trigger the streamed opening when /session/start leaves it pending.
  useEffect(() => {
    if (sessionId && kickoffPendingRef.current) {
      kickoffPendingRef.current = false;
      void runStreamFor(sessionId, { kickoff: true });
    }
  }, [sessionId, runStreamFor]);

  /** Barge-in: cut the running stream and invalidate its pending events.
   * The partial turn stays in the thread (the backend keeps what was said). */
  const cancelStream = useCallback(() => {
    streamGenRef.current++;
    streamAbortRef.current?.abort();
    setTurns((prev) =>
      prev.map((t) =>
        // Freeze the partial turn with a unique (negative) id so the next
        // turn's PENDING entry does not overwrite it.
        t.id === PENDING_ID ? { ...t, id: -(prev.length + 2) } : t,
      ),
    );
  }, []);

  /** Retry the last failed send (error banner). */
  const retry = useCallback(() => {
    const p = lastSendRef.current;
    if (!p) return;
    if (p.kind === "text") void sendText(p.text, p.action);
    else if (p.kind === "audio") void sendAudio(p.blob, p.filename);
    else void runStream(p.payload);
  }, [sendText, sendAudio, runStream]);

  const sendTextStream = useCallback(
    (text: string) => runStream({ text: text.trim() }),
    [runStream],
  );

  const sendAudioStream = useCallback(
    (blob: Blob, filename = "turn.webm") => runStream({ audio: blob, filename }),
    [runStream],
  );

  /** Mode 8: comprehension opening, triggered by the UI after the reading. */
  const startKickoff = useCallback(() => runStream({ kickoff: true }), [runStream]);

  return {
    sessionId,
    turns,
    scenarioInfo,
    referenceText,
    pairs,
    state,
    error,
    sendText,
    sendAudio,
    sendTextStream,
    sendAudioStream,
    startKickoff,
    cancelStream,
    retry,
    finish,
    setState,
  };
}
