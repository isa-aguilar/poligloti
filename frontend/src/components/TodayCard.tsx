import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import {
  fetchHome,
  type HomeData,
  type Lang,
  type LessonMode,
  type SessionConfig,
} from "@/lib/api";
import { t } from "@/i18n";

/**
 * "Today's class" card: greeting with progress (CEFR, streak, words) and a
 * class suggestion computed by rules on the backend. A hint only: the mode
 * chips stay available to choose freely. If the backend fails, the card is
 * not shown (silently) and the chips still work.
 */
export function TodayCard({
  user,
  lang,
  onStart,
  onPick,
  onReview,
}: {
  user: string;
  lang: Lang;
  onStart: (cfg: SessionConfig) => void;
  onPick: (mode: LessonMode) => void;
  onReview: () => void;
}) {
  const [home, setHome] = useState<HomeData | null>(null);

  useEffect(() => {
    let cancel = false;
    fetchHome(user, lang)
      .then((h) => !cancel && setHome(h))
      .catch(() => !cancel && setHome(null));
    return () => {
      cancel = true;
    };
  }, [user, lang]);

  if (!home) return null;

  const { greeting: g, suggestion: s } = home;

  // t() does not interpolate: compose with the number or value at the start
  // or the end (works in en/es/de).
  const stats = [
    // g.cefr can be null: nobody has measured the level yet.
    g.cefr,
    g.streak > 0
      ? `${g.streak} ${t(g.streak === 1 ? "home.streak.unit.one" : "home.streak.unit")}`
      : t("home.streak.zero"),
    `${g.vocab_count} ${t("home.vocab.unit")}`,
  ].filter(Boolean);

  const label = t(`home.label.${s.kind}`);
  let reason: string;
  if (s.kind === "srs") reason = `${s.count} ${t("home.reason.srs")}`;
  else if (s.kind === "focus") reason = `${t("home.reason.focus")} ${s.focus}`;
  else if (s.kind === "skill") reason = `${t("home.reason.skill")} ${t(`skill.${s.skill}`)}`;
  else if (s.kind === "lesson") reason = `${t("home.reason.lesson")} ${s.focus ?? ""}`.trim();
  else reason = t(`home.reason.${s.kind}`);

  const start = () => {
    if (s.route === "/review") return onReview();
    if (s.mode === 6) return onStart({ user, lang, mode: 6, subMode: "assessment" });
    // Mode 9 (lesson): start right away with the suggested topic.
    if (s.kind === "lesson" || s.mode === 9)
      return onStart({ user, lang, mode: 9, topicId: s.topic_id ?? undefined });
    if (s.mode && [2, 3, 4, 5].includes(s.mode)) return onPick(s.mode as LessonMode);
    return onStart({ user, lang, mode: 1 }); // mode 1 and fallback: start right away
  };

  return (
    <Card className="p-5 space-y-3 mb-6">
      <div>
        <p className="text-lg font-semibold text-ink-900 dark:text-ink-50">
          {t("home.hello")}, {g.name}
        </p>
        <p className="text-xs text-ink-500 mt-0.5">{stats.join(" · ")}</p>
      </div>
      <div className="rounded-xl border border-accent-500 bg-accent-500/10 p-3">
        <p className="text-xs uppercase tracking-wider text-accent-700">{t("home.today")}</p>
        <p className="text-sm font-medium text-ink-900 dark:text-ink-50 mt-1">{label}</p>
        <p className="text-sm text-ink-600 dark:text-ink-300 mt-0.5">{reason}</p>
        <Button size="sm" className="mt-3" onClick={start}>
          {t("home.start")}
        </Button>
      </div>
    </Card>
  );
}
