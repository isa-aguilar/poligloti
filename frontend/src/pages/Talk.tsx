import { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Button } from "@/components/Button";
import { SidePanel } from "@/components/SidePanel";
import { ScenarioCard } from "@/components/ScenarioCard";
import { Card } from "@/components/Card";
import { WritingView } from "@/components/WritingView";
import { ReadingView } from "@/components/ReadingView";
import { PairsView } from "@/components/PairsView";
import { CallView } from "@/components/CallView";
import { ChatView } from "@/components/ChatView";
import { SetupPanel } from "@/components/setup/SetupPanel";
import { RateToggle } from "@/components/RateToggle";
import { TodayCard } from "@/components/TodayCard";
import { useVoiceTurn } from "@/hooks/useVoiceTurn";
import { setAutoUpdatePaused } from "@/lib/auto-update";
import {
  type Lang,
  type LessonMode,
  type Scenario,
  type SessionConfig,
  type SessionEndResponse,
} from "@/lib/api";
import { LS_USER, LS_LANG } from "@/lib/storage";
import { getLocale, t } from "@/i18n";
import { langLabel } from "@/lib/lang";
import { cn } from "@/lib/cn";
import { UiLangToggle } from "@/components/UiLangToggle";
import { Notice } from "@/components/Notice";
import { useCapabilities } from "@/lib/capabilities";

type Interaction = "call" | "chat";

const LESSON_MODES: { mode: LessonMode; key: string }[] = [
  { mode: 1, key: "mode.1" },
  { mode: 2, key: "mode.2" },
  { mode: 3, key: "mode.3" },
  { mode: 4, key: "mode.4" },
  { mode: 5, key: "mode.5" },
  { mode: 7, key: "mode.7" },
  { mode: 9, key: "mode.9" },
];

export default function TalkPage() {
  const nav = useNavigate();
  const user = localStorage.getItem(LS_USER);
  const lang = localStorage.getItem(LS_LANG) as Lang | null;

  useEffect(() => {
    if (!user || !lang) nav("/");
  }, [user, lang, nav]);

  if (!user || !lang) return null;
  return <TalkInner user={user} lang={lang} />;
}

function TalkInner({ user, lang }: { user: string; lang: Lang }) {
  // React does not see a UI language change on its own (t() is not a hook):
  // this state only exists to force a repaint.
  const [, setUiLang] = useState(getLocale());
  const { caps } = useCapabilities();
  const nav = useNavigate();
  const loc = useLocation();
  const [lessonMode, setLessonMode] = useState<LessonMode>(1);
  // Home view (greeting + "Today's class"). Picking a mode leaves Home and
  // shows only that mode; the "Home" chip goes back to the suggestion.
  const [home, setHome] = useState(true);
  // A session launched from another screen (My progress, My Books) arrives in
  // the router state and starts right away.
  const [autostart] = useState(
    () => (loc.state as { autostart?: SessionConfig } | null)?.autostart ?? null,
  );
  const [interaction, setInteraction] = useState<Interaction>(
    autostart?.mode === 3 ? "chat" : "call",
  );
  // config != null: active session; null: on the setup screen.
  const [config, setConfig] = useState<SessionConfig | null>(autostart);
  const [scenarioMeta, setScenarioMeta] = useState<Scenario | null>(null);
  // The key forces a remount of ActiveSession (so a new session) on every start.
  const [runKey, setRunKey] = useState(0);

  const active = config != null;
  // Without speech-to-text there is nothing to toggle: typing is the only way.
  const effectiveInteraction: Interaction = caps.stt ? interaction : "chat";
  const showInteractionToggle = caps.stt && active && config!.mode !== 5 && config!.mode !== 4;

  const pickMode = (m: LessonMode) => {
    if (m === lessonMode && !active && !home) return;
    if (active) {
      const ok = window.confirm(t("talk.switchConfirm"));
      if (!ok) return;
    }
    setConfig(null);
    setScenarioMeta(null);
    setLessonMode(m);
    setHome(false);
  };

  const goHome = () => {
    if (active) {
      const ok = window.confirm(t("talk.switchConfirm"));
      if (!ok) return;
      setConfig(null);
      setScenarioMeta(null);
    }
    setHome(true);
  };

  const startWith = (cfg: SessionConfig, meta?: Scenario | null) => {
    // Mode 3 is about a text: it opens in the typing view.
    setScenarioMeta(meta ?? null);
    setConfig(cfg);
    setInteraction(cfg.mode === 3 ? "chat" : "call");
    setRunKey((k) => k + 1);
  };

  const exit = () => nav("/");

  // Clear the router state so coming back does not start the session again.
  useEffect(() => {
    if (autostart) window.history.replaceState({}, "");
  }, [autostart]);

  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-ink-200 dark:border-ink-800 bg-white/70 dark:bg-ink-900/70 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-5xl flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="capitalize font-semibold text-ink-900 dark:text-ink-50">{user}</span>
            <span className="text-ink-400">·</span>
            <span className="text-ink-600 dark:text-ink-400">{langLabel(lang)}</span>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            {active && config!.mode !== 4 && <RateToggle user={user} />}
            {showInteractionToggle && (
              <div className="inline-flex rounded-xl bg-ink-100 dark:bg-ink-800 p-1">
                {(["call", "chat"] as Interaction[]).map((it) => (
                  <button
                    key={it}
                    onClick={() => setInteraction(it)}
                    className={cn(
                      "px-3 py-1.5 rounded-lg text-sm font-medium",
                      effectiveInteraction === it
                        ? "bg-white shadow text-ink-900"
                        : "text-ink-600 dark:text-ink-300",
                    )}
                  >
                    {t(it === "call" ? "talk.mode.call" : "talk.mode.chat")}
                  </button>
                ))}
              </div>
            )}
            <Button variant="ghost" size="sm" onClick={() => nav("/books")}>
              {t("talk.books")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => nav("/review")}>
              {t("talk.review")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => nav("/progress")}>
              {t("talk.progress")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => nav("/sessions")}>
              {t("talk.sessions")}
            </Button>
            <Button variant="ghost" size="sm" onClick={exit}>
              {t("talk.end")}
            </Button>
            <UiLangToggle onChange={setUiLang} />
          </div>
        </div>

        <div className="mx-auto max-w-5xl px-4 pb-3 flex flex-wrap gap-2">
          <button
            onClick={goHome}
            className={cn(
              "px-3 py-1.5 rounded-full text-sm font-medium border transition",
              !active && home
                ? "border-accent-500 bg-accent-500/10 text-accent-700"
                : "border-ink-200 text-ink-700 hover:border-ink-400 dark:border-ink-700 dark:text-ink-200",
            )}
          >
            {t("home.tab")}
          </button>
          {LESSON_MODES.map(({ mode, key }) => {
            const isActive = active ? config!.mode === mode : !home && lessonMode === mode;
            // Mode 4 is voice only: without pronunciation support it stays
            // visible but dimmed, and its setup screen explains why.
            const unavailable = mode === 4 && !caps.pronunciation;
            return (
              <button
                key={mode}
                onClick={() => pickMode(mode)}
                className={cn(
                  "px-3 py-1.5 rounded-full text-sm font-medium border transition",
                  unavailable && "opacity-50 border-dashed",
                  isActive
                    ? "border-accent-500 bg-accent-500/10 text-accent-700"
                    : "border-ink-200 text-ink-700 hover:border-ink-400 dark:border-ink-700 dark:text-ink-200",
                )}
              >
                {t(key)}
              </button>
            );
          })}
        </div>
      </header>

      <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-6">
        {!active ? (
          home ? (
            <TodayCard
              user={user}
              lang={lang}
              onStart={startWith}
              onPick={pickMode}
              onReview={() => nav("/review")}
            />
          ) : (
            <SetupPanel mode={lessonMode} lang={lang} onStart={startWith} />
          )
        ) : (
          <ActiveSession
            key={runKey}
            config={config!}
            interaction={effectiveInteraction}
            scenarioMeta={scenarioMeta}
            onRestart={() => setRunKey((k) => k + 1)}
            onExitSession={() => {
              setConfig(null);
              setScenarioMeta(null);
            }}
          />
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active session (the voice orchestration lives in useVoiceTurn)
// ---------------------------------------------------------------------------
function ActiveSession({
  config,
  interaction,
  scenarioMeta,
  onRestart,
  onExitSession,
}: {
  config: SessionConfig;
  interaction: Interaction;
  scenarioMeta: Scenario | null;
  onRestart: () => void;
  onExitSession: () => void;
}) {
  const voice = useVoiceTurn(config);
  const { session, recorder, audioRef, queue } = voice;
  const { caps } = useCapabilities();
  const [draft, setDraft] = useState("");
  // Explicit close with a post-session report.
  const [finishing, setFinishing] = useState(false);
  const [summary, setSummary] = useState<SessionEndResponse | null>(null);
  // Mode 8 (book): step 1 is reading aloud; moving on to comprehension
  // (kickoff) falls through to the normal conversational view. Without
  // pronunciation support the reading step is skipped.
  const [bookTalk, setBookTalk] = useState(false);
  const skipBookReading = config.mode === 8 && !caps.pronunciation;
  const kickedOff = useRef(false);
  useEffect(() => {
    if (!skipBookReading || !session.sessionId || kickedOff.current) return;
    kickedOff.current = true;
    void session.startKickoff();
  }, [skipBookReading, session]);

  // Do not auto-reload the PWA in the middle of a session (it would lose the thread).
  useEffect(() => {
    setAutoUpdatePaused(true);
    return () => setAutoUpdatePaused(false);
  }, []);

  // Mode 8: before closing, ask which page the learner stopped at. Without
  // this the START page would be saved, which is wrong as soon as she adds
  // another page. Optional: she can finish without saying.
  const [askPage, setAskPage] = useState(false);
  const [endPage, setEndPage] = useState("");

  const close = async (lastPage?: number) => {
    queue.reset();
    session.cancelStream();
    setAskPage(false);
    setFinishing(true);
    const res = await session.finish(lastPage);
    setFinishing(false);
    if (res) setSummary(res);
    else onExitSession(); // no report (network failure): back to setup
  };

  const onFinish = async () => {
    if (config.mode === 8) {
      setEndPage(String(config.page ?? ""));
      setAskPage(true);
      return;
    }
    await close();
  };

  const { turns, state, error, scenarioInfo } = session;

  // One discreet line per missing capability that affects this view.
  const notices = (
    <>
      {!caps.stt && <Notice>{t("notice.noStt")}</Notice>}
      {voice.voice.source === "none" && (
        <Notice>{t("notice.noVoice").replace("{language}", langLabel(config.lang))}</Notice>
      )}
    </>
  );

  if (askPage) {
    const n = Number(endPage);
    return (
      <div className="max-w-md mx-auto py-16 space-y-4 text-center">
        <h2 className="text-xl font-semibold text-ink-900 dark:text-ink-50">
          {t("books.endPageAsk")}
        </h2>
        <input
          type="number"
          min={1}
          inputMode="numeric"
          value={endPage}
          onChange={(e) => setEndPage(e.target.value)}
          className="w-32 mx-auto block text-center text-2xl rounded-xl border border-ink-200 dark:border-ink-600 bg-transparent px-3 py-2"
          autoFocus
        />
        <div className="flex flex-col gap-2 pt-2">
          <Button size="lg" onClick={() => void close(n > 0 ? n : undefined)}>
            {t("books.endPageConfirm")}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void close()}>
            {t("books.endPageSkip")}
          </Button>
        </div>
      </div>
    );
  }

  if (finishing) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center">
        <p className="text-ink-500 animate-pulse">{t("summary.loading")}</p>
      </div>
    );
  }

  if (summary) {
    return <SessionSummary data={summary} onAgain={onExitSession} />;
  }

  // Starting state: some modes run a model kickoff first (~10s).
  if (state === "starting") {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center space-y-4">
        <p className="text-ink-500 animate-pulse">
          {config.mode === 2
            ? t("loading.scene")
            : config.mode === 3
              ? t("loading.text")
              : config.mode === 8
                ? t("loading.book")
                : config.mode === 4 && config.generate
                  ? t("loading.read")
                  : t("loading.generic")}
        </p>
        {scenarioMeta && (
          <Card className="p-4 text-left">
            <h3 className="font-semibold">{scenarioMeta.title}</h3>
            <p className="text-sm text-ink-500 mt-1">{scenarioMeta.description}</p>
          </Card>
        )}
      </div>
    );
  }

  // "error" only happens when /session/start failed: no session to keep.
  // Turn failures arrive as `error` with state "idle" (recoverable).
  if (state === "error") {
    return (
      <Card className="p-5 max-w-xl mx-auto text-center space-y-3">
        <p className="text-sm text-red-600">{error}</p>
        <Button size="sm" variant="outline" onClick={onRestart}>
          {t("error.retry")}
        </Button>
      </Card>
    );
  }

  // Turn error banner: the view stays mounted (the mode 5 draft is not lost)
  // and the last send can be retried.
  const errorBanner = error ? (
    <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40 px-4 py-3">
      <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
      <Button size="sm" variant="outline" onClick={session.retry}>
        {t("error.retry")}
      </Button>
    </div>
  ) : null;

  // Mode 4: read aloud. Mode 5: writing. Their own views.
  const finishFooter = (
    <div className="mt-6 flex justify-center">
      <Button variant="outline" size="sm" onClick={onFinish}>
        {t("session.finish")}
      </Button>
    </div>
  );
  if (config.mode === 4) {
    return (
      <div>
        {errorBanner}
        {config.pairMode ? <PairsView session={session} /> : <ReadingView session={session} />}
        {finishFooter}
      </div>
    );
  }
  if (config.mode === 8 && !bookTalk && !skipBookReading) {
    // Book mode step 1: read aloud. "On to comprehension" triggers the
    // teacher's opening (kickoff); "Finish here" closes with a report.
    return (
      <div>
        {errorBanner}
        <ReadingView session={session} />
        <div className="mt-6 flex justify-center gap-3">
          <Button
            size="lg"
            onClick={() => {
              setBookTalk(true);
              void session.startKickoff();
            }}
          >
            {t("books.toTalk")}
          </Button>
          <Button variant="outline" size="sm" onClick={onFinish}>
            {t("books.finishHere")}
          </Button>
        </div>
      </div>
    );
  }
  if (config.mode === 5) {
    return (
      <div>
        {errorBanner}
        <WritingView
          session={session}
          subMode={config.subMode === "chat" ? "chat" : "email"}
          voice={voice.voice}
          user={config.user}
        />
        {finishFooter}
      </div>
    );
  }

  const onSendText = async () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    await voice.sendText(text);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
      <section className="flex flex-col">
        {errorBanner}
        <div className="mb-3 space-y-1">{notices}</div>
        {voice.audioBlocked && interaction === "chat" && (
          <button
            onClick={voice.resumeAudio}
            className="mb-3 self-center rounded-xl bg-accent-600 px-5 py-2.5 text-white font-medium shadow hover:bg-accent-700"
          >
            {t("call.tapToListen")}
          </button>
        )}
        {interaction === "call" ? (
          <CallView
            micState={voice.micState}
            micLabel={voice.micLabel}
            onMic={voice.onMic}
            recorderError={recorder.error}
            turns={turns}
            hasAudio={voice.canReplay}
            audioBlocked={voice.audioBlocked}
            onResumeAudio={voice.resumeAudio}
            onReplay={voice.replay}
          />
        ) : (
          <ChatView
            turns={turns}
            draft={draft}
            setDraft={setDraft}
            onSend={onSendText}
            disabled={!session.sessionId || state === "thinking" || state === "speaking"}
          />
        )}
      </section>

      <aside className="lg:sticky lg:top-32 self-start w-full space-y-3">
        {scenarioInfo && <ScenarioCard info={scenarioInfo} />}
        <SidePanel turns={turns} />
        {turns.length > 0 && (
          <Button variant="outline" size="sm" className="w-full" onClick={onFinish}>
            {t("session.finish")}
          </Button>
        )}
      </aside>

      <audio ref={audioRef} onEnded={queue.onEnded} hidden />
    </div>
  );
}

function SessionSummary({ data, onAgain }: { data: SessionEndResponse; onAgain: () => void }) {
  // An assessment produces no `summary` nor vocabulary, so without this block
  // its closing screen would be empty right after the learner was assessed.
  const isAssessment = !!data.cefr;
  const hasContent =
    isAssessment ||
    !!data.summary ||
    (data.session_vocab?.length ?? 0) > 0 ||
    (data.missed_opportunities?.length ?? 0) > 0;
  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <h2 className="text-xl font-semibold text-ink-900 dark:text-ink-50">{t("summary.title")}</h2>
      <p className="text-sm text-ink-500">
        {data.turns} {t("summary.turns")}
      </p>
      {data.analysis_error && (
        <p className="text-sm text-amber-500">
          {t("summary.analysisError")} {data.analysis_error}
        </p>
      )}
      {isAssessment && (
        <Card className="p-5 space-y-4 border-accent-500/40">
          <div>
            <p className="text-xs uppercase tracking-wider text-ink-400">{t("summary.level")}</p>
            <p className="text-3xl font-bold text-ink-900 dark:text-ink-50">{data.cefr}</p>
          </div>
          {data.assessment_summary && (
            <p className="text-sm whitespace-pre-wrap">{data.assessment_summary}</p>
          )}
          {(data.strengths?.length ?? 0) > 0 && (
            <div>
              <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-1">
                {t("summary.strengths")}
              </h3>
              <ul className="space-y-1">
                {data.strengths!.map((x, i) => (
                  <li key={i} className="text-sm">
                    ✓ {x}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(data.weaknesses?.length ?? 0) > 0 && (
            <div>
              <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-1">
                {t("summary.weaknesses")}
              </h3>
              <ul className="space-y-1">
                {data.weaknesses!.map((x, i) => (
                  <li key={i} className="text-sm">
                    • {x}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.focus && (
            <div>
              <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-1">
                {t("summary.focus")}
              </h3>
              <p className="text-sm">{data.focus}</p>
            </div>
          )}
        </Card>
      )}
      {data.summary && (
        <Card className="p-4">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
            {t("summary.note")}
          </h3>
          <p className="text-sm whitespace-pre-wrap">{data.summary}</p>
        </Card>
      )}
      {(data.session_vocab?.length ?? 0) > 0 && (
        <Card className="p-4">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
            {t("summary.vocab")}
          </h3>
          <ul className="space-y-1">
            {data.session_vocab!.map((v, i) => (
              <li key={i} className="text-sm">
                <span className="font-medium">{v.term}</span>
                {v.translation && <span className="text-ink-500">: {v.translation}</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {(data.missed_opportunities?.length ?? 0) > 0 && (
        <Card className="p-4">
          <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
            {t("summary.missed")}
          </h3>
          <ul className="space-y-1">
            {data.missed_opportunities!.map((m, i) => (
              <li key={i} className="text-sm text-ink-800 dark:text-ink-100">
                {m}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {!hasContent && <p className="text-sm text-ink-500">{t("summary.empty")}</p>}
      <Button size="lg" onClick={onAgain}>
        {t("summary.again")}
      </Button>
    </div>
  );
}
