// The Filament Manager of Bambu Lab (the spools of a Bambu account, in the Bambu cloud) as the source of the rolls: the card under Settings ->
// Koppelingen (signing in with a mailed code or an authenticator app, the sync, signing out) and the slim bar on the Filament page. The server
// decides everything (bambu_cloud.py); this only shows it. The password is sent once, to the app's own server, and never kept in the page.
import { api } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { confirmDialog, connectionBadge, field, fill, foldHead, h, icon, toast } from './ui.js';

// Whether the app is signed in, as last heard: the roll list uses it to lock what the cloud keeps. Read again by every status call.
let signedIn = false;
export const cloudSignedIn = () => signedIn;

/** The status of the connection; null when it could not be read (the page works without it). */
export async function cloudStatus() {
  try {
    const status = await api('GET', '/api/bambu-cloud');
    signedIn = !!status.enabled;
    return status;
  } catch { return null; }
}

const when = (moment) => (moment ? formatDateTime(moment, { dateStyle: 'short', timeStyle: 'short' }) : t('bambu.never'));

/** Read every spool of the account; says what came of it. True when it went through. */
async function runSync() {
  try {
    toast(t('bambu.done', await api('POST', '/api/bambu-cloud/sync')));
    return true;
  } catch (err) { toast(err.message, 'error'); return false; }
}

/** The slim version for the Filament page, next to the Stock / Rolls tabs: when the cloud was last read and a Sync button. Hidden while the app is
 * not signed in. `onState` runs whenever the state is known (the list then knows which rolls are the cloud's), `onSynced` after a sync that went through. */
export function bambuBar({ onState = () => {}, onSynced = () => {} } = {}) {
  const bar = h('div', { class: 'spoolman-bar', hidden: true });
  async function draw() {
    const status = await cloudStatus();
    onState();
    if (!status || !status.enabled) { bar.hidden = true; return; }
    fill(bar, h('span', { class: 'muted' }, t('bambu.bar', { when: when(status.last_sync) })),
      status.pending ? h('span', { class: 'badge', title: t('bambu.pending', { n: status.pending }) }, t('bambu.pending_short', { n: status.pending })) : null,
      status.can_configure ? h('button', { class: 'btn small', type: 'button', onclick: async (e) => {
        e.currentTarget.disabled = true;
        if (await runSync()) onSynced();
        draw();
      } }, icon('sync'), h('span', {}, t('bambu.sync_short'))) : null);
    bar.hidden = false;
  }
  draw();
  return bar;
}

/** The card under Settings -> Koppelingen. Hidden for a regular user while the app is not signed in; an administrator always sees it, with the
 * sign-in. `onSynced` runs after a sync that went through. */
export function bambuCloudCard(onSynced = () => {}) {
  const card = h('div', { class: 'glass card stack', hidden: true });
  const badge = connectionBadge();

  async function draw() {
    const status = await cloudStatus();
    if (!status) return;
    const admin = status.can_configure;
    if (!status.enabled && !admin) { card.hidden = true; return; }
    const head = foldHead('bambu-cloud', t('bambu.title'), { open: false, extra: badge.el });
    const problem = h('p', { class: 'notice error', role: 'alert', hidden: true });
    if (!status.enabled) badge.set('off');
    else {
      badge.set('checking');
      api('GET', '/api/bambu-cloud/connection').then((c) => {
        badge.set(c.state, { detail: c.state === 'active' ? status.account || null : null, message: c.message });
        problem.textContent = c.message || '';
        problem.hidden = !c.message;
      }).catch(() => badge.set('offline'));
    }
    const intro = [h('p', { class: 'muted' }, t('bambu.intro')), h('p', { class: 'hint' }, t('bambu.unofficial'))];
    if (status.spoolman && !status.enabled) {                       // one source at a time
      fill(card, head, ...intro, h('p', { class: 'notice', role: 'status' }, t('bambu.spoolman_first')));
      card.hidden = false;
      return;
    }
    const parts = [head, ...intro, problem];
    if (status.enabled) {
      parts.push(h('p', { class: 'hint breakable' }, t('bambu.status', { n: status.rolls, when: when(status.last_sync) })));
      if (admin) {
        parts.push(h('p', { class: 'hint breakable' }, status.expires_at
          ? t('bambu.account_until', { account: status.account, until: formatDateTime(status.expires_at, { dateStyle: 'medium' }) })
          : t('bambu.account', { account: status.account })));
      }
      if (status.pending) parts.push(h('p', { class: 'notice', role: 'status' }, t('bambu.pending', { n: status.pending })));
      if (admin && (status.expired || !status.token_readable)) parts.push(h('p', { class: 'notice error', role: 'alert' }, t('bambu.sign_in_again')));
      if (admin) {
        parts.push(h('div', { class: 'row' },
          h('button', { class: 'btn primary', type: 'button', onclick: async (e) => {
            const button = e.currentTarget;
            button.disabled = true;
            if (await runSync()) onSynced();
            button.disabled = false;
            draw();
          } }, icon('sync'), h('span', {}, t('bambu.sync'))),
          h('button', { class: 'btn', type: 'button', onclick: async () => {
            if (!(await confirmDialog(t('bambu.sign_out_confirm'), t('bambu.sign_out')))) return;
            try { await api('DELETE', '/api/bambu-cloud/login'); toast(t('bambu.signed_out')); } catch (err) { toast(err.message, 'error'); }
            draw();
          } }, t('bambu.sign_out'))));
        parts.push(h('p', { class: 'hint' }, t('bambu.what_is_whose')));
      } else parts.push(h('p', { class: 'hint' }, t('bambu.admin_only')));
    }
    if (admin && (!status.enabled || status.expired || !status.token_readable)) parts.push(status.waiting ? codeForm(status) : signInForm(status));
    fill(card, ...parts);
    card.hidden = false;
  }

  // Step one: the account, the password and the region. The password field is emptied as soon as it is sent.
  function signInForm(status) {
    const region = h('select', {}, [['global', t('bambu.region_global')], ['china', t('bambu.region_china')]].map(([value, label]) =>
      h('option', { value, selected: value === (status.region || 'global') }, label)));
    const account = h('input', { type: 'email', autocomplete: 'username', spellcheck: 'false', required: true, value: status.account || '' });
    const password = h('input', { type: 'password', autocomplete: 'current-password', required: true });
    const submit = h('button', { class: 'btn primary', type: 'submit' }, t('bambu.sign_in'));
    return h('form', { class: 'stack', onsubmit: async (e) => {
      e.preventDefault();
      submit.disabled = true;
      const body = { region: region.value, account: account.value.trim(), password: password.value };
      password.value = '';
      try {
        const res = await api('POST', '/api/bambu-cloud/login', body);
        toast(res.step === 'done' ? t('bambu.signed_in') : t(res.step === 'tfa' ? 'bambu.tfa_sent' : 'bambu.code_sent'));
      } catch (err) { toast(err.message, 'error'); }
      draw();
    } },
    field(t('bambu.account_label'), account, t('bambu.account_hint')),
    field(t('bambu.password'), password, t('bambu.password_hint')),
    field(t('bambu.region'), region),
    h('div', { class: 'row' }, submit));
  }

  // Step two: the code from the e-mail, or from the authenticator app.
  function codeForm(status) {
    const code = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'one-time-code', required: true, maxlength: 12 });
    const tfa = status.waiting === 'tfa';
    const submit = h('button', { class: 'btn primary', type: 'submit' }, t('bambu.confirm'));
    const again = async () => {
      try { await api('POST', '/api/bambu-cloud/login/resend'); toast(t('bambu.code_sent')); } catch (err) { toast(err.message, 'error'); }
    };
    return h('form', { class: 'stack', onsubmit: async (e) => {
      e.preventDefault();
      submit.disabled = true;
      try {
        await api('POST', '/api/bambu-cloud/login/code', { code: code.value });
        toast(t('bambu.signed_in'));
        onSynced();
      } catch (err) { toast(err.message, 'error'); submit.disabled = false; return; }
      draw();
    } },
    field(t(tfa ? 'bambu.tfa_label' : 'bambu.code_label'), code, t(tfa ? 'bambu.tfa_hint' : 'bambu.code_hint', { account: status.account })),
    h('div', { class: 'row' }, submit,
      tfa ? null : h('button', { class: 'btn', type: 'button', onclick: again }, t('bambu.code_again')),
      h('button', { class: 'btn', type: 'button', onclick: async () => {        // start again: forget the waiting step
        try { await api('DELETE', '/api/bambu-cloud/login'); } catch { /* nothing to forget */ }
        draw();
      } }, t('common.cancel'))));
  }

  draw();
  return card;
}
