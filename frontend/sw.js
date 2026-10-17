// Offline shell: static files are cached, the API never is (prices must be live).
// Network first, cache only as the offline fallback: a new release must show up on the very next
// load, not the one after (stale-while-revalidate served the old interface once more).
const CACHE = 'pp-shell-v2';
const SHELL = ['/', '/css/app.css', '/js/main.js', '/js/api.js', '/js/ui.js', '/js/auth-views.js',
  '/js/resources.js', '/js/projects.js', '/js/settings.js', '/js/theme-boot.js', '/icons/icon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz' || url.pathname === '/readyz') return;

  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/')));
    return;
  }
  event.respondWith(fetch(req).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
    }
    return res;
  }).catch(() => caches.match(req)));
});
