import { useEffect, useState } from "react";
import { Button } from "@/components/Button";
import {
  createStory,
  fetchStories,
  fetchSyllabus,
  nextChapter,
  type Lang,
  type LessonMode,
  type Scenario,
  type SessionConfig,
  type StoryMeta,
  type SubMode,
  type SyllabusData,
  type TopicStatus,
} from "@/lib/api";
import { humanError } from "@/hooks/useSession";
import { ScenarioPicker } from "@/components/ScenarioPicker";
import { ExpressionsPicker } from "@/components/ExpressionsPicker";
import { VoicePicker } from "@/components/VoicePicker";
import { PhotoOcr } from "@/components/PhotoOcr";
import { Notice } from "@/components/Notice";
import { useCapabilities } from "@/lib/capabilities";
import { LS_USER } from "@/lib/storage";
import { t } from "@/i18n";
import { cn } from "@/lib/cn";

// Cap on the pasted text of mode 3 (mirrors the backend's READING_MAX_CHARS).
const READING_MAX = 6000;

/** Configuration screen before starting a session, one per mode. */
export function SetupPanel({
  mode,
  lang,
  onStart,
}: {
  mode: LessonMode;
  lang: Lang;
  onStart: (cfg: SessionConfig, meta?: Scenario | null) => void;
}) {
  const user = localStorage.getItem(LS_USER)!;
  const base = { user, lang } as const;

  const content = (() => {
    if (mode === 1) {
      return (
        <SetupShell title={t("mode.1")} desc={t("setup.1.desc")}>
          <Button size="lg" onClick={() => onStart({ ...base, mode: 1 })}>
            {t("setup.start")}
          </Button>
        </SetupShell>
      );
    }
    if (mode === 2) {
      return (
        <SetupShell title={t("mode.2")} desc={t("setup.2.desc")}>
          <ScenarioPicker onPick={(s) => onStart({ ...base, mode: 2, scenario: s.id }, s)} />
        </SetupShell>
      );
    }
    if (mode === 3) return <SetupReading base={base} onStart={onStart} />;
    if (mode === 4) return <SetupReadAloud base={base} onStart={onStart} />;
    if (mode === 7) {
      return (
        <SetupShell title={t("mode.7")} desc={t("setup.7.desc")}>
          <ExpressionsPicker onPick={(topic) => onStart({ ...base, mode: 7, topic })} />
        </SetupShell>
      );
    }
    if (mode === 9) return <SetupLesson base={base} onStart={onStart} />;
    return <SetupWriting base={base} onStart={onStart} />; // mode === 5
  })();

  return (
    <div className="space-y-5">
      {content}
      {/* The voice is picked before starting (applies to the whole session). */}
      <div className="max-w-2xl mx-auto pt-4 border-t border-ink-100 dark:border-ink-800">
        <VoicePicker user={user} lang={lang} />
      </div>
    </div>
  );
}

function SetupShell({
  title,
  desc,
  children,
}: {
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-ink-900 dark:text-ink-50">{title}</h2>
        <p className="text-sm text-ink-500 mt-1">{desc}</p>
      </div>
      {children}
    </div>
  );
}

type ReadingSource = "paste" | "story" | "photo";

function SetupReading({
  base,
  onStart,
}: {
  base: { user: string; lang: Lang };
  onStart: (cfg: SessionConfig) => void;
}) {
  const { caps } = useCapabilities();
  const [source, setSource] = useState<ReadingSource>("paste");
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const over = text.length > READING_MAX;
  // The page photo needs a vision model: without one the option is hidden.
  const sources: ReadingSource[] = caps.vision ? ["paste", "story", "photo"] : ["paste", "story"];
  const toggle = (
    <>
      <SourceToggle sources={sources} source={source} setSource={setSource} />
      {!caps.vision && <Notice>{t("notice.noVision")}</Notice>}
    </>
  );

  if (source === "story") {
    return (
      <SetupShell title={t("mode.3")} desc={t("setup.3.story.desc")}>
        {toggle}
        <StoryPicker base={base} onStart={onStart} />
      </SetupShell>
    );
  }

  if (source === "photo" && caps.vision && !text) {
    return (
      <SetupShell title={t("mode.3")} desc={t("ocr.desc")}>
        {toggle}
        <PhotoOcr user={base.user} lang={base.lang} onText={(txt) => setText(txt)} />
      </SetupShell>
    );
  }

  return (
    <SetupShell title={t("mode.3")} desc={source === "photo" ? t("ocr.review") : t("setup.3.desc")}>
      {toggle}
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t("setup.3.title")}
        className="w-full rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
      />
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={12}
        placeholder={t("setup.3.placeholder")}
        className="w-full resize-y rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
      />
      <div className="flex items-center justify-between">
        <span className={cn("text-xs", over ? "text-red-600" : "text-ink-400")}>
          {text.length} / {READING_MAX}
          {over && ` · ${t("setup.3.over")}`}
        </span>
        <Button
          size="lg"
          disabled={!text.trim() || over}
          onClick={() =>
            onStart({
              ...base,
              mode: 3,
              context: text.trim(),
              subject: title.trim() || undefined,
            })
          }
        >
          {t("setup.start")}
        </Button>
      </div>
    </SetupShell>
  );
}

function SourceToggle({
  sources,
  source,
  setSource,
}: {
  sources: ReadingSource[];
  source: ReadingSource;
  setSource: (s: ReadingSource) => void;
}) {
  const labels = {
    paste: "setup.3.source.paste",
    story: "setup.3.source.story",
    photo: "setup.3.source.photo",
  } as const;
  return (
    <div className="inline-flex rounded-xl bg-ink-100 dark:bg-ink-800 p-1">
      {sources.map((s) => (
        <button
          key={s}
          onClick={() => setSource(s)}
          className={cn(
            "px-3 py-1.5 rounded-lg text-sm font-medium",
            source === s ? "bg-white shadow text-ink-900" : "text-ink-600 dark:text-ink-300",
          )}
        >
          {t(labels[s])}
        </button>
      ))}
    </div>
  );
}

/** Chaptered stories at the learner's level (graded reader): continue one or
 * start a new one; the chapter becomes the text of a normal guided reading
 * session. */
function StoryPicker({
  base,
  onStart,
}: {
  base: { user: string; lang: Lang };
  onStart: (cfg: SessionConfig) => void;
}) {
  const [stories, setStories] = useState<StoryMeta[] | null>(null);
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchStories(base.user, base.lang)
      .then((s) => !cancelled && setStories(s))
      .catch(() => !cancelled && setStories([]));
    return () => {
      cancelled = true;
    };
  }, [base.user, base.lang]);

  const startChapter = (title: string, chapter: number, text: string) => {
    onStart({
      ...base,
      mode: 3,
      context: text,
      subject: `${title} · ${t("setup.3.story.chapter")} ${chapter}`,
    });
  };

  const onNew = async () => {
    setErr(null);
    setBusy("new");
    try {
      const s = await createStory(base.user, base.lang, topic.trim() || undefined);
      startChapter(s.title, s.chapter, s.text);
    } catch (e) {
      setErr(humanError(e));
      setBusy(null);
    }
  };

  const onContinue = async (meta: StoryMeta) => {
    setErr(null);
    setBusy(meta.slug);
    try {
      const s = await nextChapter(base.user, base.lang, meta.slug);
      startChapter(meta.title, s.chapter, s.text);
    } catch (e) {
      setErr(humanError(e));
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      {err && <p className="text-sm text-red-600">{err}</p>}
      {stories === null ? (
        <p className="text-sm text-ink-400">{t("scenario.loading")}</p>
      ) : (
        stories.length > 0 && (
          <div className="space-y-2">
            {stories.map((s) => (
              <div
                key={s.slug}
                className="flex items-center justify-between gap-3 rounded-xl border border-ink-200 dark:border-ink-700 px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-ink-900 dark:text-ink-50">{s.title}</p>
                  <p className="text-xs text-ink-500">
                    {s.level} · {s.chapters} {t("setup.3.story.chapters")}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy !== null}
                  onClick={() => onContinue(s)}
                >
                  {busy === s.slug ? t("setup.3.story.writing") : t("setup.3.story.continue")}
                </Button>
              </div>
            ))}
          </div>
        )
      )}
      <div className="space-y-2 pt-2">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder={t("setup.3.story.topic")}
          className="w-full rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
        />
        <Button size="lg" disabled={busy !== null} onClick={onNew}>
          {busy === "new" ? t("setup.3.story.writing") : t("setup.3.story.new")}
        </Button>
        <p className="text-xs text-ink-400">{t("setup.3.story.hint")}</p>
      </div>
    </div>
  );
}

type ReadAloudSource = "paste" | "generate" | "photo" | "pairs";

function SetupReadAloud({
  base,
  onStart,
}: {
  base: { user: string; lang: Lang };
  onStart: (cfg: SessionConfig) => void;
}) {
  const { caps } = useCapabilities();
  const [source, setSource] = useState<ReadAloudSource>("paste");
  const [text, setText] = useState("");
  const [topic, setTopic] = useState("");
  const canStart =
    source === "pairs" ? true : source === "generate" ? !!topic.trim() : !!text.trim();
  const labels = {
    paste: "setup.4.source.paste",
    generate: "setup.4.source.generate",
    photo: "setup.3.source.photo",
    pairs: "setup.4.source.pairs",
  } as const;

  // Mode 4 is voice only: it needs speech-to-text with word timestamps.
  if (!caps.pronunciation) {
    return (
      <SetupShell title={t("mode.4")} desc={t("setup.4.desc")}>
        <Notice>
          {caps.pronunciationOff === "timestamps" ? t("pron.timestamps") : t("notice.noStt")}
        </Notice>
        <Button size="lg" disabled>
          {t("setup.start")}
        </Button>
      </SetupShell>
    );
  }

  const sources: ReadAloudSource[] = caps.vision
    ? ["paste", "generate", "photo", "pairs"]
    : ["paste", "generate", "pairs"];
  return (
    <SetupShell title={t("mode.4")} desc={source === "photo" ? t("ocr.desc4") : t("setup.4.desc")}>
      <div className="inline-flex rounded-xl bg-ink-100 dark:bg-ink-800 p-1">
        {sources.map((s) => (
          <button
            key={s}
            onClick={() => setSource(s)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-sm font-medium",
              source === s ? "bg-white shadow text-ink-900" : "text-ink-600 dark:text-ink-300",
            )}
          >
            {t(labels[s])}
          </button>
        ))}
      </div>
      {!caps.vision && <Notice>{t("notice.noVision")}</Notice>}

      {source === "pairs" ? (
        <p className="text-sm text-ink-500">{t("setup.4.pairs.desc")}</p>
      ) : source === "photo" && !text ? (
        <PhotoOcr user={base.user} lang={base.lang} onText={(txt) => setText(txt)} />
      ) : source !== "generate" ? (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          placeholder={t("setup.4.paste.placeholder")}
          className="w-full resize-y rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
        />
      ) : (
        <div className="space-y-2">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder={t("setup.4.topic.placeholder")}
            className="w-full rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
          />
          <p className="text-xs text-ink-400">{t("setup.4.generate.hint")}</p>
        </div>
      )}

      <Button
        size="lg"
        disabled={!canStart}
        onClick={() =>
          onStart(
            source === "pairs"
              ? { ...base, mode: 4, pairMode: true }
              : source === "generate"
                ? { ...base, mode: 4, generate: true, topic: topic.trim() }
                : { ...base, mode: 4, context: text.trim() },
          )
        }
      >
        {t("setup.start")}
      </Button>
    </SetupShell>
  );
}

function SetupWriting({
  base,
  onStart,
}: {
  base: { user: string; lang: Lang };
  onStart: (cfg: SessionConfig) => void;
}) {
  const [subMode, setSubMode] = useState<SubMode>("email");
  const [subject, setSubject] = useState("");
  return (
    <SetupShell title={t("mode.5")} desc={t("setup.5.desc")}>
      <div className="inline-flex rounded-xl bg-ink-100 dark:bg-ink-800 p-1">
        {(["email", "chat"] as SubMode[]).map((sm) => (
          <button
            key={sm}
            onClick={() => setSubMode(sm)}
            className={cn(
              "px-4 py-1.5 rounded-lg text-sm font-medium",
              subMode === sm ? "bg-white shadow text-ink-900" : "text-ink-600 dark:text-ink-300",
            )}
          >
            {t(`setup.5.${sm}`)}
          </button>
        ))}
      </div>
      <input
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
        placeholder={t("setup.5.subject")}
        className="w-full rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
      />
      <Button
        size="lg"
        onClick={() =>
          onStart({
            ...base,
            mode: 5,
            subMode,
            subject: subject.trim() || undefined,
          })
        }
      >
        {t("setup.start")}
      </Button>
    </SetupShell>
  );
}

/** Mode 9: micro-lesson on one syllabus topic. Shows the next suggested topic
 * and lets the learner pick another one, with its status. */
function SetupLesson({
  base,
  onStart,
}: {
  base: { user: string; lang: Lang };
  onStart: (cfg: SessionConfig) => void;
}) {
  const [data, setData] = useState<SyllabusData | null>(null);
  const [error, setError] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSyllabus(base.user, base.lang)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
    };
  }, [base.user, base.lang]);

  if (error)
    return (
      <SetupShell title={t("mode.9")} desc={t("lesson.intro")}>
        <p className="text-sm text-red-600">{t("lesson.error")}</p>
      </SetupShell>
    );
  if (!data)
    return (
      <SetupShell title={t("mode.9")} desc={t("lesson.intro")}>
        <p className="text-sm text-ink-400">{t("scenario.loading")}</p>
      </SetupShell>
    );
  if (!data.next && !picked)
    return (
      <SetupShell title={t("mode.9")} desc={t("lesson.intro")}>
        <p className="text-sm">{t("lesson.done")}</p>
      </SetupShell>
    );

  const chosen = picked ?? data.next!.id;
  const chosenTopic = data.levels.flatMap((l) => l.topics).find((tp) => tp.id === chosen);

  return (
    <SetupShell title={t("mode.9")} desc={t("lesson.intro")}>
      <p className="font-medium text-ink-900 dark:text-ink-50">
        {t("lesson.today")}: {chosenTopic?.title}
      </p>
      <Button size="lg" onClick={() => onStart({ ...base, mode: 9, topicId: chosen })}>
        {t("lesson.start")}
      </Button>
      <button
        className="block text-sm text-accent-700 underline"
        onClick={() => setShowAll((s) => !s)}
      >
        {t("lesson.pickOther")}
      </button>
      {showAll &&
        data.levels.map((lv) => (
          <div key={lv.level}>
            <p className="mt-2 text-xs font-semibold uppercase text-ink-500">{lv.level}</p>
            {lv.topics.map((tp) => (
              <button
                key={tp.id}
                onClick={() => {
                  setPicked(tp.id);
                  setShowAll(false);
                }}
                className={cn(
                  "block w-full rounded-lg px-2 py-1 text-left text-sm",
                  tp.id === chosen && "bg-accent-500/10 text-accent-700",
                )}
                title={t(`lesson.status.${tp.status}`)}
              >
                {statusIcon(tp.status)} {tp.title}
              </button>
            ))}
          </div>
        ))}
    </SetupShell>
  );
}

function statusIcon(status: TopicStatus): string {
  return { pending: "○", seen: "◐", practiced: "◕", mastered: "●" }[status] ?? "○";
}
