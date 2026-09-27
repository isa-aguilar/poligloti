/**
 * Event channel for on-the-fly speed changes.
 *
 * Why it exists: RateToggle lives in the TalkInner header (a sibling of
 * ActiveSession), but the `<audio>` and the queue live INSIDE ActiveSession
 * (in useVoiceTurn). Passing a handler up through props was fragile at
 * registration time.
 *
 * A global EventTarget avoids lifting state: RateToggle emits the event on
 * tap, and useVoiceTurn subscribes on mount. No effect timing, no re-renders.
 */
const rateTarget: EventTarget = new EventTarget();

export const RATE_CHANGE_EVENT = "poligloti:rate-change";

export function emitRateChange(ls: number | null): void {
  rateTarget.dispatchEvent(new CustomEvent(RATE_CHANGE_EVENT, { detail: ls }));
}

export function onRateChange(cb: (ls: number | null) => void): () => void {
  const handler = (e: Event) => {
    const ls = (e as CustomEvent<number | null>).detail;
    cb(ls);
  };
  rateTarget.addEventListener(RATE_CHANGE_EVENT, handler);
  return () => rateTarget.removeEventListener(RATE_CHANGE_EVENT, handler);
}
