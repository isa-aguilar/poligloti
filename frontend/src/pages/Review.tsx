import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { fetchSrsDue, reviewSrsCard, syncSrs, type Lang, type SrsCard } from "@/lib/api";
import { humanError } from "@/hooks/useSession";
import { LS_USER, LS_LANG } from "@/lib/storage";
import { t } from "@/i18n";
import { cn } from "@/lib/cn";

type Phase = "loading" | "front" | "back" | "done" | "empty" | "error";

const RATINGS: { rating: 1 | 2 | 3 | 4; key: string; tone: string }[] = [
  { rating: 1, key: "review.again", tone: "border-red-300 text-red-700 dark:text-red-400" },
  { rating: 2, key: "review.hard", tone: "border-amber-300 text-amber-700 dark:text-amber-400" },
  { rating: 3, key: "review.good", tone: "border-green-300 text-green-700 dark:text-green-400" },
  { rating: 4, key: "review.easy", tone: "border-accent-500 text-accent-700" },
];

/**
 * Spaced repetition (FSRS) with ACTIVE recall: the translation is shown and
 * the learner produces the term (aloud or mentally) before revealing it.
 * Self-graded Anki style; the algorithm decides when to ask again.
 */
export default function ReviewPage() {
  const nav = useNavigate();
  const user = localStorage.getItem(LS_USER);
  const lang = localStorage.getItem(LS_LANG) as Lang | null;

  const [phase, setPhase] = useState<Phase>("loading");
  const [cards, setCards] = useState<SrsCard[]>([]);
  const [idx, setIdx] = useState(0);
  const [doneCount, setDoneCount] = useState(0);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!user || !lang) {
      nav("/");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await syncSrs(user, lang).catch(() => undefined); // new vocabulary becomes cards
        const res = await fetchSrsDue(user, lang);
        if (cancelled) return;
        setCards(res.due);
        setPhase(res.due.length > 0 ? "front" : "empty");
      } catch (e) {
        if (!cancelled) {
          setErr(humanError(e));
          setPhase("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, lang, nav]);

  if (!user || !lang) return null;
  const card = cards[idx];

  const rate = async (rating: 1 | 2 | 3 | 4) => {
    void reviewSrsCard(user, lang, card.term, rating).catch(() => undefined);
    setDoneCount((n) => n + 1);
    if (idx + 1 < cards.length) {
      setIdx(idx + 1);
      setPhase("front");
    } else {
      setPhase("done");
    }
  };

  return (
    <div className="min-h-full mx-auto max-w-xl px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-ink-900 dark:text-ink-50">{t("review.title")}</h1>
        <Button variant="ghost" size="sm" onClick={() => nav("/talk")}>
          {t("progress.back")}
        </Button>
      </div>

      {phase === "loading" && (
        <p className="text-ink-500 animate-pulse text-center py-12">{t("review.loading")}</p>
      )}

      {phase === "error" && <p className="text-sm text-red-600">{err}</p>}

      {phase === "empty" && (
        <Card className="p-6 text-center text-sm text-ink-500">{t("review.empty")}</Card>
      )}

      {(phase === "front" || phase === "back") && card && (
        <>
          <p className="text-xs text-ink-400 text-center">
            {idx + 1} / {cards.length}
          </p>
          <Card className="p-8 text-center space-y-4 min-h-[30vh] flex flex-col justify-center">
            <p className="text-xs uppercase tracking-wider text-ink-400">{t("review.prompt")}</p>
            <p className="text-2xl font-semibold text-ink-900 dark:text-ink-50">
              {card.translation || card.term}
            </p>
            {phase === "back" && (
              <div className="pt-4 border-t border-ink-100 dark:border-ink-800 space-y-2">
                <p className="text-2xl text-accent-700 font-semibold">{card.term}</p>
                {card.example && <p className="text-sm text-ink-500 italic">{card.example}</p>}
              </div>
            )}
          </Card>
          {phase === "front" ? (
            <Button size="lg" className="w-full" onClick={() => setPhase("back")}>
              {t("review.show")}
            </Button>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {RATINGS.map(({ rating, key, tone }) => (
                <button
                  key={rating}
                  onClick={() => rate(rating)}
                  className={cn(
                    "rounded-xl border px-2 py-3 text-sm font-medium bg-white dark:bg-ink-900",
                    tone,
                  )}
                >
                  {t(key)}
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {phase === "done" && (
        <Card className="p-6 text-center space-y-4">
          <p className="text-lg font-semibold text-ink-900 dark:text-ink-50">{t("review.done")}</p>
          <p className="text-sm text-ink-500">
            {doneCount} {t("review.reviewed")}
          </p>
          <Button size="lg" onClick={() => nav("/talk")}>
            {t("review.backToTalk")}
          </Button>
        </Card>
      )}
    </div>
  );
}
