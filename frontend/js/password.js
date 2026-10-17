import { api, confirmWithPasskey } from './api.js';
import { confirmDialog, h, switchRow, toast } from './ui.js';

// Optional password login, always together with an authenticator app (two-step verification).
// Passkeys stay the primary way in; this is the weaker, opt-in door, and it is off by default.
// Turning it on only needs the session you are in (it must work on a device without a passkey); changing it,
// turning it off and new backup codes need a fresh passkey confirmation.

const group = (secret) => secret.replace(/(.{4})/g, '$1 ').trim();

function codesBlock(codes) {
  const text = codes.join('\n');
  return [
    h('ul', { class: 'codes', 'aria-label': 'Back-upcodes' }, codes.map((c) => h('li', {}, c))),
    h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onclick: async () => {
        try { await navigator.clipboard.writeText(text); toast('Gekopieerd'); } catch { toast('Kopiëren mislukt', 'error'); }
      } }, 'Kopieer'),
      h('button', { class: 'btn', type: 'button', onclick: () => {
        const url = URL.createObjectURL(new Blob([`${text}\n`], { type: 'text/plain' }));
        h('a', { href: url, download: 'printpricing-backupcodes.txt' }).click();
        URL.revokeObjectURL(url);
      } }, 'Download')),
  ];
}

/** The setup wizard: password -> authenticator -> backup codes. Resolves true once it is switched on. */
export function setupWizard() {
  return new Promise((resolve) => {
    let finished = false;
    let started = false;
    const body = h('div', { class: 'stack' });
    const dialog = h('dialog', { class: 'glass sheet' }, h('h2', {}, 'Wachtwoord-login instellen'), body);
    dialog.addEventListener('cancel', () => {});
    dialog.addEventListener('close', () => {
      // Leaving before the end discards the half-finished setup: no password without its second factor.
      if (started && !finished) api('POST', '/api/auth/password/setup/cancel').catch(() => {});
      dialog.remove();
      resolve(finished);
    });
    const error = h('p', { class: 'error', role: 'alert', hidden: true });
    const fail = (message) => { error.textContent = message; error.hidden = !message; };
    const cancel = h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, 'Annuleren');

    function stepPassword() {
      const pw = h('input', { type: 'password', id: 'pw-new', autocomplete: 'new-password', required: true, minlength: 12 });
      const again = h('input', { type: 'password', id: 'pw-again', autocomplete: 'new-password', required: true });
      const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Doorgaan');
      body.replaceChildren(h('form', { class: 'stack', onsubmit: async (e) => {
        e.preventDefault();
        fail('');
        if (pw.value !== again.value) { fail('De twee wachtwoorden zijn niet gelijk.'); return; }
        submit.disabled = true;
        try {
          const res = await api('POST', '/api/auth/password/setup/start', { password: pw.value });
          started = true;
          stepAuthenticator(res);
        } catch (err) { fail(err.message); submit.disabled = false; }
      } },
      h('p', { class: 'muted' }, 'Je kiest een wachtwoord en koppelt daarna een authenticator-app. Zonder die tweede stap bestaat er geen wachtwoord-login.'),
      h('div', { class: 'field' }, h('label', { for: 'pw-new' }, 'Nieuw wachtwoord'), pw,
        h('p', { class: 'hint' }, 'Minstens 12 tekens. Een zin van een paar woorden is sterk én te onthouden.')),
      h('div', { class: 'field' }, h('label', { for: 'pw-again' }, 'Herhaal wachtwoord'), again),
      error, h('div', { class: 'row end' }, cancel, submit)));
      pw.focus();
    }

    function stepAuthenticator({ qr, secret }) {
      const code = h('input', { type: 'text', id: 'totp-code', inputmode: 'numeric', autocomplete: 'one-time-code', pattern: '[0-9 ]*', required: true, maxlength: 7 });
      const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Bevestigen');
      body.replaceChildren(h('form', { class: 'stack', onsubmit: async (e) => {
        e.preventDefault();
        fail('');
        submit.disabled = true;
        try {
          const res = await api('POST', '/api/auth/password/setup/confirm', { code: code.value });
          stepCodes(res.backup_codes);
        } catch (err) { fail(err.message); submit.disabled = false; }
      } },
      h('p', {}, 'Scan de QR-code met een authenticator-app (bijvoorbeeld Google Authenticator, Microsoft Authenticator, 1Password of Aegis).'),
      h('div', { class: 'qr' }, h('img', { src: qr, alt: 'QR-code om in je authenticator-app te scannen', width: 200, height: 200 })),
      h('p', { class: 'muted' }, 'Lukt scannen niet? Voer deze sleutel handmatig in:'),
      h('p', { class: 'secret', id: 'totp-secret' }, group(secret)),
      h('div', { class: 'field' }, h('label', { for: 'totp-code' }, 'Code uit de app'), code),
      error, h('div', { class: 'row end' }, cancel, submit)));
      code.focus();
    }

    function stepCodes(codes) {
      finished = true;                                        // it is on now; closing no longer discards anything
      const saved = h('input', { type: 'checkbox', id: 'codes-saved' });
      const done = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: () => dialog.close() }, 'Klaar');
      saved.addEventListener('change', () => { done.disabled = !saved.checked; });
      body.replaceChildren(
        h('p', {}, 'Wachtwoord-login staat aan. Bewaar deze back-upcodes: raak je je authenticator-app kwijt, dan log je met een code in. ',
          h('strong', {}, 'Ze worden maar één keer getoond.'), ' Elke code werkt één keer.'),
        ...codesBlock(codes),
        h('label', { class: 'check', for: 'codes-saved' }, saved, 'Ik heb mijn back-upcodes veilig bewaard'),
        h('div', { class: 'row end' }, done));
    }

    document.body.append(dialog);
    dialog.showModal();
    stepPassword();
  });
}

async function newPassword() {
  return new Promise((resolve) => {
    const pw = h('input', { type: 'password', id: 'pw-change', autocomplete: 'new-password', required: true, minlength: 12 });
    const again = h('input', { type: 'password', id: 'pw-change2', autocomplete: 'new-password', required: true });
    const error = h('p', { class: 'error', role: 'alert', hidden: true });
    const dialog = h('dialog', { class: 'glass sheet' }, h('form', { class: 'stack', onsubmit: async (e) => {
      e.preventDefault();
      if (pw.value !== again.value) { error.textContent = 'De twee wachtwoorden zijn niet gelijk.'; error.hidden = false; return; }
      try {
        const credential = await confirmWithPasskey('password-change');
        await api('POST', '/api/auth/password/change', { password: pw.value, credential });
        dialog.close('yes');
      } catch (err) { error.textContent = err.message; error.hidden = false; }
    } },
    h('h2', {}, 'Wachtwoord wijzigen'),
    h('div', { class: 'field' }, h('label', { for: 'pw-change' }, 'Nieuw wachtwoord'), pw, h('p', { class: 'hint' }, 'Minstens 12 tekens.')),
    h('div', { class: 'field' }, h('label', { for: 'pw-change2' }, 'Herhaal wachtwoord'), again),
    error,
    h('div', { class: 'row end' },
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.close('no') }, 'Annuleren'),
      h('button', { class: 'btn primary', type: 'submit' }, 'Wijzigen (met passkey)'))));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(dialog.returnValue === 'yes'); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

export function passwordCard() {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'Laden…'));

  async function draw() {
    let status;
    try { status = await api('GET', '/api/auth/password/status'); } catch (e) { body.replaceChildren(h('p', { class: 'error' }, e.message)); return; }
    if (!status.enabled) {
      body.replaceChildren(
        h('p', { class: 'muted' }, 'Standaard uit. Passkeys blijven de aanbevolen manier van inloggen. Een wachtwoord werkt alleen samen met een authenticator-app (tweestapsverificatie) en stel je hier in.'),
        switchRow('Inloggen met wachtwoord en tweestapsverificatie', 'Naast je passkey kun je dan ook met wachtwoord en code inloggen.', false, async (on) => {
          if (on) await setupWizard();
          draw();
        }));
      return;
    }
    body.replaceChildren(
      h('p', { class: 'status-line' }, '✓ Wachtwoord-login staat aan, met tweestapsverificatie.'),
      h('p', { class: 'muted' }, `Back-upcodes: ${status.backup_codes_remaining} van 8 ongebruikt. Na vijf mislukte pogingen blokkeert wachtwoord-login tijdelijk; je passkey blijft altijd werken.`),
      h('div', { class: 'row' },
        h('button', { class: 'btn', type: 'button', onclick: async () => { if (await newPassword()) { toast('Wachtwoord gewijzigd'); draw(); } } }, 'Wachtwoord wijzigen'),
        h('button', { class: 'btn', type: 'button', onclick: async () => {
          if (!(await confirmDialog('Nieuwe back-upcodes maken? De oude werken daarna niet meer.', 'Nieuwe codes'))) return;
          try {
            const credential = await confirmWithPasskey('password-backup-codes');
            const res = await api('POST', '/api/auth/password/backup-codes/regenerate', { credential });
            const dialog = h('dialog', { class: 'glass sheet' }, h('h2', {}, 'Nieuwe back-upcodes'),
              h('p', {}, h('strong', {}, 'Bewaar ze nu'), ' — ze worden niet opnieuw getoond.'), ...codesBlock(res.backup_codes),
              h('div', { class: 'row end' }, h('button', { class: 'btn primary', type: 'button', onclick: () => dialog.close() }, 'Klaar')));
            dialog.addEventListener('close', () => { dialog.remove(); draw(); });
            document.body.append(dialog);
            dialog.showModal();
          } catch (e) { toast(e.message, 'error'); }
        } }, 'Nieuwe back-upcodes'),
        h('button', { class: 'btn danger', type: 'button', onclick: async () => {
          if (!(await confirmDialog('Wachtwoord-login uitschakelen? Wachtwoord, authenticator en back-upcodes worden verwijderd. Je bevestigt dit met je passkey.', 'Uitschakelen'))) return;
          try {
            const credential = await confirmWithPasskey('password-disable');
            await api('POST', '/api/auth/password/disable', { credential });
            toast('Wachtwoord-login staat uit');
          } catch (e) { toast(e.message, 'error'); }
          draw();
        } }, 'Uitschakelen')));
  }
  draw();
  return h('div', { class: 'glass card stack' }, h('h2', {}, 'Wachtwoord en tweestapsverificatie'), body);
}
