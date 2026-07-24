/* Table for Two — service worker.
   App shell cached for offline/installability; city data always fetched fresh
   (falls back to cache only when offline) so the radar feed never goes stale. */
const CACHE = 't42-v23';   // bump to invalidate the cached shell on deploy
const SHELL = [
  './', './index.html', './manifest.webmanifest',
  './icons/icon-192.png', './icons/icon-512.png', './icons/apple-touch-icon.png',
  './icons/favicon.png', './icons/mark.png'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // Live data: network-first, cache only as an offline fallback.
  if (url.pathname.includes('/cities/')) {
    e.respondWith(fetch(req).catch(() => caches.match(req)));
    return;
  }
  // App shell + assets: cache-first, fill the cache in the background.
  e.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res.ok && url.origin === location.origin) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match('./index.html')))
  );
});
