import { api } from './api.js';
import { t } from './i18n.js';
import { goTo } from './pwa.js';
import { h, showBanner } from './ui.js';

// "A newer release exists on GitHub" (App-Guidance shared/guidelines/update-check.md). Not to be confused with updates.js, which
// notices that the *server* was updated since this page loaded. The server reads GitHub and remembers the answer, so asking
// once after sign-in costs nothing; this only announces, it never updates anything. Only the signed-in owner gets here.
const LATER_KEY = 'pp-release-later';          // the version the owner dismissed: the banner returns for an even newer one

let state = null;                              // the last answer of /api/update, or null when the server could not be asked
let banner = null;

function dismissed() {
  try { return localStorage.getItem(LATER_KEY) || ''; } catch { return ''; }          // storage can be absent
}

function dismiss(version) {
  try { localStorage.setItem(LATER_KEY, version); } catch { /* storage can be absent */ }
}

export const releaseStatus = () => state;
export const releaseAvailable = () => !!state?.available;

/** Draws the banner and the dot on the navigation entries that lead to Settings from the last answer. */
function apply() {
  banner?.close();
  banner = null;
  document.querySelectorAll('.nav-dot').forEach((dot) => { dot.hidden = !releaseAvailable(); });
  if (!releaseAvailable() || dismissed() === state.latest) return;
  const shown = showBanner('release', {
    text: t('release.banner', { latest: `v${state.latest}`, current: `v${state.current}` }),
    actions: [
      h('button', { class: 'btn small primary', type: 'button', onclick: () => { shown.close(); goTo('#/instellingen/systeem'); } }, t('release.view')),
      h('button', { class: 'btn small', type: 'button', onclick: () => { dismiss(state.latest); shown.close(); } }, t('updates.later')),
    ],
  });
  banner = shown;
}

async function ask(method, path) {
  try {
    state = await api(method, path, method === 'POST' ? {} : undefined);
  } catch { /* the server cannot be reached: keep what we had; the page has its own error for that */ }
  apply();
  return state;
}

/** After sign-in. */
export const initRelease = () => ask('GET', '/api/update');

/** "Check now": the server still holds it to a floor of 30 seconds. */
export const checkRelease = () => ask('POST', '/api/update/check');

/** A language was picked: the banner is worded again. */
export const redrawRelease = () => apply();

/** Signed out (or reset): nothing of the owner's stays on the screen. */
export function stopRelease() {
  state = null;
  apply();
}
