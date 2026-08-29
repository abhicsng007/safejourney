// SafeJourney PWA service worker.
//
// Goal: a new deploy takes effect immediately. We never serve index.html from a cache —
// it's always fetched fresh so it points at the newest content-hashed bundle — we activate
// the new worker right away (skipWaiting + clients.claim), and we drop any caches left by an
// older version on activate. Hashed assets are cached only as an offline fallback.
const CACHE = "safejourney-v2";

self.addEventListener("install", (e) => {
  self.skipWaiting();
  // Precache the shell so the app still opens offline (online path stays fresh via no-store).
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(["/", "/index.html"]).catch(() => {}))
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    // Remove caches from previous versions so no stale app shell survives a deploy.
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Navigations / HTML: always hit the network, bypassing the HTTP cache, so a deploy is
  // picked up on the very next load. Fall back to the cached shell only when offline.
  const isHTML =
    req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html");
  if (isHTML) {
    e.respondWith(
      fetch(req, { cache: "no-store" }).catch(
        () => caches.match(req).then((r) => r || caches.match("/index.html"))
      )
    );
    return;
  }

  // Content-hashed assets: network-first, cache the result for offline fallback.
  e.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(req))
  );
});
