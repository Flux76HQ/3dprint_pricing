// The server replaces the value below with the running release, so every release changes this file's
// bytes and browsers notice an update.
const APP_VERSION = 'dev';

// The release as it is written in the URLs of this release's files (`?v=<version>-<commit>`, see backend/app/static_files.py);
// null for a development build, whose files change under the same name and are therefore never answered from the cache.
const RELEASE = /^(\S+) \((\w+)\)$/.exec(APP_VERSION);
const TOKEN = RELEASE && RELEASE[2] !== 'dev' ? `${RELEASE[1]}-${RELEASE[2]}` : null;

// Offline shell: the app's own files are cached, the API never is (prices must be live).
// One cache per release: activating a new worker removes the caches of the releases before it, so nothing old is kept or served.
const CACHE = `pp-shell-${TOKEN || 'dev'}`;
// The page, and the files of this release that every screen needs. Every module under /js is listed (a test compares the folder
// with this list), so the installed app starts without the network after its first visit.
const PAGE = '/';
const SHELL = ['/css/app.css', '/js/main.js', '/js/ai-images.js', '/js/api.js', '/js/auth-views.js', '/js/build.js', '/js/bulk-scan.js', '/js/customers.js',
  '/js/filament-library.js', '/js/filament-ui.js', '/js/i18n.js', '/js/install.js', '/js/langswitch.js', '/js/listview.js', '/js/integrations.js', '/js/listing.js', '/js/mdi.js', '/js/model-viewer.js', '/js/orders.js',
  '/js/password.js', '/js/projects.js', '/js/push.js', '/js/pwa.js', '/js/release.js', '/js/resources.js', '/js/scanner.js', '/js/settings.js', '/js/spoolman.js',
  '/js/theme-boot.js', '/js/ui.js', '/js/updates.js', '/js/users.js', '/lang/nl.json', '/lang/en.json'];
const versioned = (path) => (TOKEN ? `${path}?v=${TOKEN}` : path);

self.addEventListener('install', (event) => {
  // The same URLs the page asks for, so the browser's own cache answers what the page has just loaded.
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll([PAGE, '/icons/icon.svg', ...SHELL.map(versioned)])).then(() => self.skipWaiting()));
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

  // The page itself always comes from the network: a new release must show up on the very next load, not the one after
  // (stale-while-revalidate served the old interface once more). The cached page is only the offline fallback.
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match(PAGE, { ignoreSearch: true })));
    return;
  }
  // A file of this release never changes under its URL: answer it from the cache, and ask the server only for what is not there yet.
  // A URL of another release (a page that was open during an update) is not this worker's to answer from memory.
  if (TOKEN && url.searchParams.get('v') === TOKEN) {
    event.respondWith(caches.open(CACHE).then((c) => c.match(req, { ignoreVary: true }).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) c.put(req, res.clone());
      return res;
    }))));
    return;
  }
  // Everything else (icons, the manifest, a development build): network first, the cache only as the offline fallback.
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
