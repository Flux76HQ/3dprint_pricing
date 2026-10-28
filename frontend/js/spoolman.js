import { api } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { confirmDialog, field, fill, foldHead, h, icon, toast } from './ui.js';

/** Read every spool of Spoolman; says what came of it. True when it went through. */
async function runSync() {
  try {
    toast(t('spoolman.done', await api('POST', '/api/spoolman/sync')));
    return true;
  } catch (err) { toast(err.message, 'error'); return false; }
}

/** The slim version for the Filament page, one line next to the Stock / Rolls tabs: when Spoolman was last read and a Sync button. The
 * address, the library and the rolls going to Spoolman are in Settings. Hidden while there is no Spoolman. */
export function spoolmanBar(onSynced = () => {}) {
  const bar = h('div', { class: 'spoolman-bar', hidden: true });
  async function draw() {
    let status;
    try { status = await api('GET', '/api/spoolman'); } catch { return; }          // a convenience: the page works without it
    if (!status.enabled) { bar.hidden = true; return; }
    const when = status.last_sync ? formatDateTime(status.last_sync, { dateStyle: 'short', timeStyle: 'short' }) : t('spoolman.never');
    fill(bar, h('span', { class: 'muted' }, t('spoolman.bar', { when })),
      status.pending ? h('span', { class: 'badge', title: t('spoolman.pending', { n: status.pending }) }, t('spoolman.pending_short', { n: status.pending })) : null,
      status.can_sync ? h('button', { class: 'btn small', type: 'button', onclick: async (e) => {
        const button = e.currentTarget;
        button.disabled = true;
        if (await runSync()) onSynced();
        draw();
      } }, icon('sync'), h('span', {}, t('spoolman.sync_short'))) : null);
    bar.hidden = false;
  }
  draw();
  return bar;
}

/** The Spoolman card: where the rolls come from, when they were last read, and the Sync button. It stays hidden while there is no Spoolman,
 * so an installation without one looks as before; with `configure` (Settings) an administrator sees it anyway, with the field for the address.
 * `onSynced` runs after a sync that went through (to redraw a list). */
export function spoolmanCard(onSynced = () => {}, { configure = false } = {}) {
  const card = h('div', { class: 'glass card stack', hidden: true });

  async function draw() {
    let status;
    try { status = await api('GET', '/api/spoolman'); } catch { return; }          // a convenience: the page works without it
    const setup = configure && status.can_sync;
    if (!status.enabled && !setup) { card.hidden = true; return; }
    // The address: typed here by an administrator, unless .env sets it (then it is shown and cannot be changed).
    const input = h('input', { type: 'text', inputmode: 'url', autocomplete: 'off', spellcheck: 'false', placeholder: 'http://spoolman:8000',
      value: status.url || '', disabled: status.from_env });
    const save = async () => {
      try {
        await api('PUT', '/api/spoolman/settings', { url: input.value });
        toast(t('spoolman.saved'));
      } catch (err) { toast(err.message, 'error'); }
      draw();
    };
    const test = async () => {
      try { await api('POST', '/api/spoolman/test'); toast(t('spoolman.test_ok')); } catch (err) { toast(err.message, 'error'); }
    };
    const address = !setup ? null : h('div', { class: 'stack' },
      field(t('spoolman.address'), input, status.from_env ? t('spoolman.address_env') : t('spoolman.address_hint')),
      h('div', { class: 'row' },
        status.from_env ? null : h('button', { class: 'btn primary', type: 'button', onclick: save }, t('common.save')),
        status.enabled ? h('button', { class: 'btn', type: 'button', onclick: test }, t('spoolman.test')) : null));
    if (!status.enabled) {
      fill(card, foldHead('spoolman', t('spoolman.title'), { open: false }), h('p', { class: 'muted' }, t('spoolman.setup_intro')), address);
      card.hidden = false;
      return;
    }
    const sync = h('button', { class: 'btn primary', type: 'button', onclick: async (e) => {
      const button = e.currentTarget;
      button.disabled = true;
      if (await runSync()) onSynced();
      button.disabled = false;
      draw();
    } }, icon('sync'), h('span', {}, t('spoolman.sync')));
    // The filaments of the library go to Spoolman: asked first, with the numbers, like the other syncs.
    const push = async () => {
      try {
        const plan = await api('POST', '/api/spoolman/push-library?dry_run=1');
        const left = plan.left ? ` ${t('spoolman.push_left', plan)}` : '';
        if (!plan.created) { toast(t('spoolman.push_nothing') + left); return; }
        if (!(await confirmDialog(t('spoolman.push_confirm', plan) + left, t('spoolman.push_do')))) return;
        const done = await api('POST', '/api/spoolman/push-library');
        toast(t('spoolman.push_done', done) + (done.left ? ` ${t('spoolman.push_left', done)}` : ''));
      } catch (err) { toast(err.message, 'error'); }
    };
    // The rolls typed in here become spools in Spoolman and are linked to them: asked first, with the numbers.
    const pushRolls = async () => {
      try {
        const plan = await api('POST', '/api/spoolman/push-rolls?dry_run=1');
        const left = plan.left ? ` ${t('spoolman.push_left', plan)}` : '';
        if (!plan.created) { toast(t('spoolman.rolls_nothing') + left); return; }
        if (!(await confirmDialog(t('spoolman.rolls_confirm', plan) + left, t('spoolman.rolls_do')))) return;
        const done = await api('POST', '/api/spoolman/push-rolls');
        toast(t('spoolman.rolls_done', done) + (done.left ? ` ${t('spoolman.push_left', done)}` : ''));
        onSynced();
      } catch (err) { toast(err.message, 'error'); }
      draw();
    };
    fill(card, foldHead('spoolman', t('spoolman.title'), { open: false }),
      h('p', { class: 'muted' }, t('spoolman.intro')),
      h('p', { class: 'hint breakable' }, t('spoolman.status', { host: status.host, n: status.rolls,
        when: status.last_sync ? formatDateTime(status.last_sync, { dateStyle: 'short', timeStyle: 'short' }) : t('spoolman.never') })),
      status.pending ? h('p', { class: 'notice', role: 'status' }, t('spoolman.pending', { n: status.pending })) : null,
      status.can_sync ? h('div', { class: 'row' }, sync,
        h('button', { class: 'btn', type: 'button', onclick: push }, t('spoolman.push')),
        h('button', { class: 'btn', type: 'button', onclick: pushRolls }, t('spoolman.rolls'))) : h('p', { class: 'hint' }, t('spoolman.admin_only')),
      setup ? h('p', { class: 'hint' }, t('spoolman.push_hint')) : null,
      setup ? h('p', { class: 'hint' }, t('spoolman.rolls_hint')) : null,
      address);
    card.hidden = false;
  }
  draw();
  return card;
}
