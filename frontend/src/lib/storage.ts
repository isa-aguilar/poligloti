// localStorage keys shared across screens.
export const LS_USER = "poligloti.user";
export const LS_LANG = "poligloti.lang";

// --- Teacher voice settings (per learner) ----------------------------------

/** Server voice id for this learner and language (null = the default). */
export function getVoice(user: string, lang: string): string | null {
  return localStorage.getItem(`poligloti.voice.${user}.${lang}`);
}

export function setVoice(user: string, lang: string, voice: string | null): void {
  const key = `poligloti.voice.${user}.${lang}`;
  if (voice) localStorage.setItem(key, voice);
  else localStorage.removeItem(key);
}

/** On-device voice (voiceURI), used when the server has no voice for the language.
 * Kept apart from the server voice: sending it to the backend would be invalid. */
export function getBrowserVoice(user: string, lang: string): string | null {
  return localStorage.getItem(`poligloti.browserVoice.${user}.${lang}`);
}

export function setBrowserVoice(user: string, lang: string, voice: string | null): void {
  const key = `poligloti.browserVoice.${user}.${lang}`;
  if (voice) localStorage.setItem(key, voice);
  else localStorage.removeItem(key);
}

/** Speech rate as a length scale (bigger = slower; null = normal). */
export function getRate(user: string): number | null {
  const raw = localStorage.getItem(`poligloti.rate.${user}`);
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) && n !== 1.0 ? n : null;
}

export function setRate(user: string, rate: number | null): void {
  const key = `poligloti.rate.${user}`;
  if (rate && rate !== 1.0) localStorage.setItem(key, String(rate));
  else localStorage.removeItem(key);
}
