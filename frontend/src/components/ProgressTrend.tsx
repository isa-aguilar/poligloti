import { useMemo, useState } from "react";
import type { ProgressDim, ProgressHistoryPoint } from "@/lib/api";
import { getLocale, t } from "@/i18n";

const W = 340;
const H = 170;
const PAD_L = 26;
const PAD_B = 20;
const PAD_T = 10;

function dimLabel(d: ProgressDim): string {
  const key = `skill.${d.key}`;
  const tr = t(key);
  return tr === key ? d.label : tr;
}

// "2026-08-27 12:30" -> "27 Aug" (month name in the UI language)
function shortDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  try {
    return d.toLocaleDateString(getLocale(), { day: "numeric", month: "short" });
  } catch {
    return `${m[3]}/${m[2]}`;
  }
}

/**
 * Scores over time. Plain SVG, no dependencies, like RadarChart: the radar
 * says where the learner is today, this says whether she is improving. It only
 * draws what really exists: old tracker entries have no numbers, so the curve
 * can start late.
 */
export function ProgressTrend({
  history,
  dims,
}: {
  history: ProgressHistoryPoint[];
  dims: ProgressDim[];
}) {
  const [sel, setSel] = useState<string>("__avg__");

  const series = useMemo(() => {
    return history.map((h) => {
      if (sel === "__avg__") {
        const vals = Object.values(h.scores);
        return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : 0;
      }
      return h.scores[sel] ?? 0;
    });
  }, [history, sel]);

  if (history.length < 2) {
    return <p className="text-sm text-ink-500 dark:text-ink-400">{t("progress.trend.empty")}</p>;
  }

  const n = series.length;
  const x = (i: number) => PAD_L + (i * (W - PAD_L - 8)) / Math.max(1, n - 1);
  const y = (v: number) => PAD_T + (100 - v) * ((H - PAD_T - PAD_B) / 100);
  const path = series.map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`).join(" ");

  const first = series[0];
  const last = series[n - 1];
  const delta = last - first;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={sel}
          onChange={(e) => setSel(e.target.value)}
          className="text-sm rounded-lg border border-ink-200 dark:border-ink-600 bg-transparent px-2 py-1"
        >
          <option value="__avg__">{t("progress.trend.avg")}</option>
          {dims.map((d) => (
            <option key={d.key} value={d.key}>
              {dimLabel(d)}
            </option>
          ))}
        </select>
        <span
          className={
            delta > 0
              ? "text-sm font-semibold text-emerald-600"
              : delta < 0
                ? "text-sm font-semibold text-amber-600"
                : "text-sm text-ink-500"
          }
        >
          {delta > 0 ? "+" : ""}
          {delta} {t("progress.trend.since")} {shortDate(history[0].date)}
        </span>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-sm" role="img">
        {[0, 25, 50, 75, 100].map((v) => (
          <g key={v}>
            <line
              x1={PAD_L}
              y1={y(v)}
              x2={W - 8}
              y2={y(v)}
              className="stroke-ink-200 dark:stroke-ink-700"
              strokeWidth="1"
            />
            <text x={PAD_L - 6} y={y(v) + 3} textAnchor="end" className="fill-ink-400 text-[9px]">
              {v}
            </text>
          </g>
        ))}
        <path d={path} fill="none" className="stroke-accent-500" strokeWidth="2" />
        {series.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r="3" className="fill-accent-500">
            <title>{`${shortDate(history[i].date)}: ${v}`}</title>
          </circle>
        ))}
        {/* Only the first and last dates: with many sessions they would overlap. */}
        <text x={PAD_L} y={H - 4} className="fill-ink-400 text-[9px]">
          {shortDate(history[0].date)}
        </text>
        <text x={W - 8} y={H - 4} textAnchor="end" className="fill-ink-400 text-[9px]">
          {shortDate(history[n - 1].date)}
        </text>
      </svg>
    </div>
  );
}
