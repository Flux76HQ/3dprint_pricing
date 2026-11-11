// What the service worker (frontend/sw.js) answers from its cache and what it asks the server for.
//
//   node scripts/test_service_worker.mjs          (CI: job `frontend-syntax`)
//
// The worker is run here as the browser runs it, with a cache and a network that only count: a file of the running release comes from
// the cache without a request, the page itself always comes from the network (a new release must show up on the very next load), a URL
// of another release is never answered from memory, a development build caches nothing first, and the caches of earlier releases are
// removed. Numbers and the reasoning: docs/performance.md.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SOURCE = readFileSync(new URL('../frontend/sw.js', import.meta.url), 'utf8');
const ORIGIN = 'https://print.example';
const DEV_LINE = "const APP_VERSION = 'dev';";
assert.ok(SOURCE.includes(DEV_LINE), 'sw.js must keep the line the server replaces');

/** A worker of one build with a fake cache and network. `stores` may hold the caches an earlier worker left. */
function start(appVersion, stores = new Map()) {
  const world = { stores, requests: [], online: true, handlers: {} };
  const absolute = (request) => new URL(typeof request === 'string' ? request : request.url, ORIGIN).href;
  const find = (store, request, options = {}) => {
    const wanted = new URL(absolute(request));
    for (const [url, response] of store) {
      const have = new URL(url);
      if (options.ignoreSearch ? have.origin + have.pathname === wanted.origin + wanted.pathname : url === wanted.href) return response;
    }
    return undefined;
  };
  const fetch = async (request) => {
    if (!world.online) throw new TypeError('offline');
    world.requests.push(absolute(request));
    const response = { ok: true, url: absolute(request), nth: world.requests.length, clone: () => response };
    return response;
  };
  const store = (name) => {
    if (!world.stores.has(name)) world.stores.set(name, new Map());
    const entries = world.stores.get(name);
    return {
      addAll: async (urls) => { for (const url of urls) entries.set(absolute(url), await fetch(url)); },
      put: async (request, response) => { entries.set(absolute(request), response); },
      match: async (request, options) => find(entries, request, options),
    };
  };
  const caches = {
    open: async (name) => store(name),
    keys: async () => [...world.stores.keys()],
    delete: async (name) => world.stores.delete(name),
    match: async (request, options) => {
      for (const entries of world.stores.values()) {
        const hit = find(entries, request, options);
        if (hit) return hit;
      }
      return undefined;
    },
  };
  const self = {
    addEventListener: (type, handler) => { world.handlers[type] = handler; },
    skipWaiting: async () => {},
    clients: { claim: async () => {} },
    location: new URL(`${ORIGIN}/sw.js`),
  };
  vm.runInNewContext(SOURCE.replace(DEV_LINE, `const APP_VERSION = '${appVersion}';`), { self, caches, fetch, location: self.location, URL, Promise });

  world.lifecycle = async (type) => {
    let done;
    world.handlers[type]({ waitUntil: (promise) => { done = promise; } });
    await done;
  };
  /** The answer to a request, or null when the worker leaves it to the browser. `asked` says whether the server was asked for it. */
  world.get = async (path, { mode = 'cors', method = 'GET' } = {}) => {
    const before = world.requests.length;
    let answer = null;
    world.handlers.fetch({ request: { url: `${ORIGIN}${path}`, method, mode }, respondWith: (promise) => { answer = promise; } });
    if (answer === null) return null;
    const response = await answer;
    await new Promise((resolve) => setTimeout(resolve, 0));              // a cache.put that was not waited for
    return { response, asked: world.requests.length > before };
  };
  return world;
}

const TOKEN = '1.2.3-abc1234';
const CACHE = `pp-shell-${TOKEN}`;

// --- a release build ----------------------------------------------------------------------------------------------------------------
{
  const left = new Map([['pp-shell-v2', new Map([[`${ORIGIN}/js/main.js`, { ok: true, old: true }]])],
    ['pp-shell-1.2.2-0000000', new Map([[`${ORIGIN}/js/main.js?v=1.2.2-0000000`, { ok: true, old: true }]])]]);
  const sw = start('1.2.3 (abc1234)', left);

  await sw.lifecycle('install');
  const cached = [...sw.stores.get(CACHE).keys()];
  assert.ok(cached.includes(`${ORIGIN}/`), 'the page is cached for offline use');
  assert.ok(cached.includes(`${ORIGIN}/js/main.js?v=${TOKEN}`) && cached.includes(`${ORIGIN}/css/app.css?v=${TOKEN}`) && cached.includes(`${ORIGIN}/lang/nl.json?v=${TOKEN}`),
    'the files of the release are cached under the URLs the page asks for');
  assert.ok(!cached.includes(`${ORIGIN}/js/main.js`), 'not under a URL the page never asks for');

  await sw.lifecycle('activate');
  assert.deepEqual([...sw.stores.keys()], [CACHE], 'the caches of earlier releases are removed');

  // A file of this release: from the cache, the server is not asked.
  for (const path of [`/js/main.js?v=${TOKEN}`, `/js/settings.js?v=${TOKEN}`, `/css/app.css?v=${TOKEN}`, `/lang/en.json?v=${TOKEN}`]) {
    const got = await sw.get(path);
    assert.equal(got.asked, false, `${path} is answered from the cache`);
    assert.equal(got.response.url, `${ORIGIN}${path}`);
  }
  // One that was not cached at install is fetched once and then kept.
  assert.equal((await sw.get(`/icons/favicon-32.png?v=${TOKEN}`)).asked, true);
  assert.equal((await sw.get(`/icons/favicon-32.png?v=${TOKEN}`)).asked, false);

  // The page itself: always the network, although a copy is in the cache.
  for (let n = 0; n < 2; n += 1) assert.equal((await sw.get('/', { mode: 'navigate' })).asked, true, 'a navigation asks the server every time');
  // Another release's URL, a URL without one, and the home screen icon's (new on every load): the server, every time.
  for (const path of ['/js/main.js?v=1.2.2-0000000', '/js/main.js?v=9.9.9-fffffff', '/js/main.js', '/manifest.webmanifest', `/icons/apple-touch-icon.png?v=${TOKEN}.18c`]) {
    for (let n = 0; n < 2; n += 1) assert.equal((await sw.get(path)).asked, true, `${path} is not answered from memory`);
  }
  // The API and anything that is not a GET are not the worker's business.
  assert.equal(await sw.get('/api/projects'), null);
  assert.equal(await sw.get(`/api/project-images/x/thumb?v=${TOKEN}`), null);
  assert.equal(await sw.get('/healthz'), null);
  assert.equal(await sw.get(`/js/main.js?v=${TOKEN}`, { method: 'POST' }), null);

  // Without a network the shell still starts: the cached page, the release's files, and what was fetched before.
  sw.online = false;
  assert.equal((await sw.get('/', { mode: 'navigate' })).response.url, `${ORIGIN}/`);
  assert.equal((await sw.get(`/js/main.js?v=${TOKEN}`)).response.url, `${ORIGIN}/js/main.js?v=${TOKEN}`);
  assert.equal((await sw.get('/manifest.webmanifest')).response.url, `${ORIGIN}/manifest.webmanifest`);
}

// --- a development build: the files change under the same name, so nothing is answered from the cache first ------------------------------
for (const version of ['dev', '1.2.3 (dev)']) {
  const sw = start(version);
  await sw.lifecycle('install');
  await sw.lifecycle('activate');
  assert.deepEqual([...sw.stores.keys()], ['pp-shell-dev']);
  assert.ok(sw.stores.get('pp-shell-dev').has(`${ORIGIN}/js/main.js`), 'cached for offline use under the plain URL');
  for (const path of ['/js/main.js?v=1.2.3-dev', '/js/main.js?v=dev-dev', '/js/main.js', '/css/app.css?v=1.2.3-dev']) {
    for (let n = 0; n < 2; n += 1) assert.equal((await sw.get(path)).asked, true, `${version}: ${path} comes from the server`);
  }
  sw.online = false;
  assert.equal((await sw.get('/js/main.js?v=1.2.3-dev')).response.url, `${ORIGIN}/js/main.js`, 'offline falls back to the cached file');
}

console.log('service worker: ok');
