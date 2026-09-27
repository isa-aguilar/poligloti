/**
 * On-device speech synthesis, used when the server has no voice for the
 * target language.
 *
 * Only voices with `localService === true` are used: the other ones send the
 * text to a cloud service without telling the learner, which breaks the
 * promise that the conversation stays on infrastructure the user chose.
 */

export function speechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

let snapshot: SpeechSynthesisVoice[] = speechSupported() ? window.speechSynthesis.getVoices() : [];

/** Subscribe to the voice list (it loads asynchronously in most browsers). */
export function subscribeVoices(cb: () => void): () => void {
  if (!speechSupported()) return () => undefined;
  const handler = () => {
    snapshot = window.speechSynthesis.getVoices();
    cb();
  };
  window.speechSynthesis.addEventListener("voiceschanged", handler);
  // Some browsers already have the list and never fire the event.
  const now = window.speechSynthesis.getVoices();
  if (now.length !== snapshot.length) handler();
  return () => window.speechSynthesis.removeEventListener("voiceschanged", handler);
}

export function voicesSnapshot(): SpeechSynthesisVoice[] {
  return snapshot;
}

/** On-device voices whose language starts with the target language code. */
export function localVoicesFor(
  voices: SpeechSynthesisVoice[],
  lang: string,
): SpeechSynthesisVoice[] {
  const prefix = lang.toLowerCase();
  return voices.filter((v) => v.localService && v.lang.toLowerCase().startsWith(prefix));
}

/**
 * The stored speech rate is the server's length scale (bigger = slower). The
 * browser uses a speed multiplier instead: slow 0.8, normal 1, fast 1.15.
 */
export function browserRate(lengthScale: number | null): number {
  if (!lengthScale || lengthScale === 1) return 1;
  return lengthScale > 1 ? 0.8 : 1.15;
}

/** Speak one text right away (cancels anything the browser was saying). */
export function speakNow(text: string, voice: SpeechSynthesisVoice, lengthScale: number | null) {
  if (!speechSupported() || !text.trim()) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.voice = voice;
  u.lang = voice.lang;
  u.rate = browserRate(lengthScale);
  window.speechSynthesis.speak(u);
}
