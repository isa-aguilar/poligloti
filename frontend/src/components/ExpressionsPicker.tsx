import { useState } from "react";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { t } from "@/i18n";

// The `topic` is sent to the backend as a free theme (the model reads it).
// The labels are localized; the theme sent is always an English description.
const PRESETS: { key: string; topic: string }[] = [
  { key: "expr.theme.work", topic: "meetings and the workplace" },
  { key: "expr.theme.dinner", topic: "dinner with colleagues" },
  { key: "expr.theme.travel", topic: "travel: airport, hotel, restaurant" },
  { key: "expr.theme.smalltalk", topic: "small talk and icebreakers" },
  { key: "expr.theme.daily", topic: "everyday life" },
];

export function ExpressionsPicker({ onPick }: { onPick: (topic?: string) => void }) {
  const [free, setFree] = useState("");

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {PRESETS.map((p) => (
          <button key={p.key} onClick={() => onPick(p.topic)} className="text-left">
            <Card className="p-4 h-full hover:border-accent-400 border border-transparent transition">
              <h3 className="font-semibold text-ink-900 dark:text-ink-50">{t(p.key)}</h3>
            </Card>
          </button>
        ))}
      </div>

      <div className="flex items-end gap-2">
        <input
          value={free}
          onChange={(e) => setFree(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && free.trim()) onPick(free.trim());
          }}
          placeholder={t("expr.free.placeholder")}
          className="flex-1 rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500"
        />
        <Button disabled={!free.trim()} onClick={() => onPick(free.trim())}>
          {t("setup.start")}
        </Button>
      </div>

      <button onClick={() => onPick(undefined)} className="text-sm text-accent-600 hover:underline">
        {t("expr.surprise")}
      </button>
    </div>
  );
}
