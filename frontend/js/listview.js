import { getLanguage, t } from './i18n.js';
import { goTo } from './pwa.js';
import { fill, h, icon } from './ui.js';

// One overview, the same on every page (3D models, orders, customers, filament, packaging, parts, printers, tariffs): a toolbar to search while
// typing, filter, sort and group, and the choice between tiles and a list. A page only says what its rows are; how an overview looks and
// behaves is decided here, so the pages cannot drift apart.

/** Text as it is compared in a search: lower case, without accents. */
export const folded = (v) => String(v ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const norm = (v) => String(v ?? '').trim().toLowerCase();
const VIEW_LABELS = { tiles: 'list.view_tiles', list: 'list.view_list' };
const many = (v) => (Array.isArray(v) ? v : [v]).map((x) => String(x ?? '').trim()).filter(Boolean);

function remembered(id) {
  try { return JSON.parse(localStorage.getItem(`pp-list-${id}`) || '{}') || {}; } catch { return {}; }
}

/**
 * `config`:
 *   id        remembers the view, the order and the grouping in this browser (`pp-list-<id>`)
 *   memory    an object of the page's own: what was typed and filtered is kept in it, for a page that is drawn again (the parts of Filament)
 *   search    { label, placeholder, text: (row) => text or texts, extra: a node next to the field (the barcode scanner) }
 *   filters   [{ key, label, all, value: (row) => text or texts }]: pull-downs, filled from the rows; each narrows what the next one offers
 *   chips     { label, all, options: [[value, label]], value: (row) => value }: one row of choices that is always in sight (the status of an order)
 *   sorts     [{ key, label, value: (row) => text or number, desc }]: the first is the order a first visit gets; `desc` starts it the other way round
 *   tie       (row) => text: the order of rows that are equal (their name)
 *   group     { label, key: (row) => text, head: (rows) => ({ icon, title, meta }) }: a switch that keeps the rows of one kind together
 *   columns   [{ label, cell: (row) => node or text, sort: a key of `sorts`, cls, wide: left out on a narrow screen }]
 *   tile      (row) => node; `tilesClass` is the class of the grid they are laid out in
 *   href      (row) => address: a click anywhere on a row of the list opens it
 *   rowClass  (row) => class of a row in the list
 *   views     ['tiles', 'list'] (the first is what a first visit gets); one of them leaves the switch out
 *   summary   (rows) => node or text above the rows (totals of what is listed)
 *   toggles   nodes shown with the filters (show archived)
 *   empty     the text of an overview with nothing in it; `noMatch` the text when the search or the filters leave nothing
 */
export function listView(config) {
  const saved = remembered(config.id);
  const views = config.views || ['tiles', 'list'];
  const sorts = config.sorts || [];
  const memory = config.memory || {};
  memory.query ??= '';
  memory.filters ??= {};
  memory.chip ??= '';
  const state = {
    view: views.includes(saved.view) ? saved.view : views[0],
    by: sorts.some((s) => s.key === saved.by) ? saved.by : sorts[0]?.key,
    dir: saved.dir === 1 || saved.dir === -1 ? saved.dir : (sorts[0]?.desc ? -1 : 1),
    grouped: config.group ? saved.grouped !== false : false,
    filtersOpen: false,
  };
  let items = [];
  let loaded = false;

  const remember = () => {
    try { localStorage.setItem(`pp-list-${config.id}`, JSON.stringify({ view: state.view, by: state.by, dir: state.dir, grouped: state.grouped })); } catch { /* not remembered */ }
  };

  // --- what is shown -------------------------------------------------------------
  const words = () => folded(memory.query).split(/\s+/).filter(Boolean);
  const searched = (row) => {
    const w = words();
    if (!w.length || !config.search) return true;
    const text = folded(many(config.search.text(row)).join(' '));
    return w.every((word) => text.includes(word));
  };
  const filters = config.filters || [];
  const passes = (row, upTo = filters.length) => filters.slice(0, upTo).every((f) => !memory.filters[f.key]
    || many(f.value(row)).some((v) => norm(v) === memory.filters[f.key]));
  const chipped = (row) => !config.chips || !memory.chip || String(config.chips.value(row)) === memory.chip;
  const activeFilters = () => filters.filter((f) => memory.filters[f.key]).length;
  const narrowed = () => words().length > 0 || activeFilters() > 0 || !!memory.chip;

  function ordered(rows) {
    const sort = sorts.find((s) => s.key === state.by);
    const tie = config.tie || (() => '');
    const compare = (x, y) => (typeof x === 'number' && typeof y === 'number' ? x - y
      : String(x ?? '').localeCompare(String(y ?? ''), getLanguage(), { numeric: true, sensitivity: 'base' }));
    return [...rows].sort((a, b) => (sort ? compare(sort.value(a), sort.value(b)) * state.dir : 0) || compare(tie(a), tie(b)));
  }

  // --- the toolbar ---------------------------------------------------------------
  const input = config.search ? h('input', { type: 'search', value: memory.query, autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false',
    enterkeyhint: 'search', placeholder: config.search.placeholder, 'aria-label': config.search.label,
    oninput: (e) => { memory.query = e.target.value; draw(); },
    onkeydown: (e) => { if (e.key === 'Escape' && input.value) { e.preventDefault(); setQuery(''); } } }) : null;
  function setQuery(value) {
    memory.query = value;
    if (input) input.value = value;
    draw();
  }

  const filterButton = filters.length ? h('button', { type: 'button', class: 'btn tool', 'aria-expanded': 'false', 'aria-controls': `filters-${config.id}`,
    onclick: () => { state.filtersOpen = !state.filtersOpen; drawFilters(); } }, icon('filter'), h('span', {}, t('filter.title')), h('span', { class: 'count-dot', hidden: true })) : null;
  const selects = Object.fromEntries(filters.map((f) => [f.key, h('select', { id: `filter-${config.id}-${f.key}`, 'aria-label': t('filter.by', { name: f.label.toLowerCase() }),
    onchange: (e) => { memory.filters[f.key] = e.target.value; draw(); } })]));
  const clearButton = h('button', { class: 'btn tool', type: 'button', hidden: true, onclick: () => clearAll() }, icon('close'), h('span', {}, t('filter.clear')));
  const filterRow = filters.length ? h('div', { class: 'list-filters', id: `filters-${config.id}`, role: 'group', 'aria-label': t('filter.group'), hidden: true },
    filters.map((f) => h('div', { class: 'list-filter' }, h('label', { for: `filter-${config.id}-${f.key}` }, f.label), selects[f.key]))) : null;

  function clearAll() {
    for (const f of filters) memory.filters[f.key] = '';
    memory.chip = '';
    setQuery('');
  }

  function drawFilters() {
    // Not before the rows are there: with nothing to choose from, a filter that was kept from the other part of the page would be dropped.
    if (loaded) filters.forEach((f, i) => {
      const seen = new Map();                                      // narrowed by the filters before this one
      for (const row of items.filter((r) => passes(r, i))) for (const v of many(f.value(row))) if (!seen.has(norm(v))) seen.set(norm(v), f.name ? f.name(v) : v);
      const options = [...seen].sort((a, b) => a[1].localeCompare(b[1], getLanguage(), { numeric: true }));
      const select = selects[f.key];
      select.replaceChildren(h('option', { value: '' }, f.all), ...options.map(([value, label]) => h('option', { value }, label)));
      select.value = options.some(([value]) => value === memory.filters[f.key]) ? memory.filters[f.key] : '';
      memory.filters[f.key] = select.value;
    });
    if (!filterButton) return;
    const n = activeFilters();
    const open = state.filtersOpen || n > 0;
    filterRow.hidden = !open;
    filterButton.setAttribute('aria-expanded', String(open));
    filterButton.setAttribute('aria-pressed', String(n > 0));
    const dot = filterButton.querySelector('.count-dot');
    dot.hidden = !n;
    dot.textContent = String(n);
  }

  const chips = config.chips ? h('div', { class: 'chips', role: 'group', 'aria-label': config.chips.label }) : null;
  function drawChips() {
    if (!chips) return;
    const count = (value) => items.filter((row) => searched(row) && passes(row) && (!value || String(config.chips.value(row)) === value)).length;
    fill(chips, [['', config.chips.all], ...config.chips.options].map(([value, label]) => h('button', { type: 'button', class: 'seg', 'aria-pressed': String(memory.chip === value),
      onclick: () => { memory.chip = value; draw(); } }, label, h('span', { class: 'chip-count' }, String(count(value))))));
  }

  const sortSelect = sorts.length ? h('select', { class: 'sort-select', 'aria-label': t('sort.label'),
    onchange: (e) => { setSort(e.target.value, sorts.find((s) => s.key === e.target.value)?.desc ? -1 : 1); } },
  sorts.map((s) => h('option', { value: s.key }, s.label))) : null;
  const dirButton = sorts.length ? h('button', { type: 'button', class: 'btn tool icon-only', onclick: () => setSort(state.by, -state.dir) }) : null;
  function setSort(by, dir) {
    state.by = by;
    state.dir = dir;
    remember();
    draw();
  }
  function drawSort() {
    if (!sortSelect) return;
    sortSelect.value = state.by;
    dirButton.replaceChildren(icon(state.dir > 0 ? 'sort-up' : 'sort-down'));
    const label = t(state.dir > 0 ? 'sort.asc' : 'sort.desc');
    dirButton.setAttribute('aria-label', t('list.direction', { direction: label }));
    dirButton.title = label;
  }

  const groupSwitch = config.group ? h('label', { class: 'check tool-check' },
    h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: state.grouped, onchange: (e) => { state.grouped = e.target.checked; remember(); draw(); } }),
    config.group.label) : null;

  const viewButtons = views.length > 1 ? h('div', { class: 'segmented view-switch', role: 'group', 'aria-label': t('list.view') },
    views.map((view) => h('button', { type: 'button', class: 'seg', 'data-view': view, title: t(VIEW_LABELS[view]), 'aria-label': t(VIEW_LABELS[view]),
      onclick: () => { state.view = view; remember(); draw(); } }, icon(view === 'list' ? 'view-list' : 'view-tiles')))) : null;

  const count = h('p', { class: 'list-count muted', role: 'status' });
  const body = h('div', { class: 'list-body' }, h('p', { class: 'muted' }, t('common.loading')));
  const summary = h('div', { class: 'list-summary', hidden: true });

  const tools = h('div', { class: 'list-tools' },
    h('div', { class: 'list-tools-row' },
      input ? h('div', { class: 'search-bar', role: 'search' }, h('div', { class: 'search-field' }, icon('search'), input), config.search.extra || null) : null,
      h('div', { class: 'list-controls' },
        filterButton,
        sortSelect ? h('div', { class: 'sort-control', role: 'group', 'aria-label': t('sort.label') }, sortSelect, dirButton) : null,
        viewButtons)),
    filterRow,
    h('div', { class: 'list-tools-row sub' }, chips, groupSwitch, ...(config.toggles || []), h('span', { class: 'grow' }), count, clearButton));

  // --- the rows ------------------------------------------------------------------
  function groupsOf(rows) {
    if (!config.group || !state.grouped) return null;
    const found = new Map();                                        // in the order of the rows: the group of the first row comes first
    for (const row of rows) {
      const key = config.group.key(row);
      if (!found.has(key)) found.set(key, []);
      found.get(key).push(row);
    }
    return [...found.values()];
  }

  const groupHead = (rows) => {
    const head = config.group.head(rows);
    return [head.icon || null, h('span', { class: 'group-title' }, head.title), head.meta ? h('span', { class: 'group-meta muted' }, head.meta) : null,
      h('span', { class: 'badge muted' }, String(rows.length))];
  };

  function tiles(rows) {
    const grid = (list) => h('div', { class: config.tilesClass || 'cards' }, list.map((row) => config.tile(row)));
    const groups = groupsOf(rows);
    if (!groups) return grid(rows);
    return h('div', { class: 'stack groups' }, groups.map((list) => h('section', { class: 'group' }, h('h2', { class: 'group-head' }, groupHead(list)), grid(list))));
  }

  // A click on a row opens it, unless it was on something that does its own thing (a link, a button, the status of an order).
  const open = (row) => (e) => {
    if (e.target.closest('a, button, select, input, label') || window.getSelection()?.toString()) return;
    goTo(config.href(row));
  };

  function table(rows) {
    const columns = config.columns;
    const headCell = (col) => {
      const cls = [col.cls, col.wide ? 'wide' : ''].filter(Boolean).join(' ') || null;
      if (!col.sort) return h('th', { scope: 'col', class: cls }, col.label);
      const active = state.by === col.sort;
      return h('th', { scope: 'col', class: cls, 'aria-sort': active ? (state.dir > 0 ? 'ascending' : 'descending') : null },
        h('button', { type: 'button', class: 'th-sort', onclick: () => setSort(col.sort, active ? -state.dir : (sorts.find((s) => s.key === col.sort)?.desc ? -1 : 1)) },
          h('span', {}, col.label), icon(active && state.dir < 0 ? 'sort-down' : 'sort-up')));
    };
    const line = (row) => h('tr', { class: [config.href ? 'opens' : '', config.rowClass ? config.rowClass(row) : ''].filter(Boolean).join(' ') || null, onclick: config.href ? open(row) : null },
      columns.map((col, i) => h(i === 0 ? 'th' : 'td', { scope: i === 0 ? 'row' : null, class: [col.cls, col.wide ? 'wide' : ''].filter(Boolean).join(' ') || null }, col.cell(row))));
    const groups = groupsOf(rows);
    return h('div', { class: 'table-wrap glass card' }, h('table', { class: 'data-table' },
      h('thead', {}, h('tr', {}, columns.map(headCell))),
      groups
        ? groups.map((list) => h('tbody', {}, h('tr', { class: 'group-row' }, h('th', { colspan: columns.length, scope: 'rowgroup' }, h('div', { class: 'group-head' }, groupHead(list)))), list.map(line)))
        : h('tbody', {}, rows.map(line))));
  }

  function draw() {
    drawFilters();
    drawChips();
    drawSort();
    viewButtons?.querySelectorAll('.seg').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.view === state.view)));
    if (groupSwitch) groupSwitch.hidden = !items.length;
    clearButton.hidden = !narrowed();
    if (!loaded) return;
    const rows = ordered(items.filter((row) => searched(row) && passes(row) && chipped(row)));
    count.textContent = !items.length ? '' : (rows.length === items.length ? t('list.count', { n: rows.length }) : t('list.count_of', { n: rows.length, total: items.length }));
    const extra = rows.length && config.summary ? config.summary(rows) : null;
    summary.hidden = !extra;
    if (extra) fill(summary, extra);
    if (!rows.length) {
      // No dead end: say why nothing is listed, and offer the way back when it is the search or a filter.
      fill(body, h('div', { class: 'empty glass card' }, h('p', {}, items.length ? config.noMatch : config.empty),
        items.length ? h('button', { class: 'btn', type: 'button', onclick: clearAll }, t('filter.clear')) : null));
      return;
    }
    fill(body, state.view === 'list' && config.columns ? table(rows) : tiles(rows));
  }

  draw();
  return {
    el: h('div', { class: 'list-view' }, tools, summary, body),
    setItems(rows) { items = rows; loaded = true; draw(); },
    setQuery,
    refresh: draw,
    get query() { return memory.query; },
  };
}

/** The buttons of a row or tile, as one compact group: [{ icon, label, onclick, danger, href }], nulls are left out. */
export function rowActions(actions) {
  return h('div', { class: 'row-actions' }, actions.filter(Boolean).map((a) => h(a.href ? 'a' : 'button', {
    class: `btn tool icon-only${a.danger ? ' danger' : ''}`, type: a.href ? null : 'button', href: a.href || null, title: a.label, 'aria-label': a.label,
    'aria-pressed': a.pressed == null ? null : String(a.pressed), onclick: a.onclick || null }, icon(a.icon))));
}
