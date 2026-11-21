import { api } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { fill, fmt, foldHead, h, icon, toast } from './ui.js';

// SpoolmanDB (https://github.com/Donkie/SpoolmanDB, MIT) in the fields of a new roll's form, not next to them: its brands are in the brand pull-down, the
// materials of the brand in the material pull-down, the colours of the brand and material in the colour pull-down, and choosing a colour fills in the
// rest (weight, diameter, colour code, temperatures). That is what makes a scanned roll the app does not know yet quick: the barcode is already in the form,
// brand, material and colour are chosen from lists, and only the price is left. What a choice fills in is decided by the server (`fill` in each row: a filament
// the installation already has keeps the spelling it has, so a Dutch "Geel" is not added again as "Yellow"); this only hands the rows to the form and picks
// the one a typed colour stands for. The list is the one in use (the snapshot that shipped with the app, or the one an administrator synced).

const norm = (v) => String(v || '').trim().toLowerCase();

/** What the roll form asks of SpoolmanDB: `overview()` (the source and the brands with their materials, or null when there is no list: the form then works as
    it always did) and `filaments(brand, material)` (the server's rows for that brand and material, `[]` when there are none). One request each, remembered. */
export function spoolmanDbCatalogue() {
  const overview = api('GET', '/api/spoolmandb').catch(() => null);          // a convenience: the form works without it
  const asked = new Map();
  return {
    overview: () => overview,
    filaments(brand, material) {
      const key = `${brand}\n${material}`;
      if (!asked.has(key)) {
        asked.set(key, api('GET', `/api/spoolmandb/filaments?brand=${encodeURIComponent(brand)}&material=${encodeURIComponent(material)}`)
          .then((answer) => answer.filaments).catch(() => []));
      }
      return asked.get(key);
    },
  };
}

/** The label of one filament in the colour pull-down: the name the installation uses (a filament it has keeps its own: "Geel"), SpoolmanDB's own name after it when
    that differs ("Geel (Yellow)"), and the weight and diameter that row comes in (one row per variant, so a choice says exactly which one is meant). */
export const colourLabel = (row) => `${row.known && norm(row.name) !== norm(row.fill.colour) ? `${row.fill.colour} (${row.name})` : row.fill.colour} · ${fmt(row.weight / 1000)} kg · ${fmt(row.diameter)} mm`;

/** The row a typed colour stands for, by the name the installation uses or by SpoolmanDB's own, in the weight and diameter the form has now, else the first
    one it comes in (the rows are sorted by name, weight, diameter). `null` when the colour is not one of them: it is then just text. */
export function rowFor(rows, typed, weight, diameter) {
  const wanted = norm(typed);
  const matches = wanted ? rows.filter((r) => norm(r.fill.colour) === wanted || norm(r.name) === wanted) : [];
  const w = Number(String(weight ?? '').replace(',', '.'));
  const d = Number(String(diameter ?? '').replace(',', '.'));
  return matches.find((r) => r.weight === w && r.diameter === d) || matches[0] || null;
}

/** What choosing this row did, for the line under the colour field. */
export const filledText = (row) => [row.known ? t('spoolmandb.filled_known', { name: row.name, own: row.known.colour }) : t('spoolmandb.filled', { name: row.name }),
  row.spool_weight ? t('spoolmandb.spool_weight', { g: fmt(row.spool_weight, 0) }) : ''].filter(Boolean).join(' ');

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
