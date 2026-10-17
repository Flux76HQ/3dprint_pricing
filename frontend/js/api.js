import { getLanguage, t } from './i18n.js';

// The server words its messages in the language the screen is in.
const langHeader = () => ({ 'X-Lang': getLanguage() });

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body === undefined ? langHeader() : { ...langHeader(), 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, t('api.no_connection'));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/api/auth/')) window.dispatchEvent(new Event('auth:expired'));
    throw new ApiError(res.status, data.error || t('api.error_status', { status: res.status }));
  }
  return data;
}

export async function upload(path, formData) {
  let res;
  try {
    res = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: langHeader(), body: formData });
  } catch {
    throw new ApiError(0, t('api.no_connection'));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.error || t('api.error_status', { status: res.status }));
  return data;
}

// --- passkeys ------------------------------------------------------------------

const toBuf = (b64u) => {
  const pad = '='.repeat((4 - (b64u.length % 4)) % 4);
  const bin = atob((b64u + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer;
};
const toB64u = (buf) => {
  let s = '';
  new Uint8Array(buf).forEach((b) => { s += String.fromCharCode(b); });
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

export function passkeySupport() {
  if (!window.isSecureContext) {
    return t('passkey.https_only');
  }
  if (!window.PublicKeyCredential) return t('passkey.unsupported');
  return null;
}

async function ceremony(run) {
  const problem = passkeySupport();
  if (problem) throw new ApiError(0, problem);
  try {
    return await run();
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (e?.name === 'NotAllowedError') throw new ApiError(0, t('passkey.cancelled'));
    if (e?.name === 'InvalidStateError') throw new ApiError(0, t('passkey.already_here'));
    throw new ApiError(0, t('passkey.failed', { message: e?.message || e }));
  }
}

export function createPasskey(options) {
  return ceremony(async () => {
    const cred = await navigator.credentials.create({
      publicKey: {
        ...options,
        challenge: toBuf(options.challenge),
        user: { ...options.user, id: toBuf(options.user.id) },
        excludeCredentials: options.excludeCredentials.map((c) => ({ ...c, id: toBuf(c.id) })),
      },
    });
    return {
      id: cred.id, rawId: toB64u(cred.rawId), type: cred.type,
      response: {
        clientDataJSON: toB64u(cred.response.clientDataJSON),
        attestationObject: toB64u(cred.response.attestationObject),
        transports: cred.response.getTransports ? cred.response.getTransports() : [],
      },
    };
  });
}

export function getPasskey(options) {
  return ceremony(async () => {
    const cred = await navigator.credentials.get({
      publicKey: {
        ...options,
        challenge: toBuf(options.challenge),
        allowCredentials: options.allowCredentials.map((c) => ({ ...c, id: toBuf(c.id) })),
      },
    });
    const r = cred.response;
    return {
      id: cred.id, rawId: toB64u(cred.rawId), type: cred.type,
      response: {
        clientDataJSON: toB64u(r.clientDataJSON), authenticatorData: toB64u(r.authenticatorData),
        signature: toB64u(r.signature), userHandle: r.userHandle ? toB64u(r.userHandle) : null,
      },
    };
  });
}

// Fresh passkey confirmation for an action that destroys or changes access.
export async function confirmWithPasskey(action, target) {
  const options = await api('POST', '/api/auth/stepup/options', { action, target });
  return getPasskey(options);
}
