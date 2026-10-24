import { api } from './api.js';
import { getLanguage, t } from './i18n.js';
import { colourOf, spoolIcon, stockTiles } from './filament-ui.js';
import { scanBarcode } from './scanner.js';
import { askChoice, confirmDialog, enhanceDialog, eur, field, fmt, h, icon, spoolName, toast } from './ui.js';

// Declarative config for the three inventory/rate screens. Money and quantities are
// sent as typed; the server validates and is the only place that decides what is valid.
const num = (v) => (v === '' || v == null ? '' : String(v).replace(',', '.'));

// Parts and accessories are the same kind of list: a name, a price per unit (piece, metre or kg) and notes.
const UNIT_OPTIONS = [['stuks', 'unit.pieces'], ['m', 'unit.meter'], ['g', 'unit.gram']];
const UNIT_PRICE = { stuks: 'parts.per_piece', m: 'parts.per_meter', g: 'parts.per_kg' };

function catalogue(id, path, text) {
  return {
    id, title: text.title, path, empty: text.empty, archivable: true,
    intro: text.intro,
    defaults: { name: '', price: '', unit: 'stuks', notes: '' },
    fields: [
      { key: 'name', label: t('common.name'), type: 'text', required: true, placeholder: text.name_ph },
      { key: 'unit', label: text.unit, type: 'select', options: UNIT_OPTIONS.map(([value, label]) => [value, t(label)]) },
      { key: 'price', label: text.price, type: 'number', required: true, hint: text.price_hint },
      { key: 'notes', label: t('common.notes'), type: 'textarea' },
    ],
    card(item) {
      return { title: item.name, subtitle: item.notes || null, stats: [[t(UNIT_PRICE[item.unit] || UNIT_PRICE.stuks), eur(item.price)]] };
    },
  };
}

// Built on every call, so the labels follow the language of the screen.
function resources() {
  return {
  filament: {
    id: 'filament', title: t('filament.title'), path: '/api/spools', empty: t('filament.empty'), archivable: true,
    intro: t('filament.intro'),
    defaults: { brand: '', product_type: '', material: '', colour: '', colour_hex: '', roll_weight_g: '1000', price: '', remaining_g: '1000',
      barcode: '', diameter_mm: '1.75', print_temp_c: '', bed_temp_c: '', notify_low: false, notes: '', add_to_library: true },
    fields: [
      { key: 'barcode', label: t('filament.barcode'), type: 'barcode', hint: t('filament.barcode_hint') },
      { key: 'brand', label: t('filament.brand'), type: 'text', required: true, placeholder: t('filament.brand_ph') },
      { key: 'product_type', label: t('filament.type'), type: 'text', placeholder: t('filament.type_ph'), hint: t('filament.type_hint') },
      { key: 'material', label: t('filament.material'), type: 'text', placeholder: t('filament.material_ph') },
      { key: 'colour', label: t('filament.colour'), type: 'text', placeholder: t('filament.colour_ph') },
      { key: 'colour_hex', label: t('filament.colour_hex'), type: 'color', hint: t('filament.colour_hex_hint') },
      { key: 'roll_weight_g', label: t('filament.roll_weight'), type: 'number', required: true },
      { key: 'price', label: t('filament.roll_price'), type: 'number', required: true },
      { key: 'remaining_g', label: t('filament.remaining'), type: 'number', required: true },
      { key: 'diameter_mm', label: t('filament.diameter'), type: 'number', required: true, list: ['1.75', '2.85'] },
      { key: 'print_temp_c', label: t('filament.print_temp'), type: 'number', placeholder: t('filament.print_temp_ph'), hint: t('filament.print_temp_hint') },
      { key: 'bed_temp_c', label: t('filament.bed_temp'), type: 'number', placeholder: t('filament.bed_temp_ph'), hint: t('filament.optional') },
      { key: 'notify_low', label: t('filament.notify_low'), type: 'checkbox', hint: t('filament.notify_low_hint') },
      { key: 'notes', label: t('common.notes'), type: 'textarea' },
      { key: 'add_to_library', label: t('library.also_add'), type: 'checkbox', hint: t('library.also_add_hint'), newOnly: true },
    ],
    card(item) {
      const perKg = Number(item.price) / Number(item.roll_weight_g) * 1000;
      const pct = Math.max(0, Math.min(100, Number(item.remaining_g) / Number(item.roll_weight_g) * 100));
      const bar = h('div', { class: 'meter', role: 'img',
        'aria-label': t('filament.meter', { left: fmt(item.remaining_g, 0), total: fmt(item.roll_weight_g, 0) }) }, h('span'));
      bar.firstChild.style.width = `${pct}%`;
      return {
        icon: spoolIcon(colourOf(item), 34),
        title: spoolName(item, ' · '),
        subtitle: [item.material, t('filament.per_roll_price', { price: eur(item.price) })].filter(Boolean).join(' · '),
        stats: [[t('filament.per_kg'), eur(perKg)], [t('filament.left'), `${fmt(item.remaining_g, 0)} g`], [t('filament.diameter_short'), `${fmt(item.diameter_mm)} mm`],
          ...(item.print_temp_c != null ? [[t('filament.print_temp_short'), `${item.print_temp_c} °C`]] : []),
          ...(item.bed_temp_c != null ? [[t('filament.bed_temp_short'), `${item.bed_temp_c} °C`]] : [])],
        extra: bar,
        footnote: item.barcode ? t('filament.barcode_note', { code: item.barcode }) : null,
      };
    },
  },
  verpakking: {
    id: 'packaging', title: t('packaging.title'), path: '/api/packaging', empty: t('packaging.empty'), archivable: true,
    intro: t('packaging.intro'),
    defaults: { name: '', price: '', notes: '' },
    fields: [
      { key: 'name', label: t('common.name'), type: 'text', required: true, placeholder: t('packaging.name_ph') },
      { key: 'price', label: t('packaging.price'), type: 'number', required: true, hint: t('packaging.price_hint') },
      { key: 'notes', label: t('common.notes'), type: 'textarea' },
    ],
    card(item) {
      return { title: item.name, subtitle: item.notes || null, stats: [[t('packaging.per_piece'), eur(item.price)]] };
    },
  },
  onderdelen: catalogue('parts', '/api/parts', {
    title: t('parts.title'), empty: t('parts.empty'), intro: t('parts.intro'), name_ph: t('parts.name_ph'), unit: t('parts.unit'),
    price: t('parts.price'), price_hint: t('parts.price_hint') }),
  accessoires: catalogue('accessories', '/api/accessories', {
    title: t('accessories.title'), empty: t('accessories.empty'), intro: t('accessories.intro'), name_ph: t('accessories.name_ph'),
    unit: t('accessories.unit'), price: t('accessories.price'), price_hint: t('accessories.price_hint') }),
  printers: {
    id: 'printer', title: t('printers.title'), path: '/api/printers', empty: t('printers.empty'), archivable: true,
    intro: t('printers.intro'),
    defaults: { name: '', purchase_price: '', lifetime_hours: '3000', power_kw: '0.15', notes: '' },
    fields: [
      { key: 'name', label: t('common.name'), type: 'text', required: true, placeholder: t('printers.name_ph') },
      { key: 'purchase_price', label: t('printers.purchase_price'), type: 'number', required: true },
      { key: 'lifetime_hours', label: t('printers.lifetime'), type: 'number', required: true },
      { key: 'power_kw', label: t('printers.power'), type: 'number', hint: t('printers.power_hint') },
      { key: 'notes', label: t('common.notes'), type: 'textarea' },
    ],
    card(item) {
      const perHour = Number(item.purchase_price) / Number(item.lifetime_hours);
      return {
        title: item.name,
        subtitle: t('printers.subtitle', { price: eur(item.purchase_price), hours: fmt(item.lifetime_hours, 0) }),
        stats: [[t('printers.depreciation'), t('printers.per_hour', { price: eur(perHour) })], [t('printers.power_short'), `${fmt(item.power_kw, 3)} kW`]],
      };
    },
  },
  energie: {
    id: 'tariff', title: t('energy.title'), path: '/api/tariffs', empty: t('energy.empty'), archivable: false,
    intro: t('energy.intro'),
    defaults: { name: '', price_per_kwh: '' },
    fields: [
      { key: 'name', label: t('common.name'), type: 'text', required: true, placeholder: t('energy.name_ph') },
      { key: 'price_per_kwh', label: t('energy.price'), type: 'number', required: true },
    ],
    card(item) {
      return {
        title: item.name, badge: item.is_default ? t('energy.default') : null,
        stats: [[t('energy.price_short'), t('energy.per_kwh', { price: eur(item.price_per_kwh) })]],
      };
    },
    actions(item, reload) {
      if (item.is_default) return [];
      return [h('button', { class: 'btn small', type: 'button', onclick: async () => {
        await api('PATCH', `${this.path}/${item.id}`, { is_default: true });
        reload();
      } }, t('energy.make_default'))];
    },
  },
  };
}

/** "Bambu Lab · Basic · Grijs · PLA · bijvulling": one entry of the filament library, in a line. */
export const libraryName = (e) => [spoolName(e, ' · '), e.material, e.refill ? t('library.refill_short') : ''].filter(Boolean).join(' · ');

/** The form of a filament library entry (Settings -> Filaments); `openForm` draws it like the other forms. */
export function libraryConfig() {
  return {
    id: 'library', path: '/api/filament-library',
    defaults: { brand: '', product_type: '', material: '', colour: '', colour_hex: '', filament_id: '', sku: '', barcode: '', refill: false,
      roll_weight_g: '1000', diameter_mm: '1.75', print_temp_c: '', bed_temp_c: '', price: '', notes: '' },
    fields: [
      { key: 'brand', label: t('filament.brand'), type: 'text', required: true, placeholder: t('filament.brand_ph') },
      { key: 'product_type', label: t('filament.type'), type: 'text', placeholder: t('filament.type_ph'), hint: t('filament.type_hint') },
      { key: 'material', label: t('filament.material'), type: 'text', placeholder: t('filament.material_ph') },
      { key: 'colour', label: t('filament.colour'), type: 'text', placeholder: t('filament.colour_ph') },
      { key: 'colour_hex', label: t('filament.colour_hex'), type: 'color', hint: t('filament.colour_hex_hint') },
      { key: 'filament_id', label: t('library.filament_id'), type: 'text', hint: t('library.filament_id_hint') },
      { key: 'sku', label: t('library.sku'), type: 'text', hint: t('library.sku_hint') },
      { key: 'barcode', label: t('filament.barcode'), type: 'text' },
      { key: 'refill', label: t('library.refill'), type: 'checkbox', hint: t('library.refill_hint') },
      { key: 'roll_weight_g', label: t('filament.roll_weight'), type: 'number', required: true },
      { key: 'diameter_mm', label: t('filament.diameter'), type: 'number', required: true, list: ['1.75', '2.85'] },
      { key: 'print_temp_c', label: t('filament.print_temp'), type: 'number', placeholder: t('filament.print_temp_ph'), hint: t('filament.print_temp_hint') },
      { key: 'bed_temp_c', label: t('filament.bed_temp'), type: 'number', placeholder: t('filament.bed_temp_ph'), hint: t('filament.optional') },
      { key: 'price', label: t('library.price'), type: 'number', hint: t('library.price_hint') },
      { key: 'notes', label: t('common.notes'), type: 'textarea' },
    ],
  };
}

// What is left per kind of filament: the rolls you still have (with what is on each) and the total,
// plus a total per material.
function stockPanel() {
  const body = h('div', { class: 'stack' });
  const panel = h('section', { class: 'stack', 'aria-labelledby': 'stock-title', hidden: true },
    h('h2', { id: 'stock-title', class: 'sr-only' }, t('stock.title')), body);
  let data = null;
  let match = () => true;
  const plural = (n) => t('stock.rolls', { n });

  function draw() {
    panel.hidden = !data || !data.groups.length;
    if (panel.hidden) return;
    const groups = data.groups.filter(match);
    if (!groups.length) { body.replaceChildren(h('p', { class: 'muted' }, t('stock.none_match'))); return; }
    const materials = new Map();                     // totals follow the filter, so they always match what is listed
    for (const g of groups) {
      const name = String(g.material || t('stock.unknown_material')).trim();
      const k = name.toLowerCase();                  // "PLA" and "pla" are one material
      const m = materials.get(k) || { name, rolls: 0, grams: 0 };
      m.rolls += g.roll_count;
      m.grams += Number(g.remaining_g);
      materials.set(k, m);
    }
    body.replaceChildren(
      h('p', { class: 'muted stock-materials' }, [...materials.values()].map((m) => `${m.name}: ${plural(m.rolls)}, ${fmt(m.grams, 0)} g`).join(' · ')),
      stockTiles(groups));
  }

  async function refresh() {
    try { data = await api('GET', '/api/spools/stock'); } catch { data = null; }      // a convenience: the list below still works
    draw();
  }
  return { panel, refresh, setFilter(fn) { match = fn; draw(); } };
}

// Filters for the filament list: by material ("soort"), brand and type. Options come from what you have,
// each one narrows to what the earlier choices leave, and both the list and the stock overview follow.
const norm = (v) => String(v || '').trim().toLowerCase();
const FILTERS = [['material', 'filter.material', 'filter.all_materials'], ['brand', 'filter.brand', 'filter.all_brands'], ['product_type', 'filter.type', 'filter.all_types']];

function filterBar(onChange) {
  const state = Object.fromEntries(FILTERS.map(([key]) => [key, '']));
  const selects = Object.fromEntries(FILTERS.map(([key, label]) => [key, h('select', { id: `filter-${key}`, 'aria-label': t('filter.by', { name: t(label).toLowerCase() }) })]));
  let lastItems = [];
  const clear = h('button', { class: 'btn small', type: 'button', hidden: true, onclick: () => {
    for (const [key] of FILTERS) state[key] = '';
    update(lastItems); onChange();
  } }, t('filter.clear'));

  const distinct = (rows, key) => {
    const seen = new Map();
    for (const r of rows) if (norm(r[key]) && !seen.has(norm(r[key]))) seen.set(norm(r[key]), String(r[key]).trim());
    return [...seen].sort((a, b) => a[1].localeCompare(b[1], getLanguage()));
  };
  const matches = (row, upTo = FILTERS.length) => FILTERS.slice(0, upTo).every(([key]) => !state[key] || norm(row[key]) === state[key]);

  function update(items) {
    lastItems = items;
    FILTERS.forEach(([key, , all], i) => {
      const options = distinct(items.filter((row) => matches(row, i)), key);   // narrowed by the filters before this one
      const select = selects[key];
      select.replaceChildren(h('option', { value: '' }, t(all)), ...options.map(([value, label]) => h('option', { value }, label)));
      select.value = options.some(([value]) => value === state[key]) ? state[key] : '';
      state[key] = select.value;
    });
    clear.hidden = !FILTERS.some(([key]) => state[key]);
  }
  for (const [key] of FILTERS) selects[key].addEventListener('change', () => { state[key] = selects[key].value; update(lastItems); onChange(); });

  const bar = h('div', { class: 'filters', role: 'group', 'aria-label': t('filter.group') },
    ...FILTERS.flatMap(([key, label]) => [h('label', { for: `filter-${key}` }, t(label)), selects[key]]), clear);
  return { bar, update, matches: (row) => matches(row), active: () => FILTERS.some(([key]) => state[key]) };
}

function toPayload(config, values) {
  const out = {};
  for (const f of config.fields) {
    out[f.key] = f.type === 'number' ? num(values[f.key]) : (f.type === 'checkbox' ? !!values[f.key] : values[f.key]);
  }
  return out;
}

// Brand, type, material, colour, weight, diameter and temperatures describe the product, so another roll with
// the same barcode should agree. Price, what is left and notes are per roll and never offered.
const PRODUCT_FIELDS = ['brand', 'product_type', 'material', 'colour', 'colour_hex', 'roll_weight_g', 'diameter_mm', 'print_temp_c', 'bed_temp_c'];
const sameValue = (a, b) => {
  const x = String(a ?? '').trim().replace(',', '.'), y = String(b ?? '').trim().replace(',', '.');
  return x === y || (x !== '' && y !== '' && Number.isFinite(Number(x)) && Number(x) === Number(y));
};

/** The product details to copy to the other rolls with this barcode: [] for none, null when the question was closed. */
async function askToPassOn(config, item, payload) {
  if (config.id !== 'filament' || !item.barcode || !sameValue(payload.barcode, item.barcode)) return [];
  const changed = PRODUCT_FIELDS.filter((key) => !sameValue(payload[key], item[key]));
  if (!changed.length) return [];
  const { count } = await api('GET', `${config.path}/${item.id}/siblings`);
  if (!count) return [];
  const names = changed.map((key) => config.fields.find((f) => f.key === key).label.replace(/\s*\(.*\)$/, '')).join(', ');
  const answer = await askChoice(t('propagate.ask', { n: count, fields: names, barcode: item.barcode }), [
    { value: 'all', label: t('propagate.all', { n: count }), primary: true },
    { value: 'one', label: t('propagate.one') }]);
  return answer === null ? null : (answer === 'all' ? changed : []);
}

export function openForm(config, item, reload) {
  if (item) config = { ...config, fields: config.fields.filter((f) => !f.newOnly) };     // an option of making a new one, not of editing
  const values = { ...(item || config.defaults) };
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const els = {};          // inputs by key, so "copy from the previous roll" can fill them
  const datalists = [];

  // A barcode field: type it, use a hardware scanner (it types and presses Enter), or scan with the
  // camera. A known barcode says so, fills in what is known about that filament (never over what was
  // already typed, and only for a new roll) and shows what is in stock of it: confirming is all that is left.
  const CARRIED = ['brand', 'product_type', 'material', 'colour', 'colour_hex', 'roll_weight_g', 'price', 'diameter_mm', 'print_temp_c', 'bed_temp_c', 'notes'];
  const dirty = new Set();          // fields the user typed in themselves
  function stockLine(stock) {
    if (!stock || !stock.roll_count) return t('barcode.none_left');
    const weights = stock.rolls.map((r) => `${fmt(r.remaining_g, 0)} g`).join(', ');
    return t('barcode.in_stock', { n: stock.roll_count, weights, total: fmt(stock.remaining_g, 0) });
  }
  function barcodeField(f) {
    const id = 'f-barcode';
    const notice = h('div', { class: 'notice stack', role: 'status', hidden: true });
    let looked = null;                              // Enter and then leaving the field must not look up (and reflow) twice
    const lookup = async () => {
      const code = (values[f.key] || '').trim();
      if (item || code === looked) return;         // editing: never overwrite the roll being edited
      looked = code;
      if (!code) { notice.hidden = true; return; }
      try {
        const { spool, stock } = await api('GET', `/api/spools/lookup?barcode=${encodeURIComponent(code)}`);
        if (!spool) {
          notice.replaceChildren(h('span', {}, t('barcode.new')));
          notice.hidden = false;
          return;
        }
        for (const key of CARRIED) {
          if (dirty.has(key)) continue;
          values[key] = spool[key] ?? '';
          if (els[key]) { if (els[key].setColour) els[key].setColour(values[key]); else els[key].value = values[key]; }
        }
        if (!dirty.has('notify_low')) {                 // the setting belongs to the kind, so a new roll starts with it
          values.notify_low = !!spool.notify_low;
          if (els.notify_low) els.notify_low.checked = values.notify_low;
        }
        if (!dirty.has('remaining_g')) {
          values.remaining_g = spool.roll_weight_g;     // a new roll starts full
          if (els.remaining_g) els.remaining_g.value = values.remaining_g;
        }
        notice.replaceChildren(
          h('strong', {}, t('barcode.known', { name: spoolName(spool, ' · ') })),
          h('span', {}, t('barcode.filled')),
          h('span', {}, stockLine(stock)));
        notice.hidden = false;
      } catch { /* the lookup is a convenience */ }
    };
    const input = h('input', { type: 'text', id, autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false',
      placeholder: t('barcode.placeholder'), value: values[f.key] ?? '',
      oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); },
      onchange: lookup,
      // Hardware scanners end with Enter: look it up instead of submitting the form half-filled.
      onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); lookup(); } } });
    els[f.key] = input;
    const scan = h('button', { class: 'btn', type: 'button', onclick: async () => {
      const code = await scanBarcode();
      if (code) { input.value = code; values[f.key] = code; lookup(); }
    } }, icon('scan'), h('span', {}, 'Scan'));
    return h('div', { class: 'field' }, h('label', { for: id }, f.label),
      h('div', { class: 'row nowrap' }, input, scan), f.hint ? h('p', { class: 'hint' }, f.hint) : null, notice);
  }

  // The colour of a roll as a colour: picked here, or (while nothing is picked) taken from the colour's name.
  function colourField(f) {
    const id = `f-${f.key}`;
    const guess = () => colourOf({ colour: values.colour }) || '#808080';
    const note = h('span', { class: 'muted' });
    const input = h('input', { type: 'color', id, value: values[f.key] || guess(),
      oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); show(); } });
    const show = () => { note.textContent = values[f.key] ? values[f.key] : t('filament.colour_auto'); auto.hidden = !values[f.key]; };
    const auto = h('button', { class: 'btn small', type: 'button', onclick: () => { values[f.key] = ''; dirty.add(f.key); input.value = guess(); show(); } }, t('filament.colour_reset'));
    input.setColour = (hex) => { values[f.key] = hex || ''; input.value = hex || guess(); show(); };
    els[f.key] = input;
    show();
    return h('div', { class: 'field' }, h('label', { for: id }, f.label), h('div', { class: 'row colour-row' }, input, note, auto),
      f.hint ? h('p', { class: 'hint' }, f.hint) : null);
  }

  // A new roll can start from the filament library: one pick fills in everything the library knows about that filament.
  const FROM_LIBRARY = ['brand', 'product_type', 'material', 'colour', 'colour_hex', 'roll_weight_g', 'diameter_mm', 'print_temp_c', 'bed_temp_c', 'barcode', 'price'];
  function libraryPicker() {
    const select = h('select', { id: 'f-library', 'aria-describedby': 'f-library-hint' });
    const box = h('div', { class: 'field', hidden: true }, h('label', { for: 'f-library' }, t('library.pick')), select,
      h('p', { class: 'hint', id: 'f-library-hint' }, t('library.pick_hint')));
    let entries = [];
    const put = (key, value) => {
      values[key] = value;
      dirty.add(key);
      if (!els[key]) return;
      if (els[key].setColour) els[key].setColour(value); else els[key].value = value;
    };
    select.addEventListener('change', () => {
      const entry = entries.find((e) => e.id === select.value);
      if (!entry) return;
      for (const key of FROM_LIBRARY) {
        const value = entry[key] ?? '';
        if (key === 'price' && value === '') continue;            // an entry without a price leaves the price as it is
        put(key, value);
      }
      put('remaining_g', entry.roll_weight_g);                     // a new roll starts full
    });
    api('GET', '/api/filament-library').then((rows) => {
      entries = rows;
      if (!rows.length) return;
      const groups = new Map();
      for (const e of rows) {
        const name = [e.brand, e.material].filter(Boolean).join(' · ');
        if (!groups.has(name)) groups.set(name, h('optgroup', { label: name }));
        groups.get(name).append(h('option', { value: e.id },
          [e.product_type, e.filament_id ? `${e.colour} (${e.filament_id})` : e.colour, e.refill ? t('library.refill_short') : ''].filter(Boolean).join(' · ') || e.brand));
      }
      select.append(h('option', { value: '' }, t('library.pick_none')), ...groups.values());
      box.hidden = false;
    }).catch(() => { /* the library is a convenience: the form works without it */ });
    return box;
  }

  const inputs = config.fields.map((f) => {
    if (f.type === 'barcode') return barcodeField(f);
    if (f.type === 'color') return colourField(f);
    if (f.type === 'checkbox') {
      const box = h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: !!values[f.key],
        onchange: (e) => { values[f.key] = e.target.checked; dirty.add(f.key); } });
      els[f.key] = box;
      return h('div', { class: 'field' }, h('label', { class: 'check' }, box, f.label), f.hint ? h('p', { class: 'hint' }, f.hint) : null);
    }
    if (f.type === 'select') {
      const select = h('select', { onchange: (e) => { values[f.key] = e.target.value; dirty.add(f.key); } },
        f.options.map(([value, label]) => h('option', { value, selected: value === values[f.key] }, label)));
      els[f.key] = select;
      return field(f.label, select, f.hint);
    }
    let listId = null;
    if (f.list) {
      listId = `dl-${f.key}`;
      datalists.push(h('datalist', { id: listId }, f.list.map((v) => h('option', { value: v }))));
    }
    const input = f.type === 'textarea'
      ? h('textarea', { rows: 3, oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); } }, values[f.key] ?? '')
      : h('input', { type: 'text', inputmode: f.type === 'number' ? 'decimal' : 'text', autocomplete: 'off',
        required: f.required, placeholder: f.placeholder, value: values[f.key] ?? '', list: listId,
        oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); } });
    els[f.key] = input;
    return field(f.label, input, f.hint);
  });
  const original = item || config.defaults;
  const changed = () => [...dirty].some((key) => String(values[key] ?? '') !== String(original[key] ?? ''));
  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
    h('form', { class: 'stack', method: 'dialog', onsubmit: async (e) => {
      e.preventDefault();
      try {
        const payload = toPayload(config, values);
        let passOn = [];
        if (item) {
          passOn = await askToPassOn(config, item, payload);
          if (passOn === null) return;                                     // closed the question: back to the form
          await api('PATCH', `${config.path}/${item.id}`, payload);
        } else await api('POST', config.path, payload);
        let others = 0;
        if (passOn.length) others = (await api('POST', `${config.path}/${item.id}/propagate`, { fields: passOn })).updated;
        dialog.close();
        toast(others ? t('propagate.done', { n: others }) : t('common.saved'));
        reload();
      } catch (err) { error.textContent = err.message; error.hidden = false; }
    } },
    h('h2', {}, item ? t(`${config.id}.edit`) : t(`${config.id}.new`)),
    config.id === 'filament' && !item ? libraryPicker() : null,
    ...inputs, ...datalists, error,
    h('div', { class: 'row end' },
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
      h('button', { class: 'btn primary', type: 'submit' }, t('common.save'))))), { dirty: changed });
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

// How the rolls can be ordered: [key, label key, sort value]. Tapping the active one reverses it.
const SORTS = [['name', 'sort.name'], ['material', 'sort.material'], ['left', 'sort.left'], ['per_kg', 'sort.per_kg'], ['newest', 'sort.newest']];
const sortValue = {
  name: (r) => spoolName(r, ' ').toLowerCase(),
  material: (r) => `${norm(r.material) || '~'} ${spoolName(r, ' ').toLowerCase()}`,
  left: (r) => Number(r.remaining_g),
  per_kg: (r) => Number(r.price) / Number(r.roll_weight_g),
  newest: (r) => String(r.created_at || ''),
};
let rollSort = { by: 'name', dir: 1 };                         // kept while switching between the two parts of the filament page

export function resourceView(key, sub) {
  const config = resources()[key];
  const part = key === 'filament' ? (sub === 'rollen' ? 'rollen' : 'voorraad') : null;
  const list = h('div', { class: 'cards' });
  let showArchived = false;
  let items = [];

  const render = () => {
    const visible = items.filter((i) => (showArchived || !i.archived) && (!filters || filters.matches(i)));
    if (!visible.length) {
      list.replaceChildren(h('p', { class: 'empty glass card' },
        filters?.active() && items.length ? t('filament.no_match') : `${config.empty} ${t('common.add_first')}`));
      return;
    }
    if (part === 'rollen') {
      const value = sortValue[rollSort.by];
      visible.sort((a, b) => {
        const x = value(a), y = value(b);
        const order = typeof x === 'string' ? x.localeCompare(y, getLanguage(), { numeric: true }) : x - y;
        return order * rollSort.dir || spoolName(a).localeCompare(spoolName(b), getLanguage());
      });
    }
    list.replaceChildren(...visible.map((item) => {
      const c = config.card(item);
      const extraActions = config.actions ? config.actions.call(config, item, load) : [];
      return h('article', { class: `glass card item${item.archived ? ' archived' : ''}` },
        h('div', { class: 'item-head' },
          c.icon || null,
          h('div', { class: 'grow' }, h('h3', {}, c.title, c.badge ? h('span', { class: 'badge' }, c.badge) : null,
            item.archived ? h('span', { class: 'badge muted' }, t('common.archived')) : null),
          c.subtitle ? h('p', { class: 'muted' }, c.subtitle) : null)),
        h('dl', { class: 'stats' }, c.stats.map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v)))),
        c.extra || null,
        c.footnote ? h('p', { class: 'muted footnote' }, c.footnote) : null,
        h('div', { class: 'row' },
          h('button', { class: 'btn small', type: 'button', onclick: () => openForm(config, item, load) }, t('common.edit')),
          ...extraActions,
          config.archivable ? h('button', { class: 'btn small', type: 'button', onclick: async () => {
            await api('PATCH', `${config.path}/${item.id}`, { archived: !item.archived });
            load();
          } }, item.archived ? t('common.restore') : t('common.archive')) : null,
          h('button', { class: 'btn small danger', type: 'button', 'aria-label': t('common.delete_named', { name: c.title }),
            onclick: async () => {
              if (await confirmDialog(t('common.delete_confirm', { name: c.title }))) {
                await api('DELETE', `${config.path}/${item.id}`);
                load();
              }
            } }, icon('trash'))));
    }));
  };

  const stock = part === 'voorraad' ? stockPanel() : null;
  const filters = key === 'filament' ? filterBar(() => {
    render();
    stock?.setFilter((g) => filters.matches(g));       // stock groups carry brand and material too
  }) : null;

  // The sort buttons at the top of the rolls: tap one to order by it, tap it again to reverse.
  const sortBar = part === 'rollen' ? h('div', { class: 'sortbar', role: 'group', 'aria-label': t('sort.label') }) : null;
  function drawSort() {
    sortBar.replaceChildren(h('span', { class: 'muted' }, t('sort.label')), ...SORTS.map(([by, label]) => {
      const active = rollSort.by === by;
      return h('button', { class: 'seg', type: 'button', 'aria-pressed': String(active),
        'aria-label': active ? `${t(label)}, ${t(rollSort.dir > 0 ? 'sort.asc' : 'sort.desc')}` : t(label),
        onclick: () => { rollSort = active ? { by, dir: -rollSort.dir } : { by, dir: by === 'newest' || by === 'left' ? -1 : 1 }; drawSort(); render(); } },
      t(label), active ? h('span', { 'aria-hidden': 'true' }, rollSort.dir > 0 ? ' ↑' : ' ↓') : null);
    }));
  }
  if (sortBar) drawSort();

  async function load() {
    try {
      items = await api('GET', config.path);
      filters?.update(items.filter((i) => showArchived || !i.archived));
      render();
      stock?.refresh();
    } catch (e) { toast(e.message, 'error'); }
  }

  const archiveToggle = config.archivable
    ? h('label', { class: 'check' },
      h('input', { type: 'checkbox', class: 'toggle', role: 'switch', onchange: (e) => { showArchived = e.target.checked; filters?.update(items.filter((i) => showArchived || !i.archived)); render(); } }),
      t('common.show_archived'))
    : null;

  load();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, config.title)),
      h('button', { class: 'btn primary', type: 'button', onclick: () => openForm(config, null, load) },
        icon('plus'), h('span', {}, t(`${config.id}.new`)))),
    h('p', { class: 'muted page-intro' }, config.intro),
    key === 'filament' ? h('nav', { class: 'subnav', 'aria-label': t('filament.parts') },
      ...[['voorraad', 'filament.part_stock'], ['rollen', 'filament.part_rolls']].map(([to, label]) => h('a', { href: `#/filament/${to}`, 'aria-current': part === to ? 'page' : null }, t(label)))) : null,
    key === 'onderdelen' || key === 'accessoires' ? h('nav', { class: 'subnav', 'aria-label': t('parts.tabs') },
      ...[['onderdelen', 'parts.title'], ['accessoires', 'accessories.title']].map(([to, label]) => h('a', { href: `#/onderdelen${to === 'accessoires' ? '/accessoires' : ''}`, 'aria-current': key === to ? 'page' : null }, t(label)))) : null,
    sortBar, filters ? h('details', { class: 'filters-details', open: filters.active() }, h('summary', {}, t('filter.title')), filters.bar) : null, stock?.panel || null, part === 'rollen' || !part ? archiveToggle : null, part === 'voorraad' ? null : list);
}
