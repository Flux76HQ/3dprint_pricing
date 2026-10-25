import { api, createPasskey, getPasskey, passkeySupport } from './api.js';
import { t } from './i18n.js';
import { langSwitch } from './langswitch.js';
import { betaBadge, h, toast } from './ui.js';

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

export function loginView(onDone, { passwordLogin = false, onLanguage } = {}) {
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
    error, button, passwordLogin ? passwordSection(onDone) : null, toggle, panel));
}

// Password + authenticator code. Only offered when the owner has switched it on in Settings; a session
// exists only after both steps, so the first step shows the code field and nothing is signed in yet.
function passwordSection(onDone) {
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
    const pw = h('input', { type: 'password', id: 'login-password', autocomplete: 'current-password', required: true });
    const submit = h('button', { class: 'btn', type: 'submit' }, t('auth.next'));
    body.replaceChildren(h('form', { class: 'stack', onsubmit: (e) => {
      e.preventDefault();
      guarded(error, submit, async () => {
        const res = await api('POST', '/api/auth/password/login', { password: pw.value });
        stepCode(res.mfa_token);
      });
    } }, h('div', { class: 'field' }, h('label', { for: 'login-password' }, t('auth.password')), pw), error, submit));
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
