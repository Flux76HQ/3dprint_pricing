// Settings -> Gebruikers (administrators only; the server refuses these calls to anyone else): who may sign in, a link to invite
// someone, a new link for someone who is locked out, promoting a regular user to administrator, and removing a person.
// The link is shown once, when it is made: the server keeps only its hash and cannot show it again.
import { api } from './api.js';
import { formatDate, t } from './i18n.js';
import { confirmIdentity } from './password.js';
import { confirmDialog, field, fill, h, icon, toast } from './ui.js';

const signIn = (u) => {
  const ways = [];
  if (u.passkeys) ways.push(t('users.passkeys', { n: u.passkeys }));
  if (u.password) ways.push(t('users.password'));
  return ways.length ? ways.join(' · ') : t('users.no_login');
};

/** The box that shows a fresh link, with a Copy button: the only time it can be seen. */
function linkBox(made, intro) {
  const input = h('input', { type: 'text', readonly: true, value: made.url, 'aria-label': t('users.link'), onfocus: (e) => e.target.select() });
  return h('div', { class: 'notice info stack', role: 'status' },
    h('strong', {}, intro),
    h('div', { class: 'row' }, input, h('button', { class: 'btn', type: 'button', onclick: async () => {
      try { await navigator.clipboard.writeText(made.url); toast(t('common.copied')); } catch { input.select(); toast(t('common.copy_failed'), 'error'); }
    } }, t('common.copy'))),
    h('p', { class: 'hint' }, t('users.link_once', { date: formatDate(made.expires_at, { dateStyle: 'long' }) })));
}

export function usersCards() {
  const listBox = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  const invitesBox = h('div', { class: 'stack' });
  const linkSlot = h('div');
  const name = h('input', { type: 'text', id: 'invite-for', autocomplete: 'off', maxlength: 60 });
  const make = h('button', { class: 'btn primary', type: 'submit' }, icon('plus'), h('span', {}, t('users.make_link')));

  const shown = (made, intro) => linkSlot.replaceChildren(linkBox(made, intro));

  async function load() {
    let data;
    try { data = await api('GET', '/api/users'); } catch (e) { fill(listBox, h('p', { class: 'error' }, e.message)); return; }
    fill(listBox, h('ul', { class: 'plain-list' }, data.users.map(row)));
    fill(invitesBox, data.invitations.length
      ? h('ul', { class: 'plain-list' }, data.invitations.map((i) => h('li', { class: 'list-row' },
        h('div', {}, h('strong', {}, i.name || t('users.unnamed')),
          h('p', { class: 'muted' }, `${i.kind === 'reset' ? t('users.kind_reset') : t('users.kind_new')} · ${t('users.expires', { date: formatDate(i.expires_at, { dateStyle: 'medium' }) })}`)),
        h('button', { class: 'btn small', type: 'button', onclick: async () => {
          try { await api('DELETE', `/api/users/invites/${i.id}`); toast(t('users.revoked')); load(); } catch (e) { toast(e.message, 'error'); }
        } }, t('users.revoke')))))
      : h('p', { class: 'muted' }, t('users.no_invites')));
  }

  function row(u) {
    const admin = u.role === 'admin';
    const badges = [u.is_owner ? h('span', { class: 'badge' }, t('users.owner')) : admin ? h('span', { class: 'badge' }, t('users.admin')) : h('span', { class: 'badge muted' }, t('users.user')),
      u.you ? h('span', { class: 'badge muted' }, t('users.you')) : null];
    const buttons = [];
    if (!u.is_owner && !u.you) {
      buttons.push(
        h('button', { class: 'btn small', type: 'button', onclick: () => (admin ? demote(u) : promote(u)) }, admin ? t('users.make_user') : t('users.make_admin')),
        h('button', { class: 'btn small', type: 'button', onclick: () => resetLink(u) }, t('users.new_link')),
        h('button', { class: 'btn small danger', type: 'button', 'aria-label': t('common.delete_named', { name: u.name }), onclick: () => remove(u) }, icon('trash')));
    }
    return h('li', { class: 'list-row' },
      h('div', {}, h('strong', {}, u.name, ' ', ...badges), h('p', { class: 'muted' }, `${signIn(u)} · ${t('users.since', { date: formatDate(u.created_at, { dateStyle: 'medium' }) })}`)),
      buttons.length ? h('div', { class: 'row' }, buttons) : null);
  }

  // Making someone an administrator gives them every right, so it asks for a fresh confirmation (a passkey, or the password and a code).
  async function promote(u) {
    if (!(await confirmDialog(t('users.promote_confirm', { name: u.name }), t('users.make_admin')))) return;
    try {
      const proof = await confirmIdentity({ action: 'user-promote', target: u.id, title: t('users.promote_title', { name: u.name }),
        message: t('users.promote_msg'), confirmLabel: t('users.make_admin') });
      if (!proof) return;
      await api('PUT', `/api/users/${u.id}/role`, { role: 'admin', ...proof });
      toast(t('users.promoted', { name: u.name }));
    } catch (e) { toast(e.message, 'error'); }
    load();
  }

  async function demote(u) {
    if (!(await confirmDialog(t('users.demote_confirm', { name: u.name }), t('users.make_user')))) return;
    try { await api('PUT', `/api/users/${u.id}/role`, { role: 'user' }); toast(t('users.demoted', { name: u.name })); } catch (e) { toast(e.message, 'error'); }
    load();
  }

  async function resetLink(u) {
    if (!(await confirmDialog(t('users.reset_confirm', { name: u.name }), t('users.new_link')))) return;
    try {
      let proof = {};
      if (u.role === 'admin') {                                  // a link for an administrator opens everything: confirm it is really you
        proof = await confirmIdentity({ action: 'user-reset', target: u.id, title: t('users.reset_title', { name: u.name }),
          message: t('users.reset_msg'), confirmLabel: t('users.new_link') });
        if (!proof) return;
      }
      shown(await api('POST', `/api/users/${u.id}/reset`, proof), t('users.reset_made', { name: u.name }));
      load();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function remove(u) {
    if (!(await confirmDialog(t('users.remove_confirm', { name: u.name })))) return;
    try { await api('DELETE', `/api/users/${u.id}`); toast(t('users.removed', { name: u.name })); } catch (e) { toast(e.message, 'error'); }
    load();
  }

  load();
  return [
    h('div', { class: 'glass card stack' }, h('h2', {}, t('users.title')), h('p', { class: 'muted' }, t('users.hint')), listBox),
    h('div', { class: 'glass card stack' }, h('h2', {}, t('users.invite_title')), h('p', { class: 'muted' }, t('users.invite_intro')),
      h('form', { class: 'stack', onsubmit: async (e) => {
        e.preventDefault();
        make.disabled = true;
        try {
          shown(await api('POST', '/api/users/invites', { name: name.value }), t('users.link_made'));
          name.value = '';
          load();
        } catch (err) { toast(err.message, 'error'); } finally { make.disabled = false; }
      } }, field(t('users.invite_name'), name, t('users.invite_name_hint')), h('div', { class: 'row' }, make)),
      linkSlot),
    h('div', { class: 'glass card stack' }, h('h2', {}, t('users.open_title')), invitesBox),
  ];
}
