import type { ProgressDim } from "@/lib/api";
import { t } from "@/i18n";

// Axis label in the UI language (by key); falls back to the backend label.
function dimLabel(d: ProgressDim): string {
  const key = `skill.${d.key}`;
  const tr = t(key);
  return tr === key ? d.label : tr;
}

// Spider chart of the 8 skills. Plain SVG, no dependencies.
export function RadarChart({ dims }: { dims: ProgressDim[] }) {
  const n = dims.length;
  if (n === 0) return null;
  const W = 340;
  const cx = W / 2;
  const cy = W / 2;
  const R = 110;
  const angle = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2; // starts at the top
  const at = (i: number, r: number): [number, number] => [
    cx + r * Math.cos(angle(i)),
    cy + r * Math.sin(angle(i)),
  ];
  const rings = [0.25, 0.5, 0.75, 1];
  const dataPoly = dims
    .map((d, i) => at(i, (R * Math.max(0, Math.min(100, d.score ?? 0))) / 100).join(","))
    .join(" ");

  // viewBox with a horizontal margin so the side labels are not clipped.
  return (
    <svg viewBox={`-80 -20 ${W + 160} ${W + 40}`} className="w-full max-w-md mx-auto" role="img">
      {/* concentric grid */}
      {rings.map((rr, ri) => (
        <polygon
          key={ri}
          points={dims.map((_, i) => at(i, R * rr).join(",")).join(" ")}
          className="fill-none stroke-ink-200 dark:stroke-ink-700"
          strokeWidth={1}
        />
      ))}
      {/* axes */}
      {dims.map((_, i) => {
        const [x, y] = at(i, R);
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={x}
            y2={y}
            className="stroke-ink-200 dark:stroke-ink-700"
            strokeWidth={1}
          />
        );
      })}
      {/* data polygon */}
      <polygon points={dataPoly} className="fill-accent-500/25 stroke-accent-500" strokeWidth={2} />
      {dims.map((d, i) => {
        const [x, y] = at(i, (R * Math.max(0, Math.min(100, d.score ?? 0))) / 100);
        return <circle key={i} cx={x} cy={y} r={2.5} className="fill-accent-600" />;
      })}
      {/* labels */}
      {dims.map((d, i) => {
        const [x, y] = at(i, R + 20);
        const anchor = Math.abs(x - cx) < 8 ? "middle" : x > cx ? "start" : "end";
        return (
          <text
            key={i}
            x={x}
            y={y}
            textAnchor={anchor}
            dominantBaseline="middle"
            className="fill-ink-600 dark:fill-ink-300 text-[10px]"
          >
            {dimLabel(d)} {d.score ?? "·"}
          </text>
        );
      })}
    </svg>
  );
}
