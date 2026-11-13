import { api } from './api.js';
import { t } from './i18n.js';
import { fmt, h } from './ui.js';

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
