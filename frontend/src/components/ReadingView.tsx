import { useMemo, useRef, useState } from "react";
import { Card } from "@/components/Card";
import { MicButton } from "@/components/MicButton";
import { useRecorder } from "@/hooks/useRecorder";
import { audioUrl, scoreReading, type ReadScoreResponse, type WordStatus } from "@/lib/api";
import { humanError, type useSession } from "@/hooks/useSession";
import { t } from "@/i18n";
import { cn } from "@/lib/cn";

const STATUS_CLASS: Record<WordStatus, string> = {
  ok: "text-ink-800 dark:text-ink-100",
  weak: "text-amber-600 dark:text-amber-400 underline decoration-dotted underline-offset-4 cursor-pointer",
  miss: "text-red-600 dark:text-red-400 underline decoration-wavy underline-offset-4 cursor-pointer",
};

export function ReadingView({ session }: { session: ReturnType<typeof useSession> }) {
  const { sessionId, referenceText } = session;
  const recorder = useRecorder();
  const [result, setResult] = useState<ReadScoreResponse | null>(null);
  const [scoring, setScoring] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Word -> reference audio (tap to listen).
  const audioByWord = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of result?.flagged ?? []) {
      if (f.audio_url) m.set(f.word, f.audio_url);
    }
    return m;
  }, [result]);

  const play = (word: string) => {
    const src = audioUrl(audioByWord.get(word) ?? null);
    if (!src || !audioRef.current) return;
    audioRef.current.src = src;
    audioRef.current.currentTime = 0;
    void audioRef.current.play();
  };

  const onMic = async () => {
    if (recorder.state === "recording") {
      const rec = await recorder.stop();
      if (rec.blob.size === 0 || !sessionId) return;
      setScoring(true);
      setErr(null);
      try {
        const res = await scoreReading(sessionId, rec.blob, rec.filename);
        setResult(res);
      } catch (e) {
        setErr(humanError(e));
      } finally {
        setScoring(false);
      }
    } else {
      setResult(null);
      await recorder.start();
    }
  };

  const micState: "idle" | "recording" | "busy" =
    recorder.state === "recording" ? "recording" : scoring ? "busy" : "idle";

  const summary = result?.summary;

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      {/* Text to read (colored after scoring) */}
      <Card className="p-5">
        <p className="text-lg leading-relaxed">
          {result ? (
            result.words.map((w, i) => {
              const clickable = w.status !== "ok" && audioByWord.has(w.text);
              return (
                <span key={i}>
                  <span
                    className={cn(STATUS_CLASS[w.status])}
                    onClick={clickable ? () => play(w.text) : undefined}
                    title={clickable ? t("read.listen") : undefined}
                  >
                    {w.text}
                  </span>{" "}
                </span>
              );
            })
          ) : (
            <span className="text-ink-800 dark:text-ink-100">{referenceText}</span>
          )}
        </p>
      </Card>

      {/* Recording control */}
      <div className="flex flex-col items-center gap-3">
        <MicButton
          state={micState}
          onClick={onMic}
          disabled={micState === "busy"}
          labelIdle={result ? t("read.again") : t("read.record")}
          labelRecording={t("read.recording")}
          labelBusy={t("read.scoring")}
        />
        {!result && !scoring && (
          <p className="text-sm text-ink-500 text-center">{t("read.instructions")}</p>
        )}
        {recorder.error && (
          <Card className="p-4 max-w-md">
            <h3 className="font-medium mb-1">{t("call.permission.title")}</h3>
            <p className="text-sm text-ink-500">{t("call.permission.body")}</p>
          </Card>
        )}
        {err && <p className="text-sm text-red-600">{err}</p>}
      </div>

      {/* Result */}
      {summary && (
        <Card className="p-5 space-y-4">
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-bold text-ink-900 dark:text-ink-50">
              {summary.accuracy}%
            </span>
            <span className="text-sm text-ink-500">
              {t("read.accuracy")} · {summary.ok}/{summary.total}
            </span>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-4 text-xs">
            <span className="text-ink-800 dark:text-ink-100">● {t("read.legend.ok")}</span>
            <span className="text-amber-600 dark:text-amber-400">● {t("read.legend.weak")}</span>
            <span className="text-red-600 dark:text-red-400">● {t("read.legend.miss")}</span>
          </div>

          {/* Words to review */}
          <div>
            <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
              {t("read.flagged.title")}
            </h3>
            {result && result.flagged.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {result.flagged.map((f, i) => (
                  <button
                    key={i}
                    onClick={() => play(f.word)}
                    disabled={!f.audio_url}
                    className="inline-flex items-center gap-1 rounded-full border border-ink-200 dark:border-ink-700 px-3 py-1 text-sm hover:border-accent-400 disabled:opacity-50"
                  >
                    {f.word}
                    {f.audio_url && <span className="text-xs text-accent-600">♪</span>}
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-sm text-green-700 dark:text-green-400">
                {t("read.flagged.empty")}
              </p>
            )}
          </div>

          <p className="text-xs text-ink-400">{t("read.disclaimer")}</p>
        </Card>
      )}

      <audio ref={audioRef} hidden />
    </div>
  );
}
