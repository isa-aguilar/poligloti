import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { RadarChart } from "@/components/RadarChart";
import { ProgressTrend } from "@/components/ProgressTrend";
import {
  fetchProfiles,
  fetchProgress,
  type Lang,
  type Mode6Sub,
  type Profile,
  type ProgressData,
  type SessionConfig,
} from "@/lib/api";
import { t, getLocale } from "@/i18n";
import { humanError } from "@/hooks/useSession";
import { langLabel } from "@/lib/lang";
import { cn } from "@/lib/cn";
import { LS_USER, LS_LANG } from "@/lib/storage";

export default function ProgressPage() {
  const nav = useNavigate();
  const me = localStorage.getItem(LS_USER);
  const myLang = localStorage.getItem(LS_LANG) as Lang | null;

  const [profiles, setProfiles] = useState<Profile[]>([]);
  // Each learner sees ONLY her own progress: showing someone else's level and
  // mistakes is not worth the motivation of comparing. `profiles` is still
  // loaded because it lists the languages started; the language picker stays.
  const view = me;
  const [viewLang, setViewLang] = useState<Lang | null>(myLang);
  // Tagged with the language it was loaded for, so switching language shows the
  // loading state instead of the previous language's data.
  const [result, setResult] = useState<{
    lang: Lang;
    data?: ProgressData;
    error?: string;
  } | null>(null);
  const [openRev, setOpenRev] = useState<string | null>(null);

  useEffect(() => {
    if (!me || !myLang) nav("/");
  }, [me, myLang, nav]);

  useEffect(() => {
    fetchProfiles()
      .then(setProfiles)
      .catch(() => undefined);
  }, []);

  const viewProfile = profiles.find((p) => p.user === view) ?? null;
  // Languages STARTED by the learner (each (user, lang) has its own progress).
  // The ones with real data are used, not the ones declared in profile.md:
  // anyone can start any language, so the declared list can fall short and
  // hide real progress.
  const viewLangs: Lang[] = viewProfile?.languages_started?.length
    ? viewProfile.languages_started
    : (viewProfile?.languages_studied ?? (viewLang ? [viewLang] : []));

  useEffect(() => {
    if (!view || !viewLang) return;
    let cancelled = false;
    fetchProgress(view, viewLang, getLocale())
      .then((d) => !cancelled && setResult({ lang: viewLang, data: d }))
      .catch((e) => !cancelled && setResult({ lang: viewLang, error: humanError(e) }));
    return () => {
      cancelled = true;
    };
  }, [view, viewLang]);
  const current = result && result.lang === viewLang ? result : null;
  const data = current?.data ?? null;
  const error = current?.error ?? null;

  if (!me || !myLang) return null;

  const startMode6 = (sub: Mode6Sub) => {
    // Start the assessment in the language being viewed (not always the primary one).
    const cfg: SessionConfig = { user: me, lang: viewLang ?? myLang, mode: 6, subMode: sub };
    nav("/talk", { state: { autostart: cfg } });
  };

  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b border-ink-200 dark:border-ink-800 bg-white/70 dark:bg-ink-900/70 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto max-w-3xl flex items-center justify-between gap-2 px-4 py-3">
          <h1 className="text-lg font-semibold">{t("progress.title")}</h1>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => nav("/sessions")}>
              {t("talk.sessions")}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => nav("/talk")}>
              {t("progress.back")}
            </Button>
          </div>
        </div>
        {viewLangs.length > 1 && (
          <div className="mx-auto max-w-3xl px-4 pb-3 flex items-center gap-2">
            <span className="text-sm text-ink-500">{t("progress.language")}:</span>
            <div className="inline-flex rounded-xl bg-ink-100 dark:bg-ink-800 p-1">
              {viewLangs.map((l) => (
                <button
                  key={l}
                  onClick={() => setViewLang(l)}
                  className={cn(
                    "px-3 py-1 rounded-lg text-sm font-medium",
                    viewLang === l
                      ? "bg-white shadow text-ink-900"
                      : "text-ink-600 dark:text-ink-300",
                  )}
                >
                  {langLabel(l)}
                </button>
              ))}
            </div>
          </div>
        )}
      </header>

      <main className="flex-1 mx-auto w-full max-w-3xl px-4 py-6 space-y-5">
        {error && (
          <Card className="p-4">
            <p className="text-sm text-red-600">{error}</p>
          </Card>
        )}

        {/* Pending assessment: shown even when a tracker exists (a level set by
            hand is not an assessment), otherwise no screen would offer it. */}
        {data && data.has_data && !data.has_assessment && (
          <Card className="p-5 space-y-3 border-accent-500/40">
            <p className="text-sm font-medium text-ink-800 dark:text-ink-100">
              {t("progress.assessment.pending")}
            </p>
            <p className="text-sm text-ink-500">{t("progress.assessment.why")}</p>
            <Button size="lg" onClick={() => startMode6("assessment")}>
              {t("progress.assessment")}
            </Button>
          </Card>
        )}

        {data && !data.has_data ? (
          <Card className="p-6 text-center space-y-4">
            <p className="text-ink-500">{t("progress.empty")}</p>
            {data.expressions_count > 0 && (
              <p className="text-sm text-ink-500">
                {t("progress.expressions")}:{" "}
                <span className="font-semibold">{data.expressions_count}</span>
              </p>
            )}
            <Button size="lg" onClick={() => startMode6("assessment")}>
              {t("progress.assessment")}
            </Button>
          </Card>
        ) : data ? (
          <>
            {/* CEFR + bar */}
            <Card className="p-5">
              <div className="flex items-end justify-between gap-3 flex-wrap">
                <div>
                  <p className="text-sm text-ink-500">{t("progress.level")}</p>
                  <p className="text-3xl font-bold text-ink-900 dark:text-ink-50">{data.cefr}</p>
                </div>
                {data.next_cefr && (
                  <p className="text-sm text-ink-500">
                    {t("progress.toward")} <span className="font-semibold">{data.next_cefr}</span>
                  </p>
                )}
              </div>
              <div className="mt-3 h-2.5 rounded-full bg-ink-100 dark:bg-ink-800 overflow-hidden">
                <div
                  className="h-full bg-accent-500 rounded-full"
                  style={{ width: `${data.avg_score}%` }}
                />
              </div>
              <p className="text-xs text-ink-400 mt-1">{data.avg_score}%</p>
              {data.expressions_count > 0 && (
                <p className="text-xs text-ink-400 mt-2">
                  {t("progress.expressions")}:{" "}
                  <span className="font-semibold text-ink-600 dark:text-ink-300">
                    {data.expressions_count}
                  </span>
                </p>
              )}
              {data.levelup_eligible && (
                <div className="mt-4 flex items-center justify-between gap-2 flex-wrap">
                  <span className="text-sm text-green-700 dark:text-green-400">
                    {t("progress.eligible")}
                  </span>
                  <Button size="sm" onClick={() => startMode6("test")}>
                    {t("progress.levelup")}
                  </Button>
                </div>
              )}
              {/* Recalibrate whenever the learner wants, not only when the app says so. */}
              {data.has_assessment && (
                <div className="mt-4 pt-3 border-t border-ink-100 dark:border-ink-700">
                  <Button variant="outline" size="sm" onClick={() => startMode6("assessment")}>
                    {t("progress.assessment.redo")}
                  </Button>
                  <p className="text-xs text-ink-400 mt-2">{t("progress.assessment.redo.hint")}</p>
                </div>
              )}
            </Card>

            {/* Radar (where she is today) + curve (whether she is improving) */}
            <Card className="p-5 space-y-5">
              <RadarChart dims={data.dims} />
              <div className="border-t border-ink-100 dark:border-ink-700 pt-4">
                <h2 className="text-sm font-medium text-ink-600 dark:text-ink-400 mb-3">
                  {t("progress.trend")}
                </h2>
                <ProgressTrend history={data.history ?? []} dims={data.dims} />
              </div>
            </Card>

            {/* Focus + milestones */}
            {(data.focus || data.milestones.length > 0) && (
              <Card className="p-5 space-y-3">
                {data.focus && (
                  <div>
                    <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-1">
                      {t("progress.focus")}
                    </h3>
                    <p className="text-sm">{data.focus}</p>
                  </div>
                )}
                {data.milestones.length > 0 && (
                  <div>
                    <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-1">
                      {t("progress.milestones")}
                    </h3>
                    <ul className="list-disc list-inside text-sm space-y-0.5">
                      {data.milestones.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>
            )}

            {/* Mistakes */}
            <div className="grid sm:grid-cols-2 gap-4">
              <Card className="p-4">
                <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
                  {t("progress.active")}
                </h3>
                {data.active_errors.length > 0 ? (
                  <ul className="text-sm space-y-1">
                    {data.active_errors.map((e, i) => (
                      <li key={i} className="text-red-600/90 dark:text-red-400/90">
                        • {e}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-ink-400">{t("progress.none")}</p>
                )}
              </Card>
              <Card className="p-4">
                <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
                  {t("progress.resolved")}
                </h3>
                {data.resolved_errors.length > 0 ? (
                  <ul className="text-sm space-y-1">
                    {data.resolved_errors.map((e, i) => (
                      <li key={i} className="text-green-700/90 dark:text-green-400/90">
                        ✓ {e}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-ink-400">{t("progress.none")}</p>
                )}
              </Card>
            </div>

            {/* Weekly reviews */}
            {(data.weekly_reviews ?? []).length > 0 && (
              <Card className="p-4">
                <h3 className="text-xs uppercase tracking-wider text-ink-400 mb-2">
                  {t("progress.reviews")}
                </h3>
                <div className="divide-y divide-ink-100 dark:divide-ink-800">
                  {data.weekly_reviews.map((r) => (
                    <div key={r.week} className="py-2">
                      <button
                        onClick={() => setOpenRev(openRev === r.week ? null : r.week)}
                        className="w-full text-left text-sm font-medium flex justify-between"
                      >
                        <span>{r.week}</span>
                        <span className="text-ink-400">{openRev === r.week ? "−" : "+"}</span>
                      </button>
                      {openRev === r.week && (
                        <p className="text-sm text-ink-600 dark:text-ink-300 mt-1 whitespace-pre-wrap">
                          {r.text}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            )}
          </>
        ) : (
          !error && <p className="text-ink-400 text-center py-12">…</p>
        )}
      </main>
    </div>
  );
}
