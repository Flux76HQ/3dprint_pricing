import { api } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { fill, fmt, foldHead, h, icon, toast } from './ui.js';

// The picker of a new roll's form that offers SpoolmanDB (https://github.com/Donkie/SpoolmanDB, MIT): brand, then material, then the filament,
// and one pick fills in the rest of the form. It is what makes scanning a roll the app does not know yet quick: the barcode is already in the
// form, the filament is picked here, and only the price is left. What a pick fills in is decided by the server (`fill` in each row: a filament the
// installation already has keeps the spelling it has, so a Dutch "Geel" is not added again as "Yellow"); this only shows the rows and hands
// the chosen one on. The data is the snapshot that ships with the app, and the panel names its source.

/** `onPick(row)` gets the chosen row: `{ id, name, weight, diameter, spool_weight, known, fill }`. Returns the box (hidden while there is nothing to offer). */
export function spoolmanDbPicker({ onPick }) {
  const placeholder = (key) => h('option', { value: '' }, t(key));
  const brand = h('select', { id: 'f-smdb-brand', 'aria-label': t('spoolmandb.brand') }, placeholder('spoolmandb.brand_pick'));
  const material = h('select', { id: 'f-smdb-material', 'aria-label': t('spoolmandb.material'), disabled: true }, placeholder('spoolmandb.material_pick'));
  const search = h('input', { type: 'search', id: 'f-smdb-search', autocomplete: 'off', spellcheck: 'false', disabled: true,
    placeholder: t('spoolmandb.search'), 'aria-label': t('spoolmandb.search'), oninput: () => draw() });
  const filament = h('select', { id: 'f-smdb-filament', 'aria-label': t('spoolmandb.filament'), disabled: true }, placeholder('spoolmandb.filament_pick'));
  const status = h('p', { class: 'hint', role: 'status' });
  const source = h('p', { class: 'hint' });
  const box = h('div', { class: 'notice stack', hidden: true, role: 'group', 'aria-labelledby': 'f-smdb-title' },
    h('strong', { id: 'f-smdb-title' }, t('spoolmandb.title')), h('p', { class: 'hint' }, t('spoolmandb.hint')),
    h('div', { class: 'two even' }, brand, material), search, filament, status, source);

  let brands = [];
  let rows = [];                 // the filaments of the chosen brand and material, as the server listed them
  let asked = 0;                 // a slow answer for a brand that was left again is not drawn

  const label = (row) => {
    const own = row.known ? ` · ✓ ${t('spoolmandb.known', { name: row.known.colour })}` : '';
    return `${row.name} · ${fmt(row.weight / 1000)} kg · ${fmt(row.diameter)} mm${own}`;
  };
  const clear = (select, key) => { select.replaceChildren(placeholder(key)); select.disabled = true; };

  function draw() {
    const wanted = search.value.trim().toLowerCase();
    const shown = rows.filter((row) => !wanted || row.name.toLowerCase().includes(wanted));
    filament.replaceChildren(placeholder('spoolmandb.filament_pick'), ...shown.map((row) => h('option', { value: row.id }, label(row))));
    filament.disabled = !rows.length;
    status.textContent = rows.length && !shown.length ? t('spoolmandb.none') : '';
  }

  brand.addEventListener('change', () => {
    rows = [];
    clear(material, 'spoolmandb.material_pick');
    clear(filament, 'spoolmandb.filament_pick');
    search.value = '';
    search.disabled = true;
    status.textContent = '';
    const chosen = brands.find((b) => b.name === brand.value);
    if (!chosen) return;
    material.append(...chosen.materials.map((m) => h('option', { value: m }, m)));
    material.disabled = false;
    if (chosen.materials.length === 1) { material.value = chosen.materials[0]; material.dispatchEvent(new Event('change')); }
  });

  material.addEventListener('change', async () => {
    rows = [];
    clear(filament, 'spoolmandb.filament_pick');
    search.value = '';
    search.disabled = !material.value;
    if (!material.value) return;
    const mine = ++asked;
    status.textContent = t('spoolmandb.loading');
    try {
      const answer = await api('GET', `/api/spoolmandb/filaments?brand=${encodeURIComponent(brand.value)}&material=${encodeURIComponent(material.value)}`);
      if (mine !== asked) return;
      rows = answer.filaments;
      draw();
    } catch (e) { if (mine === asked) status.textContent = e.message; }
  });

  filament.addEventListener('change', () => {
    const row = rows.find((r) => r.id === filament.value);
    if (!row) return;
    onPick(row);
    status.textContent = [row.known ? t('spoolmandb.filled_known', { name: row.name, own: row.known.colour }) : t('spoolmandb.filled', { name: row.name }),
      row.spool_weight ? t('spoolmandb.spool_weight', { g: fmt(row.spool_weight, 0) }) : ''].filter(Boolean).join(' ');
  });

  // A convenience: when the list cannot be had the form is filled in by hand as before, and says nothing.
  api('GET', '/api/spoolmandb').then((overview) => {
    brands = overview.brands;
    brand.append(...brands.map((b) => h('option', { value: b.name }, b.name)));
    const s = overview.source;
    source.append(t('spoolmandb.source', { licence: s.licence, copyright: s.copyright, date: s.fetched }), ' ',
      h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, t('spoolmandb.link')));
    box.hidden = false;
  }).catch(() => {});
  return box;
}

/** The card of Settings -> Filaments: which SpoolmanDB list is in use (the one that shipped with the app, or the one an administrator fetched), how big and
 * from when, the source, and the button that fetches the project's newest list. The server allows it once a day (`next_sync_at`), and only for an
 * administrator (`can_sync`); the button says when it is possible again. A sync only replaces the list that is offered: no roll and no library entry changes. */
export function spoolmanDbCard() {
  const card = h('div', { class: 'glass card stack', hidden: true });
  const day = (iso) => formatDateTime(`${iso}T12:00:00`, { dateStyle: 'short' });          // a date without a time, read at noon so no time zone moves it
  const moment = (iso) => formatDateTime(iso, { dateStyle: 'short', timeStyle: 'short' });

  async function draw() {
    let info;
    try { info = await api('GET', '/api/spoolmandb'); } catch { card.hidden = true; return; }          // a convenience: Settings works without it
    const wait = info.next_sync_at && new Date(info.next_sync_at) > new Date() ? info.next_sync_at : null;
    const counts = { rows: fmt(info.rows, 0), brands: fmt(info.brands.length, 0) };
    const sync = h('button', { class: 'btn primary', type: 'button', disabled: !!wait, onclick: async (e) => {
      const button = e.currentTarget;
      button.disabled = true;
      try {
        toast(t('spoolmandb.sync_done', await api('POST', '/api/spoolmandb/sync').then((r) => ({ ...r, rows: fmt(r.rows, 0), brands: fmt(r.brands, 0) }))));
      } catch (err) { toast(err.message, 'error'); }
      draw();
    } }, icon('sync'), h('span', {}, t('spoolmandb.card_sync')));
    fill(card, foldHead('spoolmandb', t('spoolmandb.card_title'), { open: false }),
      h('p', { class: 'muted' }, t('spoolmandb.card_intro')),
      h('p', { class: 'hint breakable', role: 'status' }, info.origin === 'synced'
        ? t('spoolmandb.card_synced', { ...counts, when: moment(info.synced_at) })
        : t('spoolmandb.card_shipped', { ...counts, date: day(info.source.fetched) })),
      info.can_sync ? h('div', { class: 'row' }, sync) : h('p', { class: 'hint' }, t('spoolmandb.card_admin_only')),
      info.can_sync && wait ? h('p', { class: 'hint' }, t('spoolmandb.card_next', { when: moment(wait) })) : null,
      h('p', { class: 'hint' }, t('spoolmandb.card_hint')),
      h('p', { class: 'hint' }, t('spoolmandb.source', { licence: info.source.licence, copyright: info.source.copyright, date: info.source.fetched }), ' ',
        h('a', { href: info.source.url, target: '_blank', rel: 'noopener noreferrer' }, t('spoolmandb.link'))));
    card.hidden = false;
  }
  draw();
  return card;
}
