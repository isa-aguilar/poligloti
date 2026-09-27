import { availableLocales, getLocale, setLocale } from "@/i18n";
import { cn } from "@/lib/cn";

const UI_LANG_LABEL: Record<string, string> = { en: "EN", es: "ES", de: "DE" };

/**
 * INTERFACE language (not the language being studied). It lives on several
 * screens: changing it should not force leaving the session.
 *
 * React does not see a locale change on its own (t() is not a hook), so the
 * caller passes `onChange` to re-render its tree.
 */
export function UiLangToggle({ onChange }: { onChange?: (l: string) => void }) {
  const current = getLocale();
  return (
    <div className="inline-flex rounded-lg bg-ink-100 dark:bg-ink-800 p-0.5">
      {availableLocales().map((l) => (
        <button
          key={l}
          onClick={() => {
            setLocale(l);
            onChange?.(l);
          }}
          className={cn(
            "px-2.5 py-1 rounded-md text-xs font-semibold",
            current === l ? "bg-white shadow text-ink-900" : "text-ink-500",
          )}
          aria-pressed={current === l}
        >
          {UI_LANG_LABEL[l] ?? l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
