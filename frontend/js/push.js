import { api } from './api.js';
import { t } from './i18n.js';
import { isStandalone } from './pwa.js';
import { isIOS } from './install.js';
import { h, showBanner, toast } from './ui.js';

// Web push, client side. The server decides what is sent and on which terms; this only subscribes the
// device. iOS delivers web push to installed apps only (16.4+), and only after a tap, so the
// permission request must come straight from a click handler.

/** { ok: true } or { ok: false, reason: 'ios-install' | 'unsupported' | 'denied' } */
export function pushSupport() {
  const capable = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  if (!capable) return { ok: false, reason: isIOS() && !isStandalone() ? 'ios-install' : 'unsupported' };
  if (isIOS() && !isStandalone()) return { ok: false, reason: 'ios-install' };
  if (Notification.permission === 'denied') return { ok: false, reason: 'denied' };
  return { ok: true };
}

const toKey = (b64u) => {
  const pad = '='.repeat((4 - (b64u.length % 4)) % 4);
  const raw = atob((b64u + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};

export async function currentSubscription() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

const OPT_OUT = 'pp-push-optout';          // this device was switched off on purpose: never switch it on by itself
const SNOOZED = 'pp-push-snoozed';         // "not now" on the offer below
const SNOOZE_MS = 14 * 24 * 3600 * 1000;

const remembered = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
const remember = (key, value) => { try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* private mode */ } };

export async function enablePush(publicKey) {
  remember(OPT_OUT, null);
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new Error(t('push.permission_denied'));
  const reg = await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription())
    || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toKey(publicKey) }));
  const { endpoint, keys } = sub.toJSON();
  await api('POST', '/api/push/subscribe', { endpoint, keys });
}

export async function disablePush() {
  remember(OPT_OUT, '1');
  const sub = await currentSubscription();
  if (!sub) return;
  const { endpoint } = sub.toJSON();
  await sub.unsubscribe();
  await api('POST', '/api/push/unsubscribe', { endpoint });
}

/** Matches `fingerprint` from /api/push/devices: how this device finds itself in the list. */
export async function thisDeviceFingerprint() {
  const sub = await currentSubscription().catch(() => null);
  if (!sub) return null;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(sub.endpoint));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
}

/**
 * When the app runs as an installed PWA (pinned to the home screen), notifications are offered at once: one tap on
 * the banner turns them on. The tap matters: iOS (and Chrome, politely) only show the permission question after
 * a user action. Where the permission was already given but this device is not subscribed, it just subscribes.
 * Never when the device was switched off on purpose, when "not now" was chosen lately, when the server has no
 * keys, or when the browser (or iOS before 16.4) cannot do push.
 */
export async function maybeOfferPush() {
  if (!isStandalone() || !pushSupport().ok || remembered(OPT_OUT)) return;
  if (Date.now() - Number(remembered(SNOOZED) || 0) < SNOOZE_MS) return;
  let cfg;
  try { cfg = await api('GET', '/api/push/config'); } catch { return; }
  if (!cfg.configured || await currentSubscription().catch(() => null)) return;
  if (Notification.permission === 'granted') { await enablePush(cfg.public_key).catch(() => {}); return; }
  if (Notification.permission !== 'default') return;
  const banner = showBanner('push', {
    text: t('push.offer'),
    actions: [
      h('button', { class: 'btn small primary', type: 'button', onclick: async () => {
        try { await enablePush(cfg.public_key); toast(t('push.enabled')); } catch (e) { toast(e.message, 'error'); }
        banner.close();
      } }, t('push.turn_on')),
      h('button', { class: 'btn small', type: 'button', onclick: () => { remember(SNOOZED, String(Date.now())); banner.close(); } }, t('install.not_now')),
    ],
  });
}
