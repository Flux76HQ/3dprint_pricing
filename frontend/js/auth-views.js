import { api, createPasskey, getPasskey, passkeySupport } from './api.js';
import { h, toast } from './ui.js';

function shell(...children) {
  return h('main', { id: 'main', class: 'auth-wrap' }, h('div', { class: 'glass card auth-card' },
    h('div', { class: 'brand' }, h('img', { src: '/icons/icon.svg', alt: '', width: 40, height: 40 }),
      h('div', {}, h('h1', {}, '3D Print Pricing'), h('p', { class: 'muted' }, 'Kostprijs van elke print, tot op de cent.'))),
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

export function onboardingView(onDone) {
  const root = h('div');
  const problem = passkeySupport();

  const error = errorBox();
  const code = h('input', { type: 'password', autocomplete: 'off', required: true, id: 'setup-code' });
  const name = h('input', { type: 'text', autocomplete: 'name', required: true, maxlength: 60, id: 'owner-name' });
  const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Passkey aanmaken');

  const form = h('form', {
    class: 'stack',
    onsubmit: (e) => {
      e.preventDefault();
      guarded(error, submit, async () => {
        const options = await api('POST', '/api/auth/onboarding/options',
          { setup_code: code.value, display_name: name.value });
        const credential = await createPasskey(options);
        const res = await api('POST', '/api/auth/onboarding/verify', { credential, label: 'Eerste passkey' });
        root.replaceChildren(recoveryStep(res.recovery_codes, onDone));
      });
    },
  },
    h('h2', {}, 'Welkom — stel je app in'),
    h('p', { class: 'muted' },
      'Dit is de eerste keer. Je maakt één passkey aan (vingerafdruk, gezichtsherkenning of apparaatcode); ' +
      'er is geen wachtwoord.'),
    h('div', { class: 'field' }, h('label', { for: 'setup-code' }, 'Setupcode'), code,
      h('p', { class: 'hint' }, 'Staat als SETUP_CODE in het .env-bestand van je server.')),
    h('div', { class: 'field' }, h('label', { for: 'owner-name' }, 'Jouw naam'), name),
    problem ? h('p', { class: 'error', role: 'alert' }, problem) : null,
    error, submit);
  root.append(form);
  return shell(root);
}

function recoveryStep(codes, onDone) {
  const confirmed = h('input', { type: 'checkbox', id: 'saved' });
  const proceed = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: onDone },
    'Verder naar de app');
  confirmed.addEventListener('change', () => { proceed.disabled = !confirmed.checked; });
  const text = codes.join('\n');
  return h('div', { class: 'stack' },
    h('h2', {}, 'Bewaar je herstelcodes'),
    h('p', {}, 'Raak je al je apparaten kwijt, dan kom je alleen met een van deze codes weer binnen. ',
      h('strong', {}, 'Ze worden maar één keer getoond.'), ' Elke code werkt één keer.'),
    h('ul', { class: 'codes', 'aria-label': 'Herstelcodes' }, codes.map((c) => h('li', {}, c))),
    h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onclick: async () => {
        try { await navigator.clipboard.writeText(text); toast('Gekopieerd'); } catch { toast('Kopiëren mislukt', 'error'); }
      } }, 'Kopieer'),
      h('button', { class: 'btn', type: 'button', onclick: () => {
        const url = URL.createObjectURL(new Blob([text + '\n'], { type: 'text/plain' }));
        const a = h('a', { href: url, download: 'printpricing-herstelcodes.txt' });
        a.click();
        URL.revokeObjectURL(url);
      } }, 'Download')),
    h('label', { class: 'check', for: 'saved' }, confirmed, 'Ik heb mijn herstelcodes veilig bewaard'),
    proceed);
}

// --- login ---------------------------------------------------------------------

export function loginView(onDone, { passwordLogin = false } = {}) {
  const error = errorBox();
  const problem = passkeySupport();
  const button = h('button', { class: 'btn primary big', type: 'button' }, h('span', {}, 'Inloggen met passkey'));
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
  const redeem = h('button', { class: 'btn', type: 'submit' }, 'Inloggen met herstelcode');
  const panel = h('form', { id: 'recovery-panel', class: 'stack', hidden: true,
    onsubmit: (e) => {
      e.preventDefault();
      guarded(recoveryError, redeem, async () => {
        await api('POST', '/api/auth/recovery/redeem', { code: recoveryInput.value });
        onDone({ recovered: true });
      });
    } },
    h('div', { class: 'field' }, h('label', { for: 'recovery-code' }, 'Herstelcode'), recoveryInput),
    recoveryError, redeem);
  const toggle = h('button', { class: 'link', type: 'button', 'aria-expanded': 'false',
    'aria-controls': 'recovery-panel', onclick: () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute('aria-expanded', String(!panel.hidden));
      if (!panel.hidden) recoveryInput.focus();
    } }, 'Apparaat kwijt?');

  return shell(h('div', { class: 'stack' },
    h('h2', {}, 'Welkom terug'),
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
    } }, 'Inloggen met wachtwoord');

  function stepPassword() {
    const pw = h('input', { type: 'password', id: 'login-password', autocomplete: 'current-password', required: true });
    const submit = h('button', { class: 'btn', type: 'submit' }, 'Verder');
    body.replaceChildren(h('form', { class: 'stack', onsubmit: (e) => {
      e.preventDefault();
      guarded(error, submit, async () => {
        const res = await api('POST', '/api/auth/password/login', { password: pw.value });
        stepCode(res.mfa_token);
      });
    } }, h('div', { class: 'field' }, h('label', { for: 'login-password' }, 'Wachtwoord'), pw), error, submit));
  }

  function stepCode(token) {
    let backup = false;
    const code = h('input', { type: 'text', id: 'login-code', inputmode: 'numeric', autocomplete: 'one-time-code', required: true, maxlength: 14 });
    const label = h('label', { for: 'login-code' }, 'Code uit je authenticator-app');
    const swap = h('button', { class: 'link', type: 'button', onclick: () => {
      backup = !backup;
      label.textContent = backup ? 'Back-upcode' : 'Code uit je authenticator-app';
      code.setAttribute('inputmode', backup ? 'text' : 'numeric');
      code.setAttribute('autocomplete', backup ? 'off' : 'one-time-code');
      code.placeholder = backup ? 'XXXX-XXXX-XXXX' : '';
      swap.textContent = backup ? 'Gebruik de authenticator-app' : 'Gebruik een back-upcode';
      code.value = '';
      code.focus();
    } }, 'Gebruik een back-upcode');
    const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Inloggen');
    body.replaceChildren(h('form', { class: 'stack', onsubmit: (e) => {
      e.preventDefault();
      guarded(error, submit, async () => {
        await api('POST', '/api/auth/password/mfa', { mfa_token: token, code: code.value });
        onDone({ recovered: false });
      });
    } }, h('p', { class: 'muted' }, 'Bijna binnen: voer nu de tweede stap in.'),
    h('div', { class: 'field' }, label, code), error, submit, swap));
    code.focus();
  }

  stepPassword();
  return h('div', { class: 'stack' }, toggle, panel);
}
