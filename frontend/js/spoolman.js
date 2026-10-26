import { api } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { confirmDialog, fill, h, icon, toast } from './ui.js';

/** The Spoolman card: where the rolls come from, when they were last read, and the Sync button. It stays hidden while there is no Spoolman
 * (`SPOOLMAN_URL`), so an installation without one looks as before. `onSynced` runs after a sync that went through (to redraw a list). */
export function spoolmanCard(onSynced = () => {}) {
  const card = h('div', { class: 'glass card stack', hidden: true });

  async function draw() {
    let status;
    try { status = await api('GET', '/api/spoolman'); } catch { return; }          // a convenience: the page works without it
    if (!status.enabled) { card.hidden = true; return; }
    const sync = h('button', { class: 'btn primary', type: 'button', onclick: async (e) => {
      const button = e.currentTarget;
      button.disabled = true;
      try {
        const done = await api('POST', '/api/spoolman/sync');
        toast(t('spoolman.done', done));
        onSynced();
      } catch (err) { toast(err.message, 'error'); }
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
    fill(card, h('h2', {}, t('spoolman.title')),
      h('p', { class: 'muted' }, t('spoolman.intro')),
      h('p', { class: 'hint breakable' }, t('spoolman.status', { host: status.host, n: status.rolls,
        when: status.last_sync ? formatDateTime(status.last_sync, { dateStyle: 'short', timeStyle: 'short' }) : t('spoolman.never') })),
      status.pending ? h('p', { class: 'notice', role: 'status' }, t('spoolman.pending', { n: status.pending })) : null,
      status.can_sync ? h('div', { class: 'row' }, sync,
        h('button', { class: 'btn', type: 'button', onclick: push }, t('spoolman.push')),
        h('button', { class: 'btn', type: 'button', onclick: pushRolls }, t('spoolman.rolls'))) : h('p', { class: 'hint' }, t('spoolman.admin_only')),
      status.can_sync ? h('p', { class: 'hint' }, t('spoolman.push_hint')) : null,
      status.can_sync ? h('p', { class: 'hint' }, t('spoolman.rolls_hint')) : null);
    card.hidden = false;
  }
  draw();
  return card;
}
