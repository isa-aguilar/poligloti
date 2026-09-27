/**
 * PWA auto-refresh after a deploy.
 *
 * Problem: iOS "revives" the PWA with the JS it already had in memory when it
 * comes back to the foreground, without requesting the HTML again, so it
 * keeps the old build indefinitely (the service worker only brings new code on
 * a fresh navigation). Deployed features would not show up until the app is
 * closed by hand.
 *
 * Solution: when the app comes back to the foreground, fetch a fresh
 * index.html (network first through the SW) and read the bundle hash it
 * references. If it differs from the one running now (import.meta.url), reload.
 *
 * Guard: NEVER reload in the middle of an active session (the conversation
 * would be lost). Talk pauses the auto-refresh while a session is active.
 */

// JS file this module was loaded from (the entry hashed by Vite), e.g.
// "index-DgqJ9h80.js": the version running right now.
const RUNNING_BUNDLE = (() => {
  try {
    return import.meta.url.split("/").pop() ?? "";
  } catch {
    return "";
  }
})();

let paused = false;
let checking = false;

async function deployedBundle(): Promise<string | null> {
  try {
    const res = await fetch("/", { cache: "no-store" });
    if (!res.ok) return null;
    const html = await res.text();
    const m = html.match(/assets\/(index-[A-Za-z0-9_-]+\.js)/);
    return m ? m[1] : null;
  } catch {
    return null; // server unreachable: leave everything as it is
  }
}

async function checkAndReload(): Promise<void> {
  if (paused || checking || !RUNNING_BUNDLE) return;
  checking = true;
  try {
    const deployed = await deployedBundle();
    if (deployed && deployed !== RUNNING_BUNDLE) {
      window.location.reload();
    }
  } finally {
    checking = false;
  }
}

/** Called by Talk: true while a session is active (do not reload). */
export function setAutoUpdatePaused(p: boolean): void {
  paused = p;
}

export function initAutoUpdate(): void {
  if (!import.meta.env.PROD) return;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void checkAndReload();
  });
  // iOS does not always fire visibilitychange when it revives the PWA; 'focus'
  // covers those cases.
  window.addEventListener("focus", () => void checkAndReload());
}
