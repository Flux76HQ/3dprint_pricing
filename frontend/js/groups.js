import { api } from './api.js';
import { t } from './i18n.js';
import { listView, rowActions } from './listview.js';
import { askText, confirmDialog, fmt, h, icon, toast } from './ui.js';

// Groups of rolls: the bin, shelf, drawer or dry box a roll is kept in. A group is a name; a new name makes one (`filament_groups.py`). With Spoolman a group
// is a spool's location there: the server keeps the two in step, so nothing here knows about it except the badge on a group that has rolls from Spoolman.

/** The names of the groups there are, for a pull-down. It never fails a screen: without them a name can still be typed. */
export async function groupNames() {
  try { return (await api('GET', '/api/groups')).map((g) => g.name); } catch { return []; }
}

/** The field of a group in a form: a name typed, or one of the groups there are picked from the pull-down (a name that is new makes a group). */
export function groupField({ label, hint, value, onchange, id = 'f-group' }) {
  const list = h('datalist', { id: `${id}-list` });
  const input = h('input', { type: 'text', id, value: value || '', maxlength: 64, autocomplete: 'off', list: `${id}-list`, placeholder: t('group.field_ph'),
    oninput: (e) => onchange(e.target.value) });
  groupNames().then((names) => list.replaceChildren(...names.map((name) => h('option', { value: name }))));
  return h('div', { class: 'field' }, h('label', { for: id }, label), input, list, hint ? h('p', { class: 'hint' }, hint) : null);
}

// What the chosen rolls have in common: their group, when they are all in the same one, else nothing is suggested.
const sharedGroup = (rolls) => (rolls.length && rolls.every((r) => r.group_name === rolls[0].group_name) ? rolls[0].group_name || '' : '');

/** Asks for a group and puts these rolls (as the lists give them) in it; `reload` redraws the page. Resolves with true when it went through, so a list can let go of
    its selection. A roll that is a spool in Spoolman is moved there too: the server does that first, and when Spoolman cannot be reached the roll stays where it is. */
export async function moveRolls(rolls, reload) {
  const answer = await askText(t('group.move_title', { n: rolls.length }), {
    label: t('group.field'), hint: t('group.move_hint'), confirm: t('group.move_do'), list: await groupNames(), value: sharedGroup(rolls),
    empty: rolls.some((r) => r.group_name) ? t('group.move_none') : '' });
  if (answer === null) return false;
  let done = true;
  try {
    const { moved } = await api('POST', '/api/groups/assign', { ids: rolls.map((r) => r.id), group: answer });
    toast(moved ? t('group.moved', { n: moved }) : t('group.moved_none'));
  } catch (err) {
    toast(err.message, 'error');
    done = false;
  }
  reload();                                                          // some may have moved before it failed
  return done;
}

/** The Groups part of the Filament page: every group with what is in it, to add, rename and delete (an empty one). `show(name)` opens the rolls of a group. */
export function groupsView({ show }) {
  const reportError = (err) => toast(err.message, 'error');
  async function load() {
    try { view.setItems(await api('GET', '/api/groups')); } catch (err) { reportError(err); }
  }
  async function create() {
    const name = await askText(t('group.new_title'), { label: t('group.name'), hint: t('group.new_hint'), confirm: t('group.new') });
    if (name === null) return;
    try { await api('POST', '/api/groups', { name }); toast(t('group.created')); } catch (err) { reportError(err); }
    load();
  }
  async function rename(group) {
    const name = await askText(t('group.rename_title', { name: group.name }), { label: t('group.name'), value: group.name });
    if (name === null || name === group.name) return;
    try { await api('PATCH', `/api/groups/${group.id}`, { name }); toast(t('group.renamed')); } catch (err) { reportError(err); }
    load();
  }
  async function remove(group) {
    if (!(await confirmDialog(t('group.delete_confirm', { name: group.name })))) return;
    try { await api('DELETE', `/api/groups/${group.id}`); toast(t('group.deleted')); } catch (err) { reportError(err); }
    load();
  }

  // A group with rolls in it (archived ones too) is not deleted: its rolls are moved out first, and so a group that Spoolman still uses never comes back after it was deleted.
  const actions = (group) => rowActions([
    group.rolls ? { icon: 'search', label: t('group.show_rolls', { name: group.name }), onclick: () => show(group.name) } : null,
    { icon: 'edit', label: t('group.rename_named', { name: group.name }), onclick: () => rename(group) },
    group.in_use ? null : { icon: 'trash', danger: true, label: t('group.delete_named', { name: group.name }), onclick: () => remove(group) }]);
  const spoolmanBadge = (group) => (group.from_spoolman ? h('span', { class: 'badge' }, t('spoolman.badge')) : null);
  const view = listView({
    id: 'groups',
    search: { label: t('group.search'), placeholder: t('group.search_ph'), text: (g) => g.name },
    sorts: [
      { key: 'name', label: t('sort.name'), value: (g) => g.name },
      { key: 'rolls', label: t('sort.rolls'), value: (g) => g.rolls, desc: true },
      { key: 'left', label: t('sort.left'), value: (g) => Number(g.remaining_g), desc: true }],
    tie: (g) => g.name,
    columns: [
      { label: t('group.title'), sort: 'name', cls: 'main', cell: (g) => h('div', { class: 'cell-main' }, icon('folder'), h('div', {}, h('span', { class: 'cell-title' }, g.name, spoolmanBadge(g)))) },
      { label: t('sort.rolls'), sort: 'rolls', cls: 'num', cell: (g) => String(g.rolls) },
      { label: t('sort.left'), sort: 'left', cls: 'num strong', cell: (g) => `${fmt(g.remaining_g, 0)} g` },
      { label: t('list.actions'), cls: 'actions', cell: actions }],
    tile: (g) => h('article', { class: 'glass card item' },
      h('div', { class: 'item-head' }, icon('folder'),
        h('div', { class: 'grow' }, h('h3', {}, g.name, spoolmanBadge(g)), h('p', { class: 'muted' }, t('group.meta', { n: g.rolls, grams: fmt(g.remaining_g, 0) })))),
      actions(g)),
    empty: t('group.empty'), noMatch: t('list.no_match'),
  });
  return { el: h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('group.intro')), view.el), load, create };
}
