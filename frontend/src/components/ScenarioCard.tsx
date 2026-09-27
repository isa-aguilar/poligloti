import { useState } from "react";
import { Card } from "@/components/Card";
import { t } from "@/i18n";
import type { ScenarioInfo } from "@/lib/api";

export function ScenarioCard({ info }: { info: ScenarioInfo }) {
  const [open, setOpen] = useState(true);
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-ink-900 dark:text-ink-50">{info.title}</h3>
        <button
          onClick={() => setOpen((o) => !o)}
          className="text-xs text-accent-600 hover:underline shrink-0"
        >
          {open ? t("scenario.hide") : t("scenario.show")}
        </button>
      </div>
      {info.description && <p className="text-sm text-ink-500 mt-1">{info.description}</p>}

      {open && (
        <div className="mt-3 space-y-3">
          {info.vocab.length > 0 && (
            <div>
              <h4 className="text-xs uppercase tracking-wider text-ink-400 mb-1">
                {t("scenario.vocab")}
              </h4>
              <ul className="text-sm space-y-0.5">
                {info.vocab.map((v, i) => (
                  <li key={i} className="text-ink-700 dark:text-ink-200">
                    {v}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {info.phrases.length > 0 && (
            <div>
              <h4 className="text-xs uppercase tracking-wider text-ink-400 mb-1">
                {t("scenario.phrases")}
              </h4>
              <ul className="text-sm space-y-0.5 list-disc list-inside">
                {info.phrases.map((p, i) => (
                  <li key={i} className="text-ink-700 dark:text-ink-200">
                    {p}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
