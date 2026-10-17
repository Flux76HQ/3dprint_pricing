import { api } from './api.js';
import { t } from './i18n.js';
import { confirmDialog, h, showBanner, toast, versionLabel } from './ui.js';

// "A new version is available". The server reports its running release at /api/version; the page
// remembers what it loaded with. A difference means the server has been updated since, and the
// installed app (which can stay open for days) should offer to reload. Checked when the app comes back
// to the foreground, periodically, and whenever the browser finds a new service worker.
const CHECK_EVERY_MS = 15 * 60 * 1000;
const LATER_MS = 60 * 60 * 1000;

let loaded = null;
let dirty = false;
let snoozedUntil = 0;

/** The calculation editor calls this so an update never discards unsaved work without asking. */
export function setDirty(value) { dirty = value; }

export const isNewer = (current, running) => !!current && !!running && (current.version !== running.version || current.commit !== running.commit);

async function fetchVersion() {
  const res = await fetch('/api/version', { cache: 'no-store' });
  if (!res.ok) throw new Error('version');
  return res.json();
}

async function apply() {
  if (dirty && !(await confirmDialog(t('updates.unsaved'), t('updates.update')))) return;
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    await reg?.update();
    await Promise.all((await caches.keys()).map((key) => caches.delete(key)));    // never fall back to an old shell
  } catch { /* reload anyway */ }
  window.location.reload();
}

function show(running) {
  const banner = showBanner('update', {
    text: t('updates.available', { version: versionLabel(running) }),
    actions: [
      h('button', { class: 'btn small primary', type: 'button', onclick: apply }, t('updates.update_now')),
      h('button', { class: 'btn small', type: 'button', onclick: () => { snoozedUntil = Date.now() + LATER_MS; banner.close(); } }, t('updates.later')),
    ],
  });
}

/** Returns the running version, or null when the server cannot be reached. `manual` also reports "up to date". */
export async function checkForUpdate({ manual = false } = {}) {
  try {
    navigator.serviceWorker?.getRegistration().then((reg) => reg?.update()).catch(() => {});
    const running = await fetchVersion();
    if (isNewer(loaded, running)) {
      if (manual || Date.now() >= snoozedUntil) show(running);
    } else if (manual) {
      toast(t('updates.latest', { version: versionLabel(running) }));
    }
    return running;
  } catch {
    if (manual) toast(t('updates.check_failed'), 'error');
    return null;
  }
}

export function initUpdates(version) {
  loaded = version;
  document.addEventListener('visibilitychange', () => { if (!document.hidden) checkForUpdate(); });
  setInterval(checkForUpdate, CHECK_EVERY_MS);
  navigator.serviceWorker?.getRegistration().then((reg) => {
    reg?.addEventListener('updatefound', () => checkForUpdate());
  }).catch(() => {});
}

export const loadedVersion = () => loaded;
