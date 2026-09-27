/**
 * Name and flag of a target language. The ONLY place in the frontend with
 * something per language.
 *
 * It exists because a copied `lang === "de" ? ... : ...` silently labels any
 * newly added language as the other branch. If you need a language name,
 * import it from here; do not write another ternary.
 *
 * Adding a language = one line in FLAGS + the `lang.<code>` key in the i18n files.
 */
import type { Lang, LanguageInfo } from "./api";
import { t } from "@/i18n";

const FLAGS: Record<string, string> = {
  de: "🇩🇪",
  en: "🇬🇧",
  fr: "🇫🇷",
};

/** Used only when the backend catalog (`GET /voices`) is not available. */
export const FALLBACK_LANGS: Lang[] = ["de", "en", "fr"];

export function flagFor(lang: Lang): string {
  return FLAGS[lang] ?? "🏳️";
}

/**
 * Name in the UI language. If the i18n key is missing, falls back to the name
 * given by the backend (`GET /voices`, languages) and finally to the code:
 * never to another language.
 */
export function langLabel(lang: Lang, catalog: LanguageInfo[] = []): string {
  const key = `lang.${lang}`;
  const translated = t(key);
  if (translated !== key) return translated;
  return catalog.find((l) => l.code === lang)?.name ?? lang.toUpperCase();
}
