import { api, createPasskey, getPasskey, passkeySupport } from './api.js';
import { t } from './i18n.js';
import { langSwitch } from './langswitch.js';
import { codesBlock } from './password.js';
import { betaBadge, fill, h, toast } from './ui.js';

function shell(onLanguage, ...children) {
  return h('main', { id: 'main', class: 'auth-wrap' }, h('div', { class: 'glass card auth-card' },
    langSwitch(onLanguage),
    h('div', { class: 'brand' }, h('img', { src: '/icons/icon.svg', alt: '', width: 40, height: 40 }),
      h('div', {}, h('h1', {}, '3D Print Pricing', betaBadge()), h('p', { class: 'muted' }, t('auth.tagline')))),
    ...children));
}

function errorBox() {
  return h('p', { class: 'error', role: 'alert', hidden: true });
}

function showError(box, message) {
  box.textContent = message;
  box.hidden = !message;
}

async function guarded(box, button, work) {
  showError(box, '');
  button.disabled = true;
  try {
    await work();
  } catch (e) {
    showError(box, e.message);
  } finally {
    button.disabled = false;
  }
}

// --- onboarding: setup code + name -> passkey -> recovery codes -------------------

export function onboardingView(onDone, onLanguage) {
  const root = h('div');
  const problem = passkeySupport();

  const error = errorBox();
  const code = h('input', { type: 'password', autocomplete: 'off', required: true, id: 'setup-code' });
  const name = h('input', { type: 'text', autocomplete: 'name', required: true, maxlength: 60, id: 'owner-name' });
  const submit = h('button', { class: 'btn primary', type: 'submit' }, t('auth.create_passkey'));

  const form = h('form', {
    class: 'stack',
    onsubmit: (e) => {
      e.preventDefault();
      guarded(error, submit, async () => {
        const options = await api('POST', '/api/auth/onboarding/options',
          { setup_code: code.value, display_name: name.value });
        const credential = await createPasskey(options);
        const res = await api('POST', '/api/auth/onboarding/verify', { credential, label: t('auth.first_passkey') });
        root.replaceChildren(recoveryStep(res.recovery_codes, onDone));
      });
    },
  },
    h('h2', {}, t('auth.welcome_setup')),
    h('p', { class: 'muted' },
      t('auth.first_time')),
    setupCodeHelp(),
    h('div', { class: 'field' }, h('label', { for: 'setup-code' }, t('auth.setup_code')), code,
      h('p', { class: 'hint' }, t('auth.setup_code_hint'))),
    h('div', { class: 'field' }, h('label', { for: 'owner-name' }, t('auth.your_name')), name),
    problem ? h('p', { class: 'error', role: 'alert' }, problem) : null,
    error, submit);
  root.append(form);
  return shell(onLanguage, root);
}

// Says what the setup code is, where it lives and where it goes, so nobody has to guess at the first screen.
function setupCodeHelp() {
  return h('section', { class: 'setup-help', 'aria-labelledby': 'setup-help-title' },
    h('h3', { id: 'setup-help-title' }, t('auth.setup_help_title')),
    h('p', {}, t('auth.setup_help_why')),
    h('ol', {},
      h('li', {}, t('auth.setup_help_step_find'), ' ', h('code', {}, 'grep SETUP_CODE .env')),
      h('li', {}, t('auth.setup_help_step_copy'))),
    h('p', { class: 'hint' }, t('auth.setup_help_note')));
}

function recoveryStep(codes, onDone) {
  const confirmed = h('input', { type: 'checkbox', id: 'saved' });
  const proceed = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: onDone },
    t('auth.continue_app'));
  confirmed.addEventListener('change', () => { proceed.disabled = !confirmed.checked; });
  const text = codes.join('\n');
  return h('div', { class: 'stack' },
    h('h2', {}, t('auth.save_recovery')),
    h('p', {}, t('auth.recovery_intro'), ' ',
      h('strong', {}, t('auth.shown_once')), ' ', t('auth.each_code_once')),
    h('ul', { class: 'codes', 'aria-label': t('auth.recovery_codes') }, codes.map((c) => h('li', {}, c))),
    h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onclick: async () => {
        try { await navigator.clipboard.writeText(text); toast(t('common.copied')); } catch { toast(t('common.copy_failed'), 'error'); }
      } }, t('common.copy')),
      h('button', { class: 'btn', type: 'button', onclick: () => {
        const url = URL.createObjectURL(new Blob([text + '\n'], { type: 'text/plain' }));
        const a = h('a', { href: url, download: 'printpricing-herstelcodes.txt' });
        a.click();
        URL.revokeObjectURL(url);
      } }, t('common.download'))),
    h('label', { class: 'check', for: 'saved' }, confirmed, t('auth.codes_saved')),
    proceed);
}

// --- login ---------------------------------------------------------------------

export function loginView(onDone, { passwordLogin = false, nameRequired = false, onLanguage } = {}) {
  const error = errorBox();
  const problem = passkeySupport();
  const button = h('button', { class: 'btn primary big', type: 'button' }, h('span', {}, t('auth.login_passkey')));
  button.addEventListener('click', () => guarded(error, button, async () => {
    const options = await api('POST', '/api/auth/login/options');
    const credential = await getPasskey(options);
    await api('POST', '/api/auth/login/verify', { credential });
    onDone({ recovered: false });
  }));

  // Emergency exit: findable, not prominent. Stays in the DOM and is hidden with `hidden`,
  // so aria-controls always points at something real.
  const recoveryInput = h('input', { type: 'text', autocomplete: 'off', autocapitalize: 'characters',
    spellcheck: 'false', id: 'recovery-code', placeholder: 'XXXX-XXXX-XXXX' });
  const recoveryError = errorBox();
  const redeem = h('button', { class: 'btn', type: 'submit' }, t('auth.login_recovery'));
  const panel = h('form', { id: 'recovery-panel', class: 'stack', hidden: true,
    onsubmit: (e) => {
      e.preventDefault();
      guarded(recoveryError, redeem, async () => {
        await api('POST', '/api/auth/recovery/redeem', { code: recoveryInput.value });
        onDone({ recovered: true });
      });
    } },
    h('div', { class: 'field' }, h('label', { for: 'recovery-code' }, t('auth.recovery_code')), recoveryInput),
    recoveryError, redeem);
  const toggle = h('button', { class: 'link', type: 'button', 'aria-expanded': 'false',
    'aria-controls': 'recovery-panel', onclick: () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute('aria-expanded', String(!panel.hidden));
      if (!panel.hidden) recoveryInput.focus();
    } }, t('auth.device_lost'));

  return shell(onLanguage, h('div', { class: 'stack' },
    h('h2', {}, t('auth.welcome_back')),
    problem ? h('p', { class: 'error', role: 'alert' }, problem) : null,
    error, button, passwordLogin ? passwordSection(onDone, nameRequired) : null, toggle, panel));
}

// Name + password + authenticator code. Only offered when someone has switched it on in Settings; a session exists only after
// both steps, so the first step shows the code field and nothing is signed in yet. The name is asked when there are several people.
function passwordSection(onDone, nameRequired) {
  const error = errorBox();
  const body = h('div', { class: 'stack' });
  const panel = h('div', { id: 'password-panel', class: 'stack', hidden: true }, body);
  const toggle = h('button', { class: 'link', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'password-panel',
    onclick: () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute('aria-expanded', String(!panel.hidden));
      if (!panel.hidden) body.querySelector('input')?.focus();
    } }, t('auth.login_password'));

  function stepPassword() {
    const name = nameRequired ? h('input', { type: 'text', id: 'login-name', autocomplete: 'username', required: true, maxlength: 100 }) : null;
    const pw = h('input', { type: 'password', id: 'login-password', autocomplete: 'current-password', required: true });
    const submit = h('button', { class: 'btn', type: 'submit' }, t('auth.next'));
    body.replaceChildren(h('form', { class: 'stack', onsubmit: (e) => {
      e.preventDefault();
      guarded(error, submit, async () => {
        const res = await api('POST', '/api/auth/password/login', { name: name ? name.value : undefined, password: pw.value });
        stepCode(res.mfa_token);
      });
    } }, name ? h('div', { class: 'field' }, h('label', { for: 'login-name' }, t('auth.your_name')), name) : null,
    h('div', { class: 'field' }, h('label', { for: 'login-password' }, t('auth.password')), pw), error, submit));
  }

  function stepCode(token) {
    let backup = false;
    const code = h('input', { type: 'text', id: 'login-code', inputmode: 'numeric', autocomplete: 'one-time-code', required: true, maxlength: 14 });
    const label = h('label', { for: 'login-code' }, t('auth.code_app'));
    const swap = h('button', { class: 'link', type: 'button', onclick: () => {
      backup = !backup;
      label.textContent = backup ? t('auth.backup_code') : t('auth.code_app');
      code.setAttribute('inputmode', backup ? 'text' : 'numeric');
      code.setAttribute('autocomplete', backup ? 'off' : 'one-time-code');
      code.placeholder = backup ? 'XXXX-XXXX-XXXX' : '';
      swap.textContent = backup ? t('auth.use_app') : t('auth.use_backup');
      code.value = '';
      code.focus();
    } }, t('auth.use_backup'));
    const submit = h('button', { class: 'btn primary', type: 'submit' }, t('auth.login'));
    body.replaceChildren(h('form', { class: 'stack', onsubmit: (e) => {
      e.preventDefault();
      guarded(error, submit, async () => {
        await api('POST', '/api/auth/password/mfa', { mfa_token: token, code: code.value });
        onDone({ recovered: false });
      });
    } }, h('p', { class: 'muted' }, t('auth.almost_in')),
    h('div', { class: 'field' }, label, code), error, submit, swap));
    code.focus();
  }

  stepPassword();
  return h('div', { class: 'stack' }, toggle, panel);
}

// --- invitation: a link from an administrator -> a name -> a passkey or a password -> codes to keep ------------------------
// The link is `#invite=<token>`: the fragment is never sent to a server, and the token goes back in a header. Once finished it is
// taken out of the address bar and the history.

export const inviteToken = () => new URLSearchParams(location.hash.replace(/^#/, '')).get('invite');

function leaveInvite() {
  history.replaceState(null, '', location.pathname + location.search);
}

export function inviteView(token, onDone, onLanguage) {
  const headers = { 'X-Invite-Token': token };
  const post = (path, body) => api('POST', `/api/invites/${path}`, body, headers);
  const root = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));

  const codesStep = (codes) => {
    leaveInvite();
    const saved = h('input', { type: 'checkbox', id: 'invite-saved' });
    const proceed = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: onDone }, t('auth.continue_app'));
    saved.addEventListener('change', () => { proceed.disabled = !saved.checked; });
    root.replaceChildren(h('h2', {}, t('auth.save_recovery')),
      h('p', {}, t('auth.recovery_intro'), ' ', h('strong', {}, t('auth.shown_once')), ' ', t('auth.each_code_once')),
      ...codesBlock(codes), h('label', { class: 'check', for: 'invite-saved' }, saved, t('auth.codes_saved')), proceed);
  };

  function form(info) {
    const reset = info.kind === 'reset';
    const problem = passkeySupport();
    const error = errorBox();
    const name = h('input', { type: 'text', id: 'invite-name', autocomplete: 'username', required: true, maxlength: 60, value: info.name || '', readonly: reset });
    const nameField = h('div', { class: 'field' }, h('label', { for: 'invite-name' }, t('auth.your_name')), name,
      reset ? null : h('p', { class: 'hint' }, t('invite.name_hint')));

    const passkey = h('button', { class: 'btn primary big', type: 'button', disabled: !!problem, title: problem || null }, t('invite.use_passkey'));
    passkey.addEventListener('click', () => guarded(error, passkey, async () => {
      const options = await post('passkey/options', { name: name.value });
      const credential = await createPasskey(options);
      const res = await post('passkey/verify', { credential, label: t('auth.first_passkey') });
      codesStep(res.recovery_codes);
    }));

    // The same set-up as in Settings: a password of at least 12 characters, then an authenticator app, then backup codes.
    const pw = h('input', { type: 'password', id: 'invite-password', autocomplete: 'new-password', required: true, minlength: 12 });
    const again = h('input', { type: 'password', id: 'invite-password2', autocomplete: 'new-password', required: true });
    const passwordError = errorBox();
    const next = h('button', { class: 'btn', type: 'submit' }, t('common.continue'));
    const passwordForm = h('form', { class: 'stack', hidden: true, id: 'invite-password-panel', onsubmit: (e) => {
      e.preventDefault();
      if (pw.value !== again.value) { showError(passwordError, t('pw.mismatch')); return; }
      guarded(passwordError, next, async () => {
        const res = await post('password/start', { name: name.value, password: pw.value });
        authenticatorStep(res);
      });
    } },
    h('p', { class: 'muted' }, t('pw.setup_intro')),
    h('div', { class: 'field' }, h('label', { for: 'invite-password' }, t('pw.new')), pw, h('p', { class: 'hint' }, t('pw.new_hint'))),
    h('div', { class: 'field' }, h('label', { for: 'invite-password2' }, t('pw.repeat')), again), passwordError, next);
    const toggle = h('button', { class: 'link', type: 'button', 'aria-expanded': 'false', 'aria-controls': 'invite-password-panel', onclick: () => {
      passwordForm.hidden = !passwordForm.hidden;
      toggle.setAttribute('aria-expanded', String(!passwordForm.hidden));
      if (!passwordForm.hidden) pw.focus();
    } }, t('invite.use_password'));

    function authenticatorStep({ qr, secret }) {
      const code = h('input', { type: 'text', id: 'invite-totp', inputmode: 'numeric', autocomplete: 'one-time-code', pattern: '[0-9 ]*', required: true, maxlength: 7 });
      const codeError = errorBox();
      const confirm = h('button', { class: 'btn primary', type: 'submit' }, t('common.confirm'));
      root.replaceChildren(h('form', { class: 'stack', onsubmit: (e) => {
        e.preventDefault();
        guarded(codeError, confirm, async () => {
          const res = await post('password/confirm', { code: code.value });
          codesStep(res.backup_codes);
        });
      } },
      h('p', {}, t('pw.scan')),
      h('div', { class: 'qr' }, h('img', { src: qr, alt: t('pw.qr_alt'), width: 200, height: 200 })),
      h('p', { class: 'muted' }, t('pw.manual_key')),
      h('p', { class: 'secret' }, secret.replace(/(.{4})/g, '$1 ').trim()),
      h('div', { class: 'field' }, h('label', { for: 'invite-totp' }, t('pw.app_code')), code), codeError, confirm));
      code.focus();
    }

    return [h('h2', {}, reset ? t('invite.reset_title') : t('invite.welcome_title')),
      h('p', { class: 'muted' }, reset ? t('invite.reset_intro', { name: info.name }) : t('invite.welcome_intro', { by: info.invited_by || t('invite.someone') })),
      nameField,
      problem ? h('p', { class: 'hint', role: 'note' }, problem) : null,
      error, passkey, toggle, passwordForm,
      h('p', { class: 'hint' }, t('invite.never_known'))];
  }

  api('GET', '/api/invites/info', undefined, headers).then(
    (info) => fill(root, form(info)),
    (e) => root.replaceChildren(h('h2', {}, t('invite.invalid_title')), h('p', { class: 'error', role: 'alert' }, e.message),
      h('button', { class: 'btn', type: 'button', onclick: () => { leaveInvite(); onDone(); } }, t('invite.to_login'))));
  return shell(onLanguage, root);
}
