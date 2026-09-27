import { useState } from "react";
import { Button } from "@/components/Button";
import { createProfile, type Lang, type LanguageInfo } from "@/lib/api";
import { humanError } from "@/hooks/useSession";
import { FALLBACK_LANGS, flagFor, langLabel } from "@/lib/lang";
import { getLocale, t } from "@/i18n";
import { cn } from "@/lib/cn";

const inputClass =
  "w-full rounded-xl border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500";

/** Create a learner profile: name, language to learn and, optionally, goals. */
export function NewLearnerForm({
  catalog,
  onCreated,
  onCancel,
}: {
  catalog: LanguageInfo[];
  onCreated: (user: string, lang: Lang) => void;
  /** Absent when there is no other learner to go back to. */
  onCancel?: () => void;
}) {
  const [name, setName] = useState("");
  const [lang, setLang] = useState<Lang | null>(null);
  const [goals, setGoals] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const langs: Lang[] = catalog.length ? catalog.map((l) => l.code) : FALLBACK_LANGS;

  const submit = async () => {
    if (!name.trim() || !lang) return;
    setErr(null);
    setBusy(true);
    try {
      const res = await createProfile({
        name: name.trim(),
        target_language: lang,
        goals: goals.trim() || undefined,
        ui_language: getLocale(),
      });
      onCreated(res.user, res.primary_language);
    } catch (e) {
      setErr(humanError(e));
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-ink-600 dark:text-ink-400 mb-1">
          {t("newLearner.name")}
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("newLearner.name.placeholder")}
          autoComplete="off"
          className={inputClass}
        />
      </div>

      <div>
        <p className="text-sm font-medium text-ink-600 dark:text-ink-400 mb-2">
          {t("newLearner.lang")}
        </p>
        <div className="grid grid-cols-3 gap-2">
          {langs.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setLang(l)}
              className={cn(
                "h-12 rounded-xl border text-sm font-medium flex items-center justify-center gap-1.5 transition",
                lang === l
                  ? "border-accent-500 bg-accent-500/10 text-accent-700"
                  : "border-ink-200 hover:border-ink-400 text-ink-800 dark:border-ink-600 dark:text-ink-100",
              )}
            >
              <span className="text-lg">{flagFor(l)}</span>
              <span>{langLabel(l, catalog)}</span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-ink-600 dark:text-ink-400 mb-1">
          {t("newLearner.goals")}
        </label>
        <textarea
          value={goals}
          onChange={(e) => setGoals(e.target.value)}
          rows={3}
          placeholder={t("newLearner.goals.placeholder")}
          className={cn(inputClass, "resize-y")}
        />
        <p className="text-xs text-ink-400 mt-1">{t("newLearner.goals.hint")}</p>
      </div>

      {err && <p className="text-sm text-red-600">{err}</p>}

      <div className="flex items-center gap-2">
        <Button disabled={busy || !name.trim() || !lang} onClick={() => void submit()}>
          {busy ? t("newLearner.creating") : t("newLearner.create")}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {t("newLearner.cancel")}
          </Button>
        )}
      </div>
    </div>
  );
}
