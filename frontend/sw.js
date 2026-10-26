// The server replaces the value below with the running release, so every release changes this file's
// bytes and browsers notice an update.
const APP_VERSION = 'dev';

// Offline shell: static files are cached, the API never is (prices must be live).
// Network first, cache only as the offline fallback: a new release must show up on the very next
// load, not the one after (stale-while-revalidate served the old interface once more).
const CACHE = 'pp-shell-v2';
const SHELL = ['/', '/css/app.css', '/js/main.js', '/js/api.js', '/js/ui.js', '/js/auth-views.js',
  '/js/resources.js', '/js/projects.js', '/js/orders.js', '/js/customers.js', '/js/filament-ui.js', '/js/filament-library.js', '/js/spoolman.js', '/js/mdi.js', '/js/settings.js', '/js/pwa.js', '/js/scanner.js', '/js/theme-boot.js', '/js/i18n.js', '/js/langswitch.js', '/lang/nl.json', '/lang/en.json', '/icons/icon.svg'];

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
    event.respondWith(fetch(req).catch(() => caches.match('/', { ignoreSearch: true })));
    return;
  }
  event.respondWith(fetch(req).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
    }
    return res;
  }).catch(() => caches.match(req, { ignoreSearch: true })));
});

// --- Web push -------------------------------------------------------------------------------------
// Deliberately plain: no requireInteraction and no vibration pattern. The app does not try to break
// through a Focus / Do Not Disturb mode; interruptions are the user's setting to make on their device.
// (backend/tests/test_push.py fails if either option appears here.)
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { body: event.data ? event.data.text() : '' };
  }
  // Every push must show something (userVisibleOnly), so fall back to a generic text.
  const options = {
    body: data.body || '',
    icon: '/icons/icon-192.png',
    tag: data.tag || undefined,
    silent: data.silent !== false,
    data: { url: typeof data.url === 'string' && data.url.startsWith('/') ? data.url : '/' },
  };
  event.waitUntil(self.registration.showNotification(data.title || '3D Print Pricing', options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
    for (const client of windows) {
      if ('focus' in client) {
        client.navigate(target).catch(() => {});
        return client.focus();
      }
    }
    return self.clients.openWindow(target);
  }));
});
