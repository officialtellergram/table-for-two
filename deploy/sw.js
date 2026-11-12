/* Table for Two — service worker.
   The page and its scripts are network-first (so a deploy shows on the very next
   load, with the cache as the offline fallback); icons, art and fonts are
   cache-first; city data is always fetched fresh so the radar feed never goes stale. */
const CACHE = 't42-v97';   // bump on deploy so stale shells are swept on activate
const SHELL = [
  './', './index.html', './manifest.webmanifest',
  './icons/icon-192.png', './icons/icon-512.png', './icons/apple-touch-icon.png',
  './icons/favicon.png', './icons/mark.png', './icons/favicon.svg', './icons/glyph.svg',
  './web/config.js', './web/auth.js', './web/concierge.js'
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

function fresh(req, url) {
  // Network first; a good same-origin answer refreshes the cache for offline use.
  return fetch(req).then(res => {
    if (res.ok && url.origin === location.origin) {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy));
    }
    return res;
  });
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // Live data: network-first, cache only as an offline fallback.
  if (url.pathname.includes('/cities/')) {
    e.respondWith(fetch(req).catch(() => caches.match(req)));
    return;
  }
  // The page itself, its scripts and the manifest: network-first so deploys land
  // immediately; cached copy (or the cached page) when offline.
  const isShell = req.mode === 'navigate' || /\.(html|js|webmanifest)$/.test(url.pathname) || url.pathname.endsWith('/');
  if (isShell) {
    e.respondWith(fresh(req, url).catch(() => caches.match(req).then(hit => hit || caches.match('./index.html'))));
    return;
  }
  // Icons, art, fonts: cache-first, fill the cache in the background.
  e.respondWith(
    caches.match(req).then(hit => hit || fresh(req, url).catch(() => caches.match('./index.html')))
  );
});
