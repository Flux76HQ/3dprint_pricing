import { api, confirmWithPasskey } from './api.js';
import { t } from './i18n.js';
import { confirmDialog, enhanceDialog, h, switchRow, toast } from './ui.js';

// Optional password login, with optional two-step verification (an authenticator app).
// Passkeys stay the recommended way in; a password is the door for places where a passkey cannot work (an IP address on a home
// network), and it is off by default. Turning the password or the authenticator app on only needs the session you are in (it must
// work on a device without a passkey); changing the password, turning either off and new backup codes need a passkey confirmation,
// or the password (and a code, when there is an authenticator app) on a device where no passkey works.

const group = (secret) => secret.replace(/(.{4})/g, '$1 ').trim();

export function codesBlock(codes) {
  const text = codes.join('\n');
  return [
    h('ul', { class: 'codes', 'aria-label': t('pw.backup_codes') }, codes.map((c) => h('li', {}, c))),
    h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onclick: async () => {
        try { await navigator.clipboard.writeText(text); toast(t('common.copied')); } catch { toast(t('common.copy_failed'), 'error'); }
      } }, t('common.copy')),
      h('button', { class: 'btn', type: 'button', onclick: () => {
        const url = URL.createObjectURL(new Blob([`${text}\n`], { type: 'text/plain' }));
        h('a', { href: url, download: 'printpricing-backupcodes.txt' }).click();
        URL.revokeObjectURL(url);
      } }, t('common.download'))),
  ];
}

/** Choose a password. Resolves true once it is switched on. */
export function passwordDialog() {
  return new Promise((resolve) => {
    let done = false;
    const error = h('p', { class: 'error', role: 'alert', hidden: true });
    const fail = (message) => { error.textContent = message; error.hidden = !message; };
    const pw = h('input', { type: 'password', id: 'pw-new', autocomplete: 'new-password', required: true, minlength: 12 });
    const again = h('input', { type: 'password', id: 'pw-again', autocomplete: 'new-password', required: true });
    const submit = h('button', { class: 'btn primary', type: 'submit' }, t('pw.set'));
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, h('form', { class: 'stack', onsubmit: async (e) => {
      e.preventDefault();
      fail('');
      if (pw.value !== again.value) { fail(t('pw.mismatch')); return; }
      submit.disabled = true;
      try {
        await api('POST', '/api/auth/password/setup', { password: pw.value });
        done = true;
        dialog.close();
      } catch (err) { fail(err.message); submit.disabled = false; }
    } },
    h('h2', {}, t('pw.setup_title')),
    h('p', { class: 'muted' }, t('pw.setup_intro')),
    h('div', { class: 'field' }, h('label', { for: 'pw-new' }, t('pw.new')), pw, h('p', { class: 'hint' }, t('pw.new_hint'))),
    h('div', { class: 'field' }, h('label', { for: 'pw-again' }, t('pw.repeat')), again),
    error,
    h('div', { class: 'row end' }, h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')), submit))),
    { dirty: () => !!(pw.value || again.value) });
    dialog.addEventListener('close', () => { dialog.remove(); resolve(done); });
    document.body.append(dialog);
    dialog.showModal();
    pw.focus();
  });
}

/** Add an authenticator app: scan -> confirm a code -> backup codes. Resolves true once it is switched on. */
export function totpWizard() {
  return new Promise((resolve) => {
    let finished = false;
    const body = h('div', { class: 'stack' });
    let guard = () => true;                                 // what closing would lose, per step
    let guardMessage = t('pw.discard_setup');
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, h('h2', {}, t('pw.totp_setup_title')), body),
      { dirty: () => guard(), message: () => guardMessage });
    dialog.addEventListener('close', () => { dialog.remove(); resolve(finished); });   // a half-finished set-up is only a pending secret: nothing to undo
    const error = h('p', { class: 'error', role: 'alert', hidden: true });
    const fail = (message) => { error.textContent = message; error.hidden = !message; };
    const cancel = h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel'));

    function stepAuthenticator({ qr, secret }) {
      const code = h('input', { type: 'text', id: 'totp-code', inputmode: 'numeric', autocomplete: 'one-time-code', pattern: '[0-9 ]*', required: true, maxlength: 7 });
      const submit = h('button', { class: 'btn primary', type: 'submit' }, t('common.confirm'));
      body.replaceChildren(h('form', { class: 'stack', onsubmit: async (e) => {
        e.preventDefault();
        fail('');
        submit.disabled = true;
        try {
          const res = await api('POST', '/api/auth/password/totp/confirm', { code: code.value });
          stepCodes(res.backup_codes);
        } catch (err) { fail(err.message); submit.disabled = false; }
      } },
      h('p', {}, t('pw.scan')),
      h('div', { class: 'qr' }, h('img', { src: qr, alt: t('pw.qr_alt'), width: 200, height: 200 })),
      h('p', { class: 'muted' }, t('pw.manual_key')),
      h('p', { class: 'secret', id: 'totp-secret' }, group(secret)),
      h('div', { class: 'field' }, h('label', { for: 'totp-code' }, t('pw.app_code')), code),
      error, h('div', { class: 'row end' }, cancel, submit)));
      code.focus();
    }

    function stepCodes(codes) {
      finished = true;                                        // it is on now; closing no longer discards anything
      const saved = h('input', { type: 'checkbox', id: 'codes-saved' });
      const done = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: () => dialog.close() }, t('common.done'));
      saved.addEventListener('change', () => { done.disabled = !saved.checked; });
      guard = () => !saved.checked;                         // the codes are shown once: do not lose them unsaved
      guardMessage = t('pw.codes_unsaved');
      body.replaceChildren(
        h('p', {}, t('pw.enabled_save'), ' ',
          h('strong', {}, t('auth.shown_once')), ' ', t('auth.each_code_once')),
        ...codesBlock(codes),
        h('label', { class: 'check', for: 'codes-saved' }, saved, t('pw.codes_saved')),
        h('div', { class: 'row end' }, done));
    }

    document.body.append(dialog);
    dialog.showModal();
    api('POST', '/api/auth/password/totp/start').then(stepAuthenticator, (err) => {
      body.replaceChildren(h('p', { class: 'error', role: 'alert' }, err.message), h('div', { class: 'row end' }, cancel));
    });
  });
}

/**
 * Asks for proof it is really the person signed in (and, with `target`, for what is done to that other person): a passkey, or (for a device where no passkey works, or a person with
 * only a password) the password, plus a code when they have an authenticator app. Only what the person has is offered. Resolves with what the server expects in
 * the request body, or null when cancelled.
 */
export async function confirmIdentity(options) {
  let how = { passkey: true, password: true, totp: true };
  try {
    const status = await api('GET', '/api/auth/password/status');
    how = { passkey: status.passkeys > 0, password: status.enabled, totp: status.totp };
  } catch { /* offer everything: the server decides */ }
  return askIdentity(options, how);
}

function askIdentity({ action, target, title, message, confirmLabel }, how) {
  return new Promise((resolve) => {
    let proof = null;
    const error = h('p', { class: 'error', role: 'alert', hidden: true });
    const fail = (text) => { error.textContent = text; error.hidden = !text; };
    const password = h('input', { type: 'password', id: 'confirm-password', autocomplete: 'current-password', required: true });
    const code = how.totp ? h('input', { type: 'text', id: 'confirm-code', inputmode: 'text', autocomplete: 'one-time-code', required: true, maxlength: 14 }) : null;
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, h('div', { class: 'stack' },
      h('h2', {}, title),
      h('p', {}, message),
      how.passkey ? h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        fail('');
        try { proof = { credential: await confirmWithPasskey(action, target) }; dialog.close(); }
        catch (e) { fail(t('pw.passkey_failed', { message: e.message })); }
      } }, t('pw.confirm_passkey')) : null,
      how.passkey && how.password ? h('p', { class: 'muted' }, t('pw.or_without')) : null,
      how.password ? h('form', { class: 'stack', onsubmit: (e) => {
        e.preventDefault();
        proof = { current_password: password.value, ...(code ? { code: code.value } : {}) };
        dialog.close();
      } },
      h('div', { class: 'field' }, h('label', { for: 'confirm-password' }, t('pw.current')), password),
      code ? h('div', { class: 'field' }, h('label', { for: 'confirm-code' }, t('pw.code_or_backup')), code) : null,
      error,
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
        h('button', { class: 'btn primary', type: 'submit' }, confirmLabel))) : h('div', { class: 'stack' }, error,
        h('div', { class: 'row end' }, h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')))))));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(proof); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

async function newPassword() {
  return new Promise((resolve) => {
    const pw = h('input', { type: 'password', id: 'pw-change', autocomplete: 'new-password', required: true, minlength: 12 });
    const again = h('input', { type: 'password', id: 'pw-change2', autocomplete: 'new-password', required: true });
    const error = h('p', { class: 'error', role: 'alert', hidden: true });
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, h('form', { class: 'stack', onsubmit: async (e) => {
      e.preventDefault();
      if (pw.value !== again.value) { error.textContent = t('pw.mismatch'); error.hidden = false; return; }
      try {
        const proof = await confirmIdentity({ action: 'password-change', title: t('pw.change_confirm_title'),
          message: t('pw.change_confirm_msg'), confirmLabel: t('pw.change_confirm') });
        if (!proof) return;
        await api('POST', '/api/auth/password/change', { password: pw.value, ...proof });
        dialog.close('yes');
      } catch (err) { error.textContent = err.message; error.hidden = false; }
    } },
    h('h2', {}, t('pw.change')),
    h('div', { class: 'field' }, h('label', { for: 'pw-change' }, t('pw.new')), pw, h('p', { class: 'hint' }, t('pw.min_length'))),
    h('div', { class: 'field' }, h('label', { for: 'pw-change2' }, t('pw.repeat')), again),
    error,
    h('div', { class: 'row end' },
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
      h('button', { class: 'btn primary', type: 'submit' }, t('common.continue'))))), { dirty: () => !!(pw.value || again.value) });
    dialog.addEventListener('close', () => { dialog.remove(); resolve(dialog.returnValue === 'yes'); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

function showCodes(codes, title) {
  return new Promise((resolve) => {
    let acknowledged = false;
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, h('h2', {}, title),
      h('p', {}, h('strong', {}, t('pw.save_them_now')), ' ', t('recovery.not_shown_again')), ...codesBlock(codes),
      h('div', { class: 'row end' }, h('button', { class: 'btn primary', type: 'button', onclick: () => { acknowledged = true; dialog.close(); } }, t('common.done')))),
    { dirty: () => !acknowledged, message: t('pw.codes_unsaved') });
    dialog.addEventListener('close', () => { dialog.remove(); resolve(); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

export function passwordCard() {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));

  async function turnOff(title, message, label, action, path, done) {
    try {
      const proof = await confirmIdentity({ action, title, message, confirmLabel: label });
      if (!proof) return;
      await api('POST', path, proof);
      toast(done);
    } catch (e) { toast(e.message, 'error'); }
    draw();
  }

  function totpPart(status) {
    if (!status.totp) {
      return h('div', { class: 'stack' }, h('h3', {}, t('pw.totp_title')), h('p', { class: 'muted' }, t('pw.totp_off')),
        h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: async () => { await totpWizard(); draw(); } }, t('pw.totp_add'))));
    }
    return h('div', { class: 'stack' }, h('h3', {}, t('pw.totp_title')),
      h('p', { class: 'status-line' }, t('pw.totp_on')), h('p', { class: 'muted' }, t('pw.totp_detail', { n: status.backup_codes_remaining })),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', onclick: async () => {
          if (!(await confirmDialog(t('pw.regen_confirm'), t('recovery.new_codes')))) return;
          try {
            const proof = await confirmIdentity({ action: 'password-backup-codes', title: t('pw.regen_title'),
              message: t('pw.regen_msg'), confirmLabel: t('pw.regen_make') });
            if (!proof) return;
            const res = await api('POST', '/api/auth/password/backup-codes/regenerate', proof);
            await showCodes(res.backup_codes, t('pw.new_backup'));
            draw();
          } catch (e) { toast(e.message, 'error'); }
        } }, t('pw.new_backup')),
        h('button', { class: 'btn danger', type: 'button', onclick: () => turnOff(t('pw.totp_disable_title'), t('pw.totp_disable_msg'), t('pw.totp_disable'),
          'password-totp-disable', '/api/auth/password/totp/disable', t('pw.totp_is_off')) }, t('pw.totp_disable'))));
  }

  async function draw() {
    let status;
    try { status = await api('GET', '/api/auth/password/status'); } catch (e) { body.replaceChildren(h('p', { class: 'error' }, e.message)); return; }
    if (!status.enabled) {
      body.replaceChildren(
        h('p', { class: 'muted' }, t('pw.off_intro')),
        switchRow(t('pw.switch'), t('pw.switch_hint'), false, async (on) => {
          if (on) await passwordDialog();
          draw();
        }));
      return;
    }
    body.replaceChildren(
      h('p', { class: 'status-line' }, t('pw.on')),
      h('p', { class: 'muted' }, t('pw.on_detail')),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', onclick: async () => { if (await newPassword()) { toast(t('pw.changed')); draw(); } } }, t('pw.change')),
        h('button', { class: 'btn danger', type: 'button', disabled: status.passkeys === 0, title: status.passkeys === 0 ? t('pw.last_method') : null,
          onclick: () => turnOff(t('pw.disable_title'), t('pw.disable_msg'), t('pw.disable'), 'password-disable', '/api/auth/password/disable', t('pw.is_off')) }, t('pw.disable'))),
      status.passkeys === 0 ? h('p', { class: 'hint' }, t('pw.last_method')) : null,
      totpPart(status));
  }
  draw();
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('pw.title')), body);
}
