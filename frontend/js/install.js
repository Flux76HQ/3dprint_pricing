import { isStandalone } from './pwa.js';
import { t } from './i18n.js';
import { h, showBanner } from './ui.js';

// Installing as an app. Android/Chrome/Edge hand us `beforeinstallprompt`; iOS has no API at all, only
// Share -> Add to Home Screen, so there we can only explain. The listener is registered at load because
// the event can fire before any screen exists.
let deferred = null;
const listeners = new Set();
const DISMISSED_KEY = 'pp-install-dismissed';
const SNOOZE_MS = 14 * 24 * 3600 * 1000;

window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferred = e; changed(); });
window.addEventListener('appinstalled', () => { deferred = null; changed(); });

function changed() { listeners.forEach((fn) => fn()); }
export function onInstallChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export const isIOS = () => /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

/** 'installed' | 'prompt' (one tap installs) | 'ios' (explain Share -> Add to Home Screen) | 'unavailable' */
export function installState() {
  if (isStandalone()) return 'installed';
  if (deferred) return 'prompt';
  if (isIOS()) return 'ios';
  return 'unavailable';
}

export async function promptInstall() {
  if (!deferred) return 'unavailable';
  deferred.prompt();
  const { outcome } = await deferred.userChoice;
  deferred = null;
  changed();
  return outcome;                       // 'accepted' | 'dismissed'
}

export const iosSteps = () => t('install.ios_steps');

function snoozed() {
  try { return Date.now() - Number(localStorage.getItem(DISMISSED_KEY) || 0) < SNOOZE_MS; } catch { return false; }
}

/** A dismissible banner when the app can be installed and the person has not said "not now" lately. */
export function maybeShowInstallBanner() {
  const state = installState();
  if ((state !== 'prompt' && state !== 'ios') || snoozed()) return;
  const later = () => {
    try { localStorage.setItem(DISMISSED_KEY, String(Date.now())); } catch { /* private mode */ }
    banner.close();
  };
  const banner = showBanner('install', {
    text: state === 'prompt' ? t('install.banner_prompt') : t('install.banner_ios', { steps: iosSteps() }),
    actions: [
      state === 'prompt' ? h('button', { class: 'btn small primary', type: 'button', onclick: async () => { await promptInstall(); banner.close(); } }, t('install.install')) : null,
      h('button', { class: 'btn small', type: 'button', onclick: later }, state === 'prompt' ? t('install.not_now') : t('install.understood')),
    ],
  });
}

onInstallChange(() => { if (installState() === 'installed') document.getElementById('banners')?.querySelector('[data-banner=install]')?.remove(); else maybeShowInstallBanner(); });
