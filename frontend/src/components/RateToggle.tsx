import { useState } from "react";
import { setSpeechRate } from "@/lib/api";
import { getRate, setRate } from "@/lib/storage";
import { emitRateChange } from "@/lib/rate-events";
import { t } from "@/i18n";
import { cn } from "@/lib/cn";

const RATES: { key: string; label: string; value: number | null }[] = [
  { key: "slow", label: "🐢", value: 1.3 },
  { key: "normal", label: "▶", value: null },
  { key: "fast", label: "🐇", value: 0.9 },
];

/**
 * Teacher speaking speed, changeable IN THE MIDDLE of a session. Values are
 * length scales (bigger = slower), the unit the backend synthesizes with.
 *
 * Two effects when the toggle is tapped:
 *   1) emitRateChange(ls): subscribers (useVoiceTurn) apply playbackRate to
 *      the `<audio>` playing right now (instant, no re-synthesis).
 *   2) setSpeechRate(ls) + setRate(user, ls): the value travels with the NEXT
 *      turn and the backend synthesizes at that speed. Persisted per learner.
 */
export function RateToggle({ user }: { user: string }) {
  const [rate, setRateState] = useState<number | null>(() => getRate(user));

  const pick = (value: number | null) => {
    setRateState(value);
    setRate(user, value);
    setSpeechRate(value);
    emitRateChange(value);
  };

  return (
    <div
      className="inline-flex rounded-xl bg-ink-100 dark:bg-ink-800 p-1"
      role="group"
      aria-label={t("settings.rate")}
    >
      {RATES.map(({ key, label, value }) => (
        <button
          key={key}
          onClick={() => pick(value)}
          title={t(`settings.rate.${key}`)}
          aria-label={t(`settings.rate.${key}`)}
          className={cn(
            "px-2.5 py-1.5 rounded-lg text-sm",
            rate === value ? "bg-white shadow text-ink-900" : "text-ink-600 dark:text-ink-300",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
