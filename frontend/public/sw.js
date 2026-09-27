// Minimal poligloti service worker.
// Single goal: opening the PWA when the server cannot be reached shows a
// useful screen instead of the browser's network error.
//
// - Navigations: network first (never stale HTML after a deploy); on failure,
//   the offline.html cached at install time.
// - Static assets (hashed /assets/*, icons, manifest): cache first, they are
//   immutable by name.
// - API and /audio: straight to the network, no cache (the app handles errors).

const CACHE = "poligloti-shell-v1";
const OFFLINE_URL = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll([OFFLINE_URL])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE_URL)));
    return;
  }

  const url = new URL(req.url);
  const isStaticAsset =
    url.pathname.startsWith("/assets/") ||
    url.pathname === "/manifest.webmanifest" ||
    /\.(png|svg|ico)$/.test(url.pathname);
  if (isStaticAsset) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const clone = res.clone();
              caches.open(CACHE).then((cache) => cache.put(req, clone));
            }
            return res;
          }),
      ),
    );
  }
  // Everything else (API, /audio): straight to the network.
});
