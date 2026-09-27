import { useEffect, useMemo, useState } from "react";
import { fetchScenarios, type Scenario } from "@/lib/api";
import { Card } from "@/components/Card";
import { t } from "@/i18n";
import { cn } from "@/lib/cn";

// Built-in categories first; custom ones (added under
// <DATA_DIR>/_shared/scenarios/) follow in the order they appear.
const BUILT_IN = ["work", "everyday"];

// Category label. Data driven: a new category shows its own name instead of
// falling into another category.
function catLabel(cat: string): string {
  const key = `scenario.cat.${cat}`;
  const tr = t(key);
  if (tr !== key) return tr;
  return cat.charAt(0).toUpperCase() + cat.slice(1);
}

export function ScenarioPicker({ onPick }: { onPick: (s: Scenario) => void }) {
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cat, setCat] = useState<string>(BUILT_IN[0]);

  useEffect(() => {
    fetchScenarios()
      .then(setScenarios)
      .catch((e) => setErr((e as Error).message));
  }, []);

  const categories = useMemo(() => {
    const extra = (scenarios ?? [])
      .map((s) => s.category)
      .filter((c, i, all) => !BUILT_IN.includes(c) && all.indexOf(c) === i);
    return [...BUILT_IN, ...extra];
  }, [scenarios]);

  const filtered = useMemo(
    () => (scenarios ?? []).filter((s) => s.category === cat),
    [scenarios, cat],
  );

  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-xl bg-ink-100 dark:bg-ink-800 p-1">
        {categories.map((c) => (
          <button
            key={c}
            onClick={() => setCat(c)}
            className={cn(
              "px-4 py-1.5 rounded-lg text-sm font-medium",
              cat === c ? "bg-white shadow text-ink-900" : "text-ink-600 dark:text-ink-300",
            )}
          >
            {catLabel(c)}
          </button>
        ))}
      </div>

      {err && (
        <p className="text-sm text-red-600">
          {t("select.error")}: {err}
        </p>
      )}
      {!scenarios && !err && <p className="text-sm text-ink-400">{t("scenario.loading")}</p>}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {filtered.map((s) => (
          <button key={s.id} onClick={() => onPick(s)} className="text-left">
            <Card className="p-4 h-full hover:border-accent-400 border border-transparent transition">
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-semibold text-ink-900 dark:text-ink-50">{s.title}</h3>
                {s.level && (
                  <span className="text-[10px] uppercase tracking-wider text-ink-400 shrink-0">
                    {s.level}
                  </span>
                )}
              </div>
              <p className="text-sm text-ink-500 mt-1">{s.description}</p>
            </Card>
          </button>
        ))}
      </div>
    </div>
  );
}
