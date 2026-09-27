import { useRef, useState } from "react";
import { Card } from "@/components/Card";
import { MicButton } from "@/components/MicButton";
import { useRecorder } from "@/hooks/useRecorder";
import { audioUrl, scorePair, type MinimalPair, type PairVerdict } from "@/lib/api";
import { humanError, type useSession } from "@/hooks/useSession";
import { t } from "@/i18n";
import { cn } from "@/lib/cn";

/** Minimal pairs exercise: listen, read the pair aloud, get a verdict. */
export function PairsView({ session }: { session: ReturnType<typeof useSession> }) {
  const { sessionId, pairs } = session;
  const recorder = useRecorder();
  const [idx, setIdx] = useState(0);
  const [verdicts, setVerdicts] = useState<(PairVerdict | null)[]>(() =>
    (pairs ?? []).map(() => null),
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  if (!pairs || pairs.length === 0) {
    return <p className="text-sm text-ink-500 text-center py-10">{t("pairs.empty")}</p>;
  }
  const done = idx >= pairs.length;
  const pair: MinimalPair | undefined = pairs[idx];
  const verdict = done ? null : verdicts[idx];

  const play = (url: string | null) => {
    const src = audioUrl(url);
    if (!src || !audioRef.current) return;
    audioRef.current.src = src;
    void audioRef.current.play();
  };

  const onMic = async () => {
    if (recorder.state === "recording") {
      const rec = await recorder.stop();
      if (rec.blob.size === 0 || !sessionId) return;
      setBusy(true);
      setErr(null);
      try {
        const v = await scorePair(sessionId, idx, rec.blob, rec.filename);
        setVerdicts((prev) => prev.map((p, i) => (i === idx ? v : p)));
      } catch (e) {
        setErr(humanError(e));
      } finally {
        setBusy(false);
      }
    } else {
      setErr(null);
      await recorder.start();
    }
  };

  if (done) {
    const practiced = verdicts.filter((v) => v != null).length;
    // Speech recognizers are unreliable with isolated words: for review we list
    // EVERYTHING that was not "distinguished" (same + unclear), with its tip.
    const failed = pairs.filter((_, i) => verdicts[i] && verdicts[i]!.status !== "ok");
    return (
      <div className="max-w-2xl mx-auto space-y-4">
        <Card className="p-5 text-center space-y-2">
          <p className="text-3xl font-bold text-ink-900 dark:text-ink-50">
            {practiced}/{pairs.length}
          </p>
          <p className="text-sm text-ink-500">{t("pairs.summary")}</p>
        </Card>
        {failed.length > 0 && (
          <Card className="p-4 space-y-2">
            <h3 className="text-xs uppercase tracking-wider text-ink-400">{t("pairs.toWork")}</h3>
            {failed.map((p, i) => (
              <p key={i} className="text-sm">
                <span className="font-medium">{p.words.join(" / ")}</span>
                <span className="text-ink-500"> · {p.tip}</span>
              </p>
            ))}
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-5">
      <p className="text-xs text-ink-400 text-center">
        {idx + 1} / {pairs.length} · {pair.contrast}
      </p>
      {idx === 0 && (
        <p className="text-xs text-ink-500 text-center px-2">{t("pairs.disclaimer")}</p>
      )}
      <Card className="p-6 space-y-4">
        <div className="grid grid-cols-2 gap-4 text-center">
          {pair.words.map((w, i) => (
            <button
              key={i}
              onClick={() => play(pair.audio_urls[i])}
              className="rounded-xl border border-ink-200 dark:border-ink-700 py-4 hover:border-accent-400"
            >
              <p className="text-2xl font-semibold text-ink-900 dark:text-ink-50">{w} ♪</p>
            </button>
          ))}
        </div>
        <p className="text-sm text-ink-500 text-center">{pair.gloss}</p>
        <p className="text-sm text-ink-600 dark:text-ink-300 text-center">💡 {pair.tip}</p>
      </Card>

      <div className="flex flex-col items-center gap-3">
        {!verdict ? (
          <>
            <MicButton
              state={recorder.state === "recording" ? "recording" : busy ? "busy" : "idle"}
              onClick={onMic}
              disabled={busy}
              labelIdle={t("pairs.record")}
              labelRecording={t("pairs.recording")}
              labelBusy={t("pairs.scoring")}
            />
            {err && <p className="text-sm text-red-600">{err}</p>}
          </>
        ) : (
          <div className="text-center space-y-3">
            <p
              className={cn(
                "text-base font-medium",
                verdict.status === "ok"
                  ? "text-green-700 dark:text-green-400"
                  : verdict.status === "same"
                    ? "text-amber-600 dark:text-amber-400"
                    : "text-ink-500",
              )}
            >
              {verdict.status === "ok"
                ? t("pairs.ok")
                : verdict.status === "same"
                  ? t("pairs.same")
                  : t("pairs.unclear")}
            </p>
            {verdict.heard.length > 0 && (
              <p className="text-xs text-ink-400">
                {t("pairs.heard")} {verdict.heard.join(", ")}
              </p>
            )}
            <p className="text-sm text-ink-600 dark:text-ink-300">💡 {pair.tip}</p>
            <div className="flex justify-center gap-3">
              <button
                onClick={() => setVerdicts((prev) => prev.map((p, i) => (i === idx ? null : p)))}
                className="rounded-xl border border-ink-200 dark:border-ink-700 px-4 py-2 text-sm"
              >
                {t("pairs.retry")}
              </button>
              <button
                onClick={() => setIdx((i) => i + 1)}
                className="rounded-xl bg-accent-600 px-4 py-2 text-sm text-white"
              >
                {t("pairs.next")}
              </button>
            </div>
          </div>
        )}
      </div>
      <audio ref={audioRef} hidden />
    </div>
  );
}
