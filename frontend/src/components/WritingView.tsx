import { useRef, useState } from "react";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { audioUrl, type Correction, type SubMode } from "@/lib/api";
import type { useSession } from "@/hooks/useSession";
import type { TeacherVoice } from "@/hooks/useTeacherVoice";
import { speakNow } from "@/lib/browserVoice";
import { getRate } from "@/lib/storage";
import { t } from "@/i18n";

interface ThreadMsg {
  role: "user" | "colleague";
  text: string;
  audio_url?: string | null;
}

interface Feedback {
  reply: string;
  corrections: Correction[];
  revised: string;
}

export function WritingView({
  session,
  subMode,
  voice,
  user,
}: {
  session: ReturnType<typeof useSession>;
  user: string;
  subMode: SubMode;
  voice: TeacherVoice;
}) {
  const { state, sendText } = session;
  const [draft, setDraft] = useState("");
  const [thread, setThread] = useState<ThreadMsg[]>([]);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const busy = state === "thinking";

  const askFeedback = async () => {
    if (!draft.trim()) return;
    const res = await sendText(draft.trim(), "feedback");
    if (res) {
      setFeedback({
        reply: res.reply,
        corrections: res.corrections,
        revised: res.revised ?? "",
      });
    }
  };

  const sendToColleague = async () => {
    if (!draft.trim()) return;
    const sent = draft.trim();
    const res = await sendText(sent, "send");
    if (res) {
      setThread((prev) => [
        ...prev,
        { role: "user", text: sent },
        { role: "colleague", text: res.reply, audio_url: res.audio_url },
      ]);
      setFeedback(null);
      setDraft("");
    }
  };

  // Server audio when there is some; otherwise the on-device voice, if any.
  const canListen = (m: ThreadMsg) => Boolean(m.audio_url) || voice.source === "browser";

  const play = (m: ThreadMsg) => {
    const src = audioUrl(m.audio_url ?? null);
    if (!src) {
      if (voice.browserVoice) speakNow(m.text, voice.browserVoice, getRate(user));
      return;
    }
    if (!audioRef.current) return;
    audioRef.current.src = src;
    audioRef.current.currentTime = 0;
    void audioRef.current.play();
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6">
      <section className="space-y-4">
        {/* Hilo */}
        <Card className="p-4 min-h-[20vh]">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-3">
            {t(`write.thread.${subMode}`)}
          </h3>
          {thread.length === 0 ? (
            <p className="text-sm text-ink-400">{t("write.thread.empty")}</p>
          ) : (
            <div className="space-y-3">
              {thread.map((m, i) => (
                <div key={i} className="text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">
                      {m.role === "user" ? t("write.you") : t("write.colleague")}
                    </span>
                    {m.role === "colleague" && canListen(m) && (
                      <button
                        onClick={() => play(m)}
                        className="text-xs text-accent-600 hover:underline"
                      >
                        {t("write.listen")}
                      </button>
                    )}
                  </div>
                  <p className="whitespace-pre-wrap text-ink-800 dark:text-ink-100 mt-0.5">
                    {m.text}
                  </p>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Editor */}
        <Card className="p-4 space-y-3">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={8}
            placeholder={t(`write.placeholder.${subMode}`)}
            className="w-full resize-y rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={askFeedback} disabled={busy || !draft.trim()}>
              {t("write.feedback")}
            </Button>
            <Button onClick={sendToColleague} disabled={busy || !draft.trim()}>
              {t("write.send")}
            </Button>
            {busy && <span className="text-sm text-ink-400">{t("call.thinking")}</span>}
          </div>
        </Card>
      </section>

      {/* Panel feedback */}
      <aside className="lg:sticky lg:top-32 self-start w-full">
        {feedback ? (
          <div className="space-y-3">
            <Card className="p-4">
              <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
                {t("write.feedback.title")}
              </h3>
              <p className="text-sm">{feedback.reply}</p>
            </Card>

            {feedback.corrections.length > 0 && (
              <Card className="p-4">
                <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
                  {t("talk.corrections")}
                </h3>
                <ul className="space-y-2">
                  {feedback.corrections.map((c, i) => (
                    <li key={i} className="text-sm">
                      <span className="line-through text-red-500/80">{c.original}</span> →{" "}
                      <span className="text-green-700 dark:text-green-400 font-medium">
                        {c.corrected}
                      </span>
                      {c.note && <p className="text-xs text-ink-500 mt-0.5">{c.note}</p>}
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            {feedback.revised && (
              <Card className="p-4">
                <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
                  {t("write.revised")}
                </h3>
                <p className="text-sm whitespace-pre-wrap text-ink-800 dark:text-ink-100">
                  {feedback.revised}
                </p>
                <button
                  onClick={() => setDraft(feedback.revised)}
                  className="text-xs text-accent-600 hover:underline mt-2"
                >
                  {t("write.useRevised")}
                </button>
              </Card>
            )}
          </div>
        ) : (
          <Card className="p-4 text-sm text-ink-500">{t("write.feedback.empty")}</Card>
        )}
      </aside>

      <audio ref={audioRef} hidden />
    </div>
  );
}
