import { api, confirmWithPasskey } from './api.js';
import { t } from './i18n.js';
import { confirmDialog, h, switchRow, toast } from './ui.js';

// Optional password login, always together with an authenticator app (two-step verification).
// Passkeys stay the primary way in; this is the weaker, opt-in door, and it is off by default.
// Turning it on only needs the session you are in (it must work on a device without a passkey); changing it,
// turning it off and new backup codes need a passkey confirmation, or the password plus a code on a device
// where no passkey works.

const group = (secret) => secret.replace(/(.{4})/g, '$1 ').trim();

function codesBlock(codes) {
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

/** The setup wizard: password -> authenticator -> backup codes. Resolves true once it is switched on. */
export function setupWizard() {
  return new Promise((resolve) => {
    let finished = false;
    let started = false;
    const body = h('div', { class: 'stack' });
    const dialog = h('dialog', { class: 'glass sheet' }, h('h2', {}, t('pw.setup_title')), body);
    dialog.addEventListener('cancel', () => {});
    dialog.addEventListener('close', () => {
      // Leaving before the end discards the half-finished setup: no password without its second factor.
      if (started && !finished) api('POST', '/api/auth/password/setup/cancel').catch(() => {});
      dialog.remove();
      resolve(finished);
    });
    const error = h('p', { class: 'error', role: 'alert', hidden: true });
    const fail = (message) => { error.textContent = message; error.hidden = !message; };
    const cancel = h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, t('common.cancel'));

    function stepPassword() {
      const pw = h('input', { type: 'password', id: 'pw-new', autocomplete: 'new-password', required: true, minlength: 12 });
      const again = h('input', { type: 'password', id: 'pw-again', autocomplete: 'new-password', required: true });
      const submit = h('button', { class: 'btn primary', type: 'submit' }, t('common.continue'));
      body.replaceChildren(h('form', { class: 'stack', onsubmit: async (e) => {
        e.preventDefault();
        fail('');
        if (pw.value !== again.value) { fail(t('pw.mismatch')); return; }
        submit.disabled = true;
        try {
          const res = await api('POST', '/api/auth/password/setup/start', { password: pw.value });
          started = true;
          stepAuthenticator(res);
        } catch (err) { fail(err.message); submit.disabled = false; }
      } },
      h('p', { class: 'muted' }, t('pw.setup_intro')),
      h('div', { class: 'field' }, h('label', { for: 'pw-new' }, t('pw.new')), pw,
        h('p', { class: 'hint' }, t('pw.new_hint'))),
      h('div', { class: 'field' }, h('label', { for: 'pw-again' }, t('pw.repeat')), again),
      error, h('div', { class: 'row end' }, cancel, submit)));
      pw.focus();
    }

    function stepAuthenticator({ qr, secret }) {
      const code = h('input', { type: 'text', id: 'totp-code', inputmode: 'numeric', autocomplete: 'one-time-code', pattern: '[0-9 ]*', required: true, maxlength: 7 });
      const submit = h('button', { class: 'btn primary', type: 'submit' }, t('common.confirm'));
      body.replaceChildren(h('form', { class: 'stack', onsubmit: async (e) => {
        e.preventDefault();
        fail('');
        submit.disabled = true;
        try {
          const res = await api('POST', '/api/auth/password/setup/confirm', { code: code.value });
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
      body.replaceChildren(
        h('p', {}, t('pw.enabled_save'), ' ',
          h('strong', {}, t('auth.shown_once')), ' ', t('auth.each_code_once')),
        ...codesBlock(codes),
        h('label', { class: 'check', for: 'codes-saved' }, saved, t('pw.codes_saved')),
        h('div', { class: 'row end' }, done));
    }

    document.body.append(dialog);
    dialog.showModal();
    stepPassword();
  });
}

/**
 * Asks for proof it is really the owner: a passkey, or (for a device where no passkey works, e.g. after
 * signing in with password and code) the password plus a code. Resolves with what the server expects in
 * the request body, or null when cancelled.
 */
export function confirmIdentity({ action, title, message, confirmLabel }) {
  return new Promise((resolve) => {
    let proof = null;
    const error = h('p', { class: 'error', role: 'alert', hidden: true });
    const fail = (text) => { error.textContent = text; error.hidden = !text; };
    const password = h('input', { type: 'password', id: 'confirm-password', autocomplete: 'current-password', required: true });
    const code = h('input', { type: 'text', id: 'confirm-code', inputmode: 'text', autocomplete: 'one-time-code', required: true, maxlength: 14 });
    const dialog = h('dialog', { class: 'glass sheet' }, h('div', { class: 'stack' },
      h('h2', {}, title),
      h('p', {}, message),
      h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        fail('');
        try { proof = { credential: await confirmWithPasskey(action) }; dialog.close(); }
        catch (e) { fail(t('pw.passkey_failed', { message: e.message })); }
      } }, t('pw.confirm_passkey')),
      h('p', { class: 'muted' }, t('pw.or_without')),
      h('form', { class: 'stack', onsubmit: (e) => {
        e.preventDefault();
        proof = { current_password: password.value, code: code.value };
        dialog.close();
      } },
      h('div', { class: 'field' }, h('label', { for: 'confirm-password' }, t('pw.current')), password),
      h('div', { class: 'field' }, h('label', { for: 'confirm-code' }, t('pw.code_or_backup')), code),
      error,
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, t('common.cancel')),
        h('button', { class: 'btn primary', type: 'submit' }, confirmLabel)))));
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
    const dialog = h('dialog', { class: 'glass sheet' }, h('form', { class: 'stack', onsubmit: async (e) => {
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
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.close('no') }, t('common.cancel')),
      h('button', { class: 'btn primary', type: 'submit' }, t('common.continue')))));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(dialog.returnValue === 'yes'); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

export function passwordCard() {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));

  async function draw() {
    let status;
    try { status = await api('GET', '/api/auth/password/status'); } catch (e) { body.replaceChildren(h('p', { class: 'error' }, e.message)); return; }
    if (!status.enabled) {
      body.replaceChildren(
        h('p', { class: 'muted' }, t('pw.off_intro')),
        switchRow(t('pw.switch'), t('pw.switch_hint'), false, async (on) => {
          if (on) await setupWizard();
          draw();
        }));
      return;
    }
    body.replaceChildren(
      h('p', { class: 'status-line' }, t('pw.on')),
      h('p', { class: 'muted' }, t('pw.on_detail', { n: status.backup_codes_remaining })),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', onclick: async () => { if (await newPassword()) { toast(t('pw.changed')); draw(); } } }, t('pw.change')),
        h('button', { class: 'btn', type: 'button', onclick: async () => {
          if (!(await confirmDialog(t('pw.regen_confirm'), t('recovery.new_codes')))) return;
          try {
            const proof = await confirmIdentity({ action: 'password-backup-codes', title: t('pw.regen_title'),
              message: t('pw.regen_msg'), confirmLabel: t('pw.regen_make') });
            if (!proof) return;
            const res = await api('POST', '/api/auth/password/backup-codes/regenerate', proof);
            const dialog = h('dialog', { class: 'glass sheet' }, h('h2', {}, t('pw.new_backup')),
              h('p', {}, h('strong', {}, t('pw.save_them_now')), ' ', t('recovery.not_shown_again')), ...codesBlock(res.backup_codes),
              h('div', { class: 'row end' }, h('button', { class: 'btn primary', type: 'button', onclick: () => dialog.close() }, t('common.done'))));
            dialog.addEventListener('close', () => { dialog.remove(); draw(); });
            document.body.append(dialog);
            dialog.showModal();
          } catch (e) { toast(e.message, 'error'); }
        } }, t('pw.new_backup')),
        h('button', { class: 'btn danger', type: 'button', onclick: async () => {
          try {
            const proof = await confirmIdentity({ action: 'password-disable', title: t('pw.disable_title'),
              message: t('pw.disable_msg'), confirmLabel: t('pw.disable') });
            if (!proof) return;
            await api('POST', '/api/auth/password/disable', proof);
            toast(t('pw.is_off'));
          } catch (e) { toast(e.message, 'error'); }
          draw();
        } }, t('pw.disable'))));
  }
  draw();
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('pw.title')), body);
}
