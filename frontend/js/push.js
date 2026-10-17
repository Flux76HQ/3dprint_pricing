import { api } from './api.js';
import { t } from './i18n.js';
import { isStandalone } from './pwa.js';
import { isIOS } from './install.js';

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

export async function enablePush(publicKey) {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new Error(t('push.permission_denied'));
  const reg = await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription())
    || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toKey(publicKey) }));
  const { endpoint, keys } = sub.toJSON();
  await api('POST', '/api/push/subscribe', { endpoint, keys });
}

export async function disablePush() {
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
