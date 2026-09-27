import en from "./en.json";
import es from "./es.json";
import de from "./de.json";

// Adding a new UI language (e.g. French):
//   1. Create `fr.json` by copying `en.json` (the base) and translating its values.
//   2. Import it here and add it to `bundles` below.
//   3. (optional) Short label in `UI_LANG_LABEL` in `components/UiLangToggle.tsx`.
//   4. Register the language name in the backend's `UI_LANG_NAMES` (config.py),
//      so the generated content of "My progress" is translated too.
// The UI language toggle picks it up through `availableLocales()`. Keys missing
// in the new bundle fall back to the base language (English), never to the raw key.

// Base language: source of truth for the keys, and the fallback when another
// bundle has no translation for a key yet.
const BASE_LOCALE = "en";

const bundles: Record<string, Record<string, string>> = { en, es, de };
const LS_LOCALE = "poligloti.uilang";

let current = BASE_LOCALE;
try {
  const saved = localStorage.getItem(LS_LOCALE);
  if (saved && bundles[saved]) current = saved;
} catch {
  /* localStorage unavailable (SSR / private mode): stay on the base */
}

// Mirror the UI language in <html lang> for accessibility (screen readers)
// and SEO. Centralized here so no screen forgets it.
function applyDocumentLang(locale: string) {
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }
}
applyDocumentLang(current);

// Development-only warning: keys missing from (or extra in) any bundle compared
// with the base, so a new language is not left half done unnoticed.
if (import.meta.env.DEV) {
  const baseKeys = Object.keys(bundles[BASE_LOCALE]);
  for (const [locale, bundle] of Object.entries(bundles)) {
    if (locale === BASE_LOCALE) continue;
    const missing = baseKeys.filter((k) => !(k in bundle));
    const extra = Object.keys(bundle).filter((k) => !(k in bundles[BASE_LOCALE]));
    if (missing.length) {
      console.warn(
        `[i18n] "${locale}" untranslated (falls back to ${BASE_LOCALE}): ${missing.join(", ")}`,
      );
    }
    if (extra.length) {
      console.warn(
        `[i18n] "${locale}" has keys that are not in ${BASE_LOCALE}: ${extra.join(", ")}`,
      );
    }
  }
}

export function getLocale(): string {
  return current;
}

export function availableLocales(): string[] {
  return Object.keys(bundles);
}

export function setLocale(locale: string) {
  if (!bundles[locale]) return;
  current = locale;
  applyDocumentLang(locale);
  try {
    localStorage.setItem(LS_LOCALE, locale);
  } catch {
    /* ignore */
  }
}

export function t(key: string): string {
  return bundles[current]?.[key] ?? bundles[BASE_LOCALE]?.[key] ?? key;
}
