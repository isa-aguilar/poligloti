import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { MessageList } from "@/components/MessageList";
import type { Message } from "@/lib/messages";
import {
  ApiError,
  fetchSessionDetail,
  fetchSessions,
  type Lang,
  type SessionDetail,
  type SessionListItem,
  type SessionNotes,
} from "@/lib/api";
import { getLocale, t } from "@/i18n";
import { humanError } from "@/hooks/useSession";
import { langLabel } from "@/lib/lang";
import { LS_USER, LS_LANG } from "@/lib/storage";

/** Mode name: the lesson labels where they exist, a generic one otherwise. */
function modeLabel(mode: number | null): string {
  if (mode == null) return t("sessions.mode.generic");
  for (const key of [`mode.${mode}`, `sessions.mode.${mode}`]) {
    const label = t(key);
    if (label !== key) return label;
  }
  return t("sessions.mode.generic");
}

/** Localised date for a YYYY-MM-DD day (falls back to the raw string). */
function formatDay(day: string): string {
  const d = new Date(`${day}T00:00:00`);
  if (Number.isNaN(d.getTime())) return day;
  return d.toLocaleDateString(getLocale(), {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export default function SessionsPage() {
  const nav = useNavigate();
  const { id } = useParams<{ id?: string }>();
  const user = localStorage.getItem(LS_USER);
  const lang = localStorage.getItem(LS_LANG) as Lang | null;

  useEffect(() => {
    if (!user || !lang) nav("/");
  }, [user, lang, nav]);

  if (!user || !lang) return null;

  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-ink-200 dark:border-ink-800 bg-white/70 dark:bg-ink-900/70 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-3xl flex items-center justify-between gap-2 px-4 py-3">
          <h1 className="text-lg font-semibold">
            {t("sessions.title")}
            <span className="ml-2 text-sm font-normal text-ink-500">{langLabel(lang)}</span>
          </h1>
          <div className="flex items-center gap-2">
            {id && (
              <Button variant="ghost" size="sm" onClick={() => nav("/sessions")}>
                {t("sessions.all")}
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => nav("/talk")}>
              {t("progress.back")}
            </Button>
          </div>
        </div>
      </header>

      <main className="flex-1 mx-auto w-full max-w-3xl px-4 py-6 space-y-4">
        {id ? (
          <SessionDetailView key={id} user={user} lang={lang} id={id} />
        ) : (
          <SessionList user={user} lang={lang} onOpen={(sid) => nav(`/sessions/${sid}`)} />
        )}
      </main>
    </div>
  );
}

function SessionList({
  user,
  lang,
  onOpen,
}: {
  user: string;
  lang: Lang;
  onOpen: (id: string) => void;
}) {
  const [sessions, setSessions] = useState<SessionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSessions(user, lang)
      .then((s) => !cancelled && setSessions(s))
      .catch((e) => !cancelled && setError(humanError(e)));
    return () => {
      cancelled = true;
    };
  }, [user, lang]);

  if (error) {
    return (
      <Card className="p-4">
        <p className="text-sm text-red-600">{error}</p>
      </Card>
    );
  }
  if (!sessions) {
    return <p className="text-ink-400 animate-pulse text-center py-8">{t("sessions.loading")}</p>;
  }
  if (sessions.length === 0) {
    return (
      <Card className="p-6 text-center">
        <p className="text-ink-500">{t("sessions.empty")}</p>
      </Card>
    );
  }

  return (
    <ul className="space-y-3">
      {sessions.map((s) => {
        const mode = modeLabel(s.mode);
        // The label is only worth showing when it says more than the mode name.
        const showLabel = !!s.label && s.label.trim().toLowerCase() !== mode.toLowerCase();
        return (
          <li key={s.id}>
            <button
              onClick={() => onOpen(s.id)}
              className="w-full text-left rounded-2xl border border-ink-200 dark:border-ink-800 bg-white dark:bg-ink-900 p-4 hover:border-accent-500 transition focus:outline-none focus:ring-2 focus:ring-accent-500"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-medium text-ink-900 dark:text-ink-50">
                  {formatDay(s.day)}
                  <span className="ml-2 text-ink-500 font-normal">{s.started}</span>
                </p>
                <div className="flex items-center gap-2 text-xs">
                  {s.has_notes && (
                    <span className="rounded-full bg-accent-500/10 text-accent-700 dark:text-accent-500 px-2 py-0.5">
                      {t("sessions.notesBadge")}
                    </span>
                  )}
                  <span className="text-ink-500">
                    {s.turns} {t("sessions.turns")}
                  </span>
                </div>
              </div>
              <p className="mt-1 text-sm text-accent-700 dark:text-accent-500">
                {mode}
                {showLabel && <span className="text-ink-500"> · {s.label}</span>}
              </p>
              {s.preview && (
                <p className="mt-1 text-sm text-ink-600 dark:text-ink-300 line-clamp-2">
                  {s.preview}
                </p>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function SessionDetailView({ user, lang, id }: { user: string; lang: Lang; id: string }) {
  const [data, setData] = useState<SessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSessionDetail(user, lang, id)
      .then((d) => !cancelled && setData(d))
      .catch((e) => {
        if (cancelled) return;
        setError(
          e instanceof ApiError && e.status === 404 ? t("sessions.notFound") : humanError(e),
        );
      });
    return () => {
      cancelled = true;
    };
  }, [user, lang, id]);

  if (error) {
    return (
      <Card className="p-4">
        <p className="text-sm text-red-600">{error}</p>
      </Card>
    );
  }
  if (!data) {
    return <p className="text-ink-400 animate-pulse text-center py-8">{t("sessions.loading")}</p>;
  }

  const messages: Message[] = (data.turns ?? []).map((tn, i) => ({
    id: i,
    learner: tn.learner ?? "",
    teacher: tn.teacher ?? "",
    corrections: tn.corrections ?? [],
  }));
  const mode = modeLabel(data.mode);

  return (
    <>
      <div>
        <p className="text-sm font-medium text-ink-900 dark:text-ink-50">
          {formatDay(data.day)}
          <span className="ml-2 text-ink-500 font-normal">{data.started}</span>
        </p>
        <p className="text-sm text-accent-700 dark:text-accent-500">
          {mode}
          {data.label && data.label.trim().toLowerCase() !== mode.toLowerCase() && (
            <span className="text-ink-500"> · {data.label}</span>
          )}
        </p>
      </div>

      {data.notes && <NotesCard notes={data.notes} />}

      <Card className="p-4">
        <MessageList
          messages={messages}
          empty={<p className="text-sm text-ink-400 text-center py-4">{t("sessions.noTurns")}</p>}
        />
      </Card>
    </>
  );
}

function NotesCard({ notes }: { notes: SessionNotes }) {
  const vocab = notes.session_vocab ?? [];
  const missed = notes.missed_opportunities ?? [];
  const strengths = notes.strengths ?? [];
  const weaknesses = notes.weaknesses ?? [];
  const heading = "text-xs uppercase tracking-wider text-ink-400 mb-1";

  return (
    <Card className="p-5 space-y-4 border-accent-500/40">
      <h2 className="text-sm font-semibold text-ink-900 dark:text-ink-50">{t("sessions.notes")}</h2>

      {notes.cefr && (
        <div>
          <p className={heading}>{t("summary.level")}</p>
          <p className="text-2xl font-bold text-ink-900 dark:text-ink-50">{notes.cefr}</p>
        </div>
      )}
      {notes.assessment_summary && (
        <p className="text-sm whitespace-pre-wrap">{notes.assessment_summary}</p>
      )}
      {notes.summary && <p className="text-sm whitespace-pre-wrap">{notes.summary}</p>}

      {strengths.length > 0 && (
        <div>
          <h3 className={heading}>{t("summary.strengths")}</h3>
          <ul className="space-y-1">
            {strengths.map((x, i) => (
              <li key={i} className="text-sm">
                ✓ {x}
              </li>
            ))}
          </ul>
        </div>
      )}
      {weaknesses.length > 0 && (
        <div>
          <h3 className={heading}>{t("summary.weaknesses")}</h3>
          <ul className="space-y-1">
            {weaknesses.map((x, i) => (
              <li key={i} className="text-sm">
                • {x}
              </li>
            ))}
          </ul>
        </div>
      )}
      {notes.focus && (
        <div>
          <h3 className={heading}>{t("summary.focus")}</h3>
          <p className="text-sm">{notes.focus}</p>
        </div>
      )}

      {missed.length > 0 && (
        <div>
          <h3 className={heading}>{t("sessions.missed")}</h3>
          <ul className="space-y-1">
            {missed.map((m, i) => (
              <li key={i} className="text-sm text-ink-800 dark:text-ink-100">
                {m}
              </li>
            ))}
          </ul>
        </div>
      )}

      {vocab.length > 0 && (
        <div>
          <h3 className={heading}>{t("sessions.vocab")}</h3>
          <ul className="space-y-1">
            {vocab.map((v, i) => (
              <li key={i} className="text-sm">
                <span className="font-medium">{v.term}</span>
                {v.translation && <span className="text-ink-500">: {v.translation}</span>}
                {v.example && <p className="text-xs italic text-ink-500">{v.example}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {notes.analysis_error && (
        <p className="text-xs text-ink-400">
          {t("sessions.analysisError")} {notes.analysis_error}
        </p>
      )}
    </Card>
  );
}
