import { api, upload } from './api.js';
import { getLanguage, t } from './i18n.js';
import { colourOf, spoolIcon, stockTile } from './filament-ui.js';
import { openBulkScan } from './bulk-scan.js';
import { listView, rowActions } from './listview.js';
import { scanBarcode } from './scanner.js';
import { livePanel, serialField } from './haspelsync.js';
import { spoolmanBar } from './spoolman.js';
import { colourLabel, filledText, rowFor, spoolmanDbCatalogue } from './spoolmandb.js';
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
    search: (item) => [item.name, item.notes],
    sorts: [byName(), { key: 'price', label: t('sort.price'), value: (item) => Number(item.price) }, { key: 'unit', label: text.unit, value: (item) => unitName(item.unit) }],
    columns: [nameColumn(),
      { label: text.unit, sort: 'unit', cell: (item) => unitName(item.unit) },
      { label: text.price, sort: 'price', cls: 'num strong', cell: (item) => eur(item.price) }],
  };
}

// What every list of things with a name shares: the order by name, and the first column (the name, with the notes under it).
const unitName = (unit) => t((UNIT_OPTIONS.find(([value]) => value === unit) || UNIT_OPTIONS[0])[1]);
const byName = () => ({ key: 'name', label: t('sort.name'), value: (item) => item.name });
const nameColumn = (badge = () => null, lead = () => null) => ({ label: t('common.name'), sort: 'name', cls: 'main', cell: (item) => h('div', { class: 'cell-main' }, lead(item),
  h('div', {}, h('span', { class: 'cell-title' }, item.name, badge(item), item.archived ? h('span', { class: 'badge muted' }, t('common.archived')) : null),
    item.notes ? h('div', { class: 'cell-sub muted' }, item.notes) : null)) });
/** The picture of an item, small; an item without one gets a quiet placeholder, so a list of both stays aligned. The address carries the
    version of the picture, so a new one is shown at once. */
const imageUrl = (path, item) => `${path}/${item.id}?v=${item.image_version}`;
const thumb = (path, item) => (item.image_version ? h('img', { class: 'item-thumb', src: imageUrl(path, item), alt: '', loading: 'lazy' })
  : h('span', { class: 'item-thumb placeholder', 'aria-hidden': 'true' }, icon('box')));
const perKg = (roll) => Number(roll.price) / Number(roll.roll_weight_g) * 1000;
/** How full a roll is, as a bar. */
function meter(roll) {
  const bar = h('div', { class: 'meter', role: 'img', 'aria-label': t('filament.meter', { left: fmt(roll.remaining_g, 0), total: fmt(roll.roll_weight_g, 0) }) }, h('span'));
  bar.firstChild.style.width = `${Math.max(0, Math.min(100, Number(roll.remaining_g) / Number(roll.roll_weight_g) * 100))}%`;
  return bar;
}
// One kind of filament, as the server groups the stock (`stock.key_of`): the barcode when there is one, else brand, type, material and colour.
const kindOf = (roll) => (String(roll.barcode || '').trim() ? `barcode:${String(roll.barcode).trim()}`
  : `name:${['brand', 'product_type', 'material', 'colour'].map((key) => norm(roll[key])).join('|')}`);
// The filters of both parts of the filament page: by material, brand and type, each narrowing what the next one offers.
const filamentFilters = () => [
  { key: 'material', label: t('filter.material'), all: t('filter.all_materials'), value: (row) => row.material },
  { key: 'brand', label: t('filter.brand'), all: t('filter.all_brands'), value: (row) => row.brand },
  { key: 'product_type', label: t('filter.type'), all: t('filter.all_types'), value: (row) => row.product_type }];
const filamentText = (row) => [row.brand, row.product_type, row.colour, row.material, row.barcode];

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
      { key: 'brand', label: t('filament.brand'), type: 'brand', required: true },
      // Not a field of this form any more (SpoolmanDB and Spoolman put the product line in the name of the colour), but it stays here: `toPayload` sends what the form
      // holds, so a type that comes with a library entry or a known roll goes with the new roll, and editing a roll never clears the one it has. The library form keeps it.
      { key: 'product_type', label: t('filament.type'), type: 'text', hidden: true },
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
      return {
        icon: spoolIcon(colourOf(item), 34),
        title: spoolName(item, ' · '), badge: item.spoolman_id ? t('spoolman.badge') : null,
        subtitle: [item.material, t('filament.per_roll_price', { price: eur(item.price) })].filter(Boolean).join(' · '),
        stats: [[t('filament.per_kg'), eur(perKg(item))], [t('filament.left'), `${fmt(item.remaining_g, 0)} g`], [t('filament.diameter_short'), `${fmt(item.diameter_mm)} mm`],
          ...(item.print_temp_c != null ? [[t('filament.print_temp_short'), `${item.print_temp_c} °C`]] : []),
          ...(item.bed_temp_c != null ? [[t('filament.bed_temp_short'), `${item.bed_temp_c} °C`]] : [])],
        extra: meter(item),
        footnote: [item.barcode ? t('filament.barcode_note', { code: item.barcode }) : null, item.spoolman_id ? t('spoolman.note') : null].filter(Boolean).join(' · ') || null,
      };
    },
    name: (item) => spoolName(item, ' · '),
    search: filamentText,
    filters: filamentFilters(),
    // Tapping the active order reverses it. Equal rolls are in the order of their name.
    sorts: [
      { key: 'name', label: t('sort.name'), value: (r) => spoolName(r, ' ') },
      { key: 'material', label: t('sort.material'), value: (r) => norm(r.material) || '~' },
      { key: 'left', label: t('sort.left'), value: (r) => Number(r.remaining_g) },
      { key: 'per_kg', label: t('sort.per_kg'), value: (r) => perKg(r) },
      { key: 'newest', label: t('sort.newest'), value: (r) => String(r.created_at || ''), desc: true }],
    // The rolls of one kind together (three rolls of Bambu Lab Basic red, told apart from another red by the barcode). Inside a group the rolls keep the
    // chosen order, and the groups are in the order of their first roll: sorted on what is left, the kind with the emptiest roll comes first.
    group: { label: t('filament.group'), key: kindOf, head: (rolls) => ({
      icon: spoolIcon(colourOf(rolls[0]), 26), title: [spoolName(rolls[0], ' · '), rolls[0].material].filter(Boolean).join(' · '),
      meta: [t('filament.group_left', { grams: fmt(rolls.reduce((sum, r) => sum + Number(r.remaining_g), 0), 0) }),
        rolls[0].barcode ? t('filament.barcode_note', { code: rolls[0].barcode }) : null].filter(Boolean).join(' · ') }) },
    columns: [
      { label: t('filament.roll'), sort: 'name', cls: 'main', cell: (item) => h('div', { class: 'cell-main' }, spoolIcon(colourOf(item), 28),
        h('div', {}, h('span', { class: 'cell-title' }, spoolName(item, ' · '), item.spoolman_id ? h('span', { class: 'badge' }, t('spoolman.badge')) : null,
          item.archived ? h('span', { class: 'badge muted' }, t('common.archived')) : null),
        item.notes ? h('div', { class: 'cell-sub muted' }, item.notes) : null)) },
      { label: t('sort.material'), sort: 'material', cell: (item) => item.material || '—' },
      { label: t('sort.left'), sort: 'left', cls: 'meter-cell', cell: (item) => h('div', { class: 'cell-meter' }, h('span', { class: 'num' }, `${fmt(item.remaining_g, 0)} g`), meter(item)) },
      { label: t('sort.per_kg'), sort: 'per_kg', cls: 'num', cell: (item) => eur(perKg(item)) },
      { label: t('filament.roll_price'), cls: 'num', wide: true, cell: (item) => eur(item.price) },
      { label: t('filament.barcode'), cls: 'nowrap', wide: true, cell: (item) => item.barcode || '—' }],
    // A roll typed in here can be duplicated: the roll form, filled in with this roll, makes one or more new ones.
    // A roll from Spoolman is Spoolman's to change (the server refuses it), and a new one is made there: all that is left here is the low-stock alert.
    actions(item, reload) {
      if (!item.spoolman_id) {
        return [{ icon: 'copy', label: t('filament.duplicate_named', { name: spoolName(item, ' · ') }), onclick: () => openForm(this, null, reload, { copyOf: item }) }];
      }
      return [{ icon: 'bell', label: item.notify_low ? t('spoolman.notify_off') : t('spoolman.notify_on'), pressed: !!item.notify_low, onclick: async () => {
        try { await api('PATCH', `${this.path}/${item.id}`, { notify_low: !item.notify_low }); reload(); } catch (e) { toast(e.message, 'error'); }
      } }];
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
    // An item can have a picture (a photo of the box or bag, or its logo): shown in the tile and the list, chosen in the form.
    image: '/api/packaging-images',
    card(item) {
      return { icon: thumb(this.image, item), title: item.name, subtitle: item.notes || null, stats: [[t('packaging.per_piece'), eur(item.price)]] };
    },
    search: (item) => [item.name, item.notes],
    sorts: [byName(), { key: 'price', label: t('sort.price'), value: (item) => Number(item.price) }],
    columns: [nameColumn(() => null, (item) => thumb('/api/packaging-images', item)), { label: t('packaging.per_piece'), sort: 'price', cls: 'num strong', cell: (item) => eur(item.price) }],
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
    defaults: { name: '', purchase_price: '', lifetime_hours: '3000', power_kw: '0.15', notes: '', haspelsync_serial: '' },
    fields: [
      { key: 'name', label: t('common.name'), type: 'text', required: true, placeholder: t('printers.name_ph') },
      { key: 'purchase_price', label: t('printers.purchase_price'), type: 'number', required: true },
      { key: 'lifetime_hours', label: t('printers.lifetime'), type: 'number', required: true },
      { key: 'power_kw', label: t('printers.power'), type: 'number', hint: t('printers.power_hint') },
      { key: 'haspelsync_serial', label: t('haspelsync.field'), type: 'haspelsync', hint: t('haspelsync.field_hint') },
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
    search: (item) => [item.name, item.notes],
    sorts: [byName(), { key: 'price', label: t('printers.purchase_price'), value: (item) => Number(item.purchase_price) },
      { key: 'per_hour', label: t('printers.depreciation'), value: (item) => Number(item.purchase_price) / Number(item.lifetime_hours) }],
    columns: [nameColumn(),
      { label: t('printers.purchase_price'), sort: 'price', cls: 'num', cell: (item) => eur(item.purchase_price) },
      { label: t('printers.lifetime'), cls: 'num', wide: true, cell: (item) => fmt(item.lifetime_hours, 0) },
      { label: t('printers.depreciation'), sort: 'per_hour', cls: 'num strong', cell: (item) => t('printers.per_hour', { price: eur(Number(item.purchase_price) / Number(item.lifetime_hours)) }) },
      { label: t('printers.power_short'), cls: 'num', wide: true, cell: (item) => `${fmt(item.power_kw, 3)} kW` }],
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
    search: (item) => [item.name],
    sorts: [byName(), { key: 'price', label: t('energy.price_short'), value: (item) => Number(item.price_per_kwh) }],
    columns: [nameColumn((item) => (item.is_default ? h('span', { class: 'badge' }, t('energy.default')) : null)),
      { label: t('energy.price_short'), sort: 'price', cls: 'num strong', cell: (item) => t('energy.per_kwh', { price: eur(item.price_per_kwh) }) }],
    actions(item, reload) {
      if (item.is_default) return [];
      return [{ icon: 'star', label: t('energy.make_default'), onclick: async () => {
        await api('PATCH', `${this.path}/${item.id}`, { is_default: true });
        reload();
      } }];
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

const norm = (v) => String(v || '').trim().toLowerCase();

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

/** The form of `config`: editing `item`, or a new one. `copyOf` (a roll) makes it a new roll with that roll's details, which starts full
    (what is left is per roll), and asks how many: they are all added at once. */
export function openForm(config, item, reload, { copyOf = null } = {}) {
  if (item || copyOf) config = { ...config, fields: config.fields.filter((f) => !f.newOnly) };     // an option of making a new one from scratch, not of editing or copying
  const copied = copyOf ? { ...Object.fromEntries(config.fields.map((f) => [f.key, copyOf[f.key] ?? ''])), remaining_g: copyOf.roll_weight_g, count: '1' } : null;
  const values = { ...(item || copied || config.defaults) };
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const els = {};          // inputs by key, so "copy from the previous roll" can fill them
  const datalists = [];

  // A barcode field: type it, use a hardware scanner (it types and presses Enter), or scan with the
  // camera. A known barcode says so, fills in what is known about that filament (never over what was
  // already typed, and only for a new roll) and shows what is in stock of it: confirming is all that is left.
  const CARRIED = ['brand', 'product_type', 'material', 'colour', 'colour_hex', 'roll_weight_g', 'price', 'diameter_mm', 'print_temp_c', 'bed_temp_c', 'notes', 'spoolmandb_id'];
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
          if (els[key]) { if (els[key].setValue) els[key].setValue(values[key]); else els[key].value = values[key]; }
        }
        suggest();
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
    input.lookup = lookup;                                           // the Bambu Lab pick fills the barcode and then looks the roll up too
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
    input.setValue = (hex) => { values[f.key] = hex || ''; input.value = hex || guess(); show(); };
    els[f.key] = input;
    show();
    return h('div', { class: 'field' }, h('label', { for: id }, f.label), h('div', { class: 'row colour-row' }, input, note, auto),
      f.hint ? h('p', { class: 'hint' }, f.hint) : null);
  }

  // Fill a field from outside (the library, the Bambu Lab shop): its value, the widget, and a mark that it is no longer to be overwritten.
  const put = (key, value) => {
    values[key] = value;
    dirty.add(key);
    if (!els[key]) return;
    if (els[key].setValue) els[key].setValue(value); else els[key].value = value;
  };
  const fresh = config.id === 'filament' && !item && !copyOf;          // a roll from scratch: the library and the Bambu Lab shop can fill it in
  const libraryRows = fresh ? api('GET', '/api/filament-library').catch(() => []) : Promise.resolve([]);   // a convenience: the form works without it
  const fromShop = { filament_id: '', refill: null };          // what the library knows about the filament that a roll does not hold (its supplier's filament ID, refill or spool)

  // The SpoolmanDB filament the form was filled from (picked here, or a library entry that came from there) and what the form said then. The id is
  // the reference to the source and goes to Spoolman with the roll: when brand, material, colour, weight or diameter are changed afterwards it is
  // another filament, and the reference is dropped rather than left pointing at the wrong one.
  const IDENTITY = ['brand', 'material', 'colour', 'roll_weight_g', 'diameter_mm'];
  const identity = () => IDENTITY.map((key) => norm(String(values[key] ?? '').replace(',', '.'))).join('|');
  let from = null;
  const sourceId = () => (from ? (from.identity === identity() ? from.id : '') : String(values.spoolmandb_id || ''));

  // SpoolmanDB feeds the fields of a new roll's form (`spoolmandb.js`), not a block next to them: its brands join the brand pull-down, the material pull-down offers the
  // materials of the brand, the colour pull-down the colours of the brand and material, and choosing a colour fills in the rest. Each has "Other…" to type something
  // that is not in the list. A filament that is already here keeps its own spelling (the server's `fill`), the id of the SpoolmanDB filament is kept as the reference
  // to the source, and without a list the form is as it always was.
  const catalogue = fresh ? spoolmanDbCatalogue() : null;
  const OTHER = '__other__';                                                   // "Other material / colour…": the pull-down hands over to a text field
  const COMMON_MATERIALS = ['PLA', 'PETG', 'ABS', 'ASA', 'TPU', 'PA', 'PC'];    // when there is no list at all
  const note = h('p', { class: 'hint', hidden: true });                         // the source, under the brand field
  const status = h('p', { class: 'hint', role: 'status', hidden: true });       // what choosing a colour did, or how to get the colours, under the colour field
  let smdbBrands = [];                                                         // [{ name, materials }] of the list in use; empty without one
  let ownRows = [];                                                            // the rolls and library entries here: their materials are offered too
  let smdbRows = [];                                                           // the filaments of the brand and material in the form
  let pickedRow = null;                                                        // the row the form was last filled from: it stays the chosen one when another variant has the same name
  let lastBrand = null;                                                        // what the pull-downs were last made for, so that filling in a roll does not make them again
  let lastMaterial = null;
  let askedFor = 0;                                                            // a slow answer for a brand that was changed again is not used
  const ui = {};                                                               // `ui.material.draw()` and `ui.colour.draw()`, set by the two fields
  const unique = (list) => {
    const out = new Map();
    for (const m of list) { const v = String(m || '').trim(); if (v && !out.has(norm(v))) out.set(norm(v), v); }
    return [...out.values()];
  };
  // The materials to offer for the brand in the form: its own (the list's, and the ones used here), else every material there is, the common ones first.
  function materialChoices() {
    const brand = norm(values.brand);
    const known = smdbBrands.find((b) => norm(b.name) === brand);
    const mine = unique([...(known ? known.materials : []), ...ownRows.filter((r) => norm(r.brand) === brand).map((r) => r.material)]);
    if (mine.length) return mine.sort((a, b) => a.localeCompare(b, getLanguage()));
    const seen = new Map();
    for (const b of smdbBrands) for (const m of b.materials) seen.set(m, (seen.get(m) || 0) + 1);
    const common = [...seen.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([m]) => m);
    return unique([...(common.length ? common : COMMON_MATERIALS), ...ownRows.map((r) => r.material)]);
  }
  async function suggest(force = false) {                                      // the brand or the material changed (or what is known about them): the pull-downs follow
    if (!catalogue) return;
    const brand = norm(values.brand);
    const known = smdbBrands.find((b) => norm(b.name) === brand);
    const material = known?.materials.find((m) => norm(m) === norm(values.material));
    const brandChanged = force || brand !== lastBrand;
    if (!brandChanged && norm(material) === lastMaterial) return;
    lastBrand = brand;
    lastMaterial = norm(material);
    if (brandChanged) ui.material?.draw();
    const mine = ++askedFor;
    const rows = known && material ? await catalogue.filaments(known.name, material) : [];
    if (mine !== askedFor) return;
    smdbRows = rows;
    ui.colour?.draw();
    status.textContent = known && !material ? t('spoolmandb.colour_hint') : '';
    status.hidden = !status.textContent;
  }
  // A colour of the list: the rest of the roll is filled in from it, with the weight and diameter of that very row.
  function adopt(row) {
    pickedRow = row;
    for (const [key, value] of Object.entries(row.fill)) if (key !== 'spoolmandb_id') put(key, value == null ? '' : String(value));
    put('remaining_g', String(row.fill.roll_weight_g));            // a new roll starts full
    values.spoolmandb_id = row.fill.spoolmandb_id;
    from = { id: row.fill.spoolmandb_id, identity: identity() };
    status.textContent = filledText(row);
    status.hidden = false;
  }
  // The material: a pull-down like the brand's, with "Other material…" for one that is not in it.
  function materialField(f) {
    const select = h('select', { id: 'f-material' });
    const typed = h('input', { type: 'text', autocomplete: 'off', placeholder: t('filament.material_ph'), 'aria-label': t('material.other'), hidden: true,
      oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); suggest(); } });
    function draw() {                                                          // the options for the brand in the form; what the form says now stays chosen
      const list = materialChoices();
      const current = String(values[f.key] ?? '').trim();
      const chosen = list.find((m) => norm(m) === norm(current));
      select.replaceChildren(h('option', { value: '' }, t('material.pick')), ...list.map((m) => h('option', { value: m }, m)), h('option', { value: OTHER }, t('material.other')));
      select.value = chosen || (current ? OTHER : '');
      typed.hidden = !(current && !chosen);
      if (!typed.hidden) typed.value = current;
    }
    select.addEventListener('change', () => {
      dirty.add(f.key);
      typed.hidden = select.value !== OTHER;
      values[f.key] = select.value === OTHER ? typed.value : select.value;
      if (select.value === OTHER) typed.focus();
      suggest();
    });
    select.setValue = () => { draw(); suggest(); };                            // `put` has set the value already
    ui.material = { draw };
    els[f.key] = select;
    draw();
    return h('div', { class: 'field' }, h('label', { for: 'f-material' }, f.label), select, typed);
  }
  // The colour: a pull-down of the colours of the brand and material (one row per weight and diameter) once there are any, else the text field it always was.
  function colourPick(f) {
    const label = h('label', { for: 'f-colour' }, f.label);
    const select = h('select', { id: 'f-colour', hidden: true });
    const typed = h('input', { type: 'text', id: 'f-colour-text', autocomplete: 'off', placeholder: f.placeholder, value: values[f.key] ?? '',
      oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); },
      onchange: () => { const row = rowFor(smdbRows, values[f.key], values.roll_weight_g, values.diameter_mm); if (row) adopt(row); } });
    function draw() {
      const rows = smdbRows;
      select.hidden = !rows.length;
      label.setAttribute('for', rows.length ? 'f-colour' : 'f-colour-text');
      if (!rows.length) { typed.hidden = false; return; }
      const current = String(values[f.key] ?? '').trim();
      const chosen = pickedRow && rows.includes(pickedRow) && norm(pickedRow.fill.colour) === norm(current) ? pickedRow : rowFor(rows, current, values.roll_weight_g, values.diameter_mm);
      select.replaceChildren(h('option', { value: '' }, t('colour.pick')), ...rows.map((row) => h('option', { value: row.id }, colourLabel(row))), h('option', { value: OTHER }, t('colour.other')));
      select.value = chosen ? chosen.id : (current ? OTHER : '');
      typed.hidden = !(current && !chosen);
      if (!typed.hidden) typed.value = current;
    }
    select.addEventListener('change', () => {
      dirty.add(f.key);
      if (select.value === OTHER) { typed.hidden = false; values[f.key] = typed.value; typed.focus(); return; }
      typed.hidden = true;
      const row = smdbRows.find((r) => r.id === select.value);
      if (row) adopt(row); else values[f.key] = '';
    });
    select.setValue = (value) => { typed.value = value; draw(); };            // `put` has set the value already
    ui.colour = { draw };
    els[f.key] = select;
    draw();
    return h('div', { class: 'field' }, label, select, typed, status);
  }

  // The brand: a pull-down of the brands there are (on rolls and in the library, and the SpoolmanDB list's), and "New brand..." for one that is not there yet.
  function brandField(f) {
    const id = 'f-brand';
    const NEW = '__new__';
    const select = h('select', { id, required: true });
    const typed = h('input', { type: 'text', autocomplete: 'off', placeholder: t('brand.new_ph'), 'aria-label': t('brand.new'), hidden: true,
      oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); suggest(); } });
    const option = (name) => h('option', { value: name }, name);
    const ensure = (name) => {                                      // the option of this brand (any case), added when there is none
      const found = [...select.options].find((o) => o.value !== NEW && norm(o.value) === norm(name));
      if (found) return found;
      const added = option(name);
      select.insertBefore(added, select.querySelector(`option[value="${NEW}"]`));
      return added;
    };
    select.append(h('option', { value: '' }, t('brand.pick')), h('option', { value: NEW }, t('brand.new')));
    if (values[f.key]) ensure(values[f.key]);
    select.value = values[f.key] ? ensure(values[f.key]).value : '';
    Promise.all([api('GET', '/api/spools').catch(() => []), libraryRows, catalogue ? catalogue.overview() : null]).then(([rolls, entries, overview]) => {
      ownRows = [...rolls, ...entries];
      if (overview) {                                                // the list in use: its brands are offered, and its source is named
        smdbBrands = overview.brands;
        const s = overview.source;
        note.replaceChildren(t('spoolmandb.source', { licence: s.licence, copyright: s.copyright, date: s.fetched }), ' ',
          h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, t('spoolmandb.link')));
        note.hidden = false;
      }
      const names = new Map([['bambu lab', 'Bambu Lab']]);
      for (const name of [...ownRows.map((r) => r.brand), ...smdbBrands.map((b) => b.name)]) if (norm(name) && !names.has(norm(name))) names.set(norm(name), String(name).trim());
      const keep = select.value;
      for (const name of [...names.values()].sort((a, b) => a.localeCompare(b, getLanguage()))) ensure(name);
      select.value = keep;
      suggest(true);
    });
    select.addEventListener('change', () => {
      dirty.add(f.key);
      typed.hidden = select.value !== NEW;
      values[f.key] = select.value === NEW ? typed.value : select.value;
      if (select.value === NEW) typed.focus();
      suggest();
    });
    select.setValue = (name) => { select.value = name ? ensure(name).value : ''; typed.hidden = true; suggest(); };
    els[f.key] = select;                                             // so `put` (a pick from the library, a barcode or SpoolmanDB) shows the brand it fills in: without it the pull-down stayed on "Kies een merk" and its `required` blocked saving
    return h('div', { class: 'field' }, h('label', { for: id }, f.label), select, typed, note);
  }

  // A new roll can start from the filament library: one pick fills in everything the library knows about that filament.
  const FROM_LIBRARY = ['brand', 'product_type', 'material', 'colour', 'colour_hex', 'roll_weight_g', 'diameter_mm', 'print_temp_c', 'bed_temp_c', 'barcode', 'price'];
  function libraryPicker() {
    const select = h('select', { id: 'f-library', 'aria-describedby': 'f-library-hint' });
    const box = h('div', { class: 'field', hidden: true }, h('label', { for: 'f-library' }, t('library.pick')), select,
      h('p', { class: 'hint', id: 'f-library-hint' }, t('library.pick_hint')));
    let entries = [];
    select.addEventListener('change', () => {
      const entry = entries.find((e) => e.id === select.value);
      if (!entry) return;
      for (const key of FROM_LIBRARY) {
        const value = entry[key] ?? '';
        if (key === 'price' && value === '') continue;            // an entry without a price leaves the price as it is
        put(key, value);
      }
      put('remaining_g', entry.roll_weight_g);                     // a new roll starts full
      fromShop.filament_id = entry.filament_id || '';              // what the library knows about the filament goes back to it with the roll
      fromShop.refill = entry.filament_id ? !!entry.refill : null;
      values.spoolmandb_id = entry.spoolmandb_id || '';            // an entry that came from SpoolmanDB says so on the roll too
      from = entry.spoolmandb_id ? { id: entry.spoolmandb_id, identity: identity() } : null;
    });
    libraryRows.then((rows) => {
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
    });
    return box;
  }

  // The picture of an item (packaging): pick a file (on a phone: take a photo), see it, or take the present one away. It is sent after the item
  // itself is saved, because a new item has no address yet.
  const picture = { file: null, remove: false };
  function pictureField() {
    const preview = h('img', { class: 'image-preview', alt: t('packaging.image_alt'), hidden: true });
    const mark = () => { values.image = picture.file ? `${picture.file.name}:${picture.file.size}` : (picture.remove ? 'removed' : ''); dirty.add('image'); };
    const show = () => {
      const kept = item && item.image_version && !picture.remove;
      clear.hidden = !picture.file && !kept;
      if (picture.file) {
        const reader = new FileReader();                             // a data: address; the page may not show a blob: one
        reader.onload = () => { preview.src = reader.result; preview.hidden = false; };
        reader.readAsDataURL(picture.file);
      } else if (kept) { preview.src = imageUrl(config.image, item); preview.hidden = false; } else { preview.removeAttribute('src'); preview.hidden = true; }
    };
    const input = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', onchange: (e) => {
      picture.file = e.target.files[0] || null;
      picture.remove = false;
      mark(); show();
    } });
    const clear = h('button', { class: 'btn tool', type: 'button', hidden: true, onclick: () => {
      picture.file = null;
      picture.remove = true;
      input.value = '';
      mark(); show();
    } }, icon('trash'), h('span', {}, t('packaging.image_remove')));
    show();
    return h('div', { class: 'stack' }, field(t('packaging.image'), input, t('packaging.image_hint')), h('div', { class: 'row' }, preview, clear));
  }
  let savedId = item ? item.id : null;       // once a new item is made, a second try (the picture was refused) changes it instead of making another

  const inputs = config.fields.map((f) => {
    if (f.hidden) return null;                                       // part of what is saved, not of what is shown
    if (f.type === 'barcode') return barcodeField(f);
    if (f.type === 'brand') return brandField(f);
    if (f.type === 'color') return colourField(f);
    if (f.type === 'haspelsync') {
      return serialField({ label: f.label, hint: f.hint, value: values[f.key] || '', onchange: (serial) => { values[f.key] = serial; dirty.add(f.key); } });
    }
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
    if (catalogue && f.key === 'material') return materialField(f);
    if (catalogue && f.key === 'colour') return colourPick(f);
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
  // A copy asks how many rolls it makes (typed, or one less / one more); the button says how many it adds.
  const submit = h('button', { class: 'btn primary', type: 'submit' }, t('common.save'));
  let countField = null;
  if (copyOf) {
    const label = () => {
      const n = Number(values.count);
      submit.textContent = Number.isInteger(n) && n >= 1 ? t('filament.add_rolls', { n }) : t('common.save');
    };
    const input = h('input', { type: 'text', id: 'f-count', inputmode: 'numeric', autocomplete: 'off', required: true, value: values.count,
      oninput: (e) => { values.count = e.target.value.trim(); dirty.add('count'); label(); } });
    const step = (by) => {
      values.count = String(Math.max(1, (Number.parseInt(values.count, 10) || 1) + by));
      input.value = values.count;
      dirty.add('count');
      label();
    };
    countField = h('div', { class: 'field' }, h('label', { for: 'f-count' }, t('filament.count')),
      h('div', { class: 'row nowrap count-stepper' },
        h('button', { class: 'btn small', type: 'button', 'aria-label': t('filament.count_less'), onclick: () => step(-1) }, '−'),
        input,
        h('button', { class: 'btn small', type: 'button', 'aria-label': t('filament.count_more'), onclick: () => step(1) }, '+')),
      h('p', { class: 'hint' }, t('filament.count_hint')));
    label();
  }
  const original = item || copied || config.defaults;
  const changed = () => [...dirty].some((key) => String(values[key] ?? '') !== String(original[key] ?? ''));
  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
    h('form', { class: 'stack', method: 'dialog', onsubmit: async (e) => {
      e.preventDefault();
      try {
        const payload = toPayload(config, values);
        if (config.id === 'filament' && !item) payload.spoolmandb_id = copyOf ? String(copyOf.spoolmandb_id || '') : sourceId();
        if (fresh && fromShop.filament_id) payload.library = { filament_id: fromShop.filament_id, refill: fromShop.refill };      // for "also add to the library"
        let passOn = [];
        if (item) {
          passOn = await askToPassOn(config, item, payload);
          if (passOn === null) return;                                     // closed the question: back to the form
          await api('PATCH', `${config.path}/${item.id}`, payload);
        } else if (savedId) await api('PATCH', `${config.path}/${savedId}`, payload);
        else savedId = (await api('POST', config.path, copyOf ? { ...payload, count: values.count } : payload))?.id || null;
        if (config.image && savedId) {
          if (picture.file) {
            const form = new FormData();
            form.append('file', picture.file);
            await upload(`${config.image}/${savedId}`, form, 'PUT');
          } else if (picture.remove && item?.image_version) await api('DELETE', `${config.image}/${savedId}`);
        }
        let others = 0;
        if (passOn.length) others = (await api('POST', `${config.path}/${item.id}/propagate`, { fields: passOn })).updated;
        dialog.close();
        if (others) toast(t('propagate.done', { n: others }));
        else toast(copyOf ? t('filament.duplicated', { n: Number(values.count) }) : t('common.saved'));
        reload();
      } catch (err) { error.textContent = err.message; error.hidden = false; }
    } },
    h('h2', {}, item ? t(`${config.id}.edit`) : (copyOf ? t('filament.duplicate_title') : t(`${config.id}.new`))),
    copyOf ? h('p', { class: 'hint' }, t('filament.duplicate_intro', { name: spoolName(copyOf, ' · ') })) : null,
    item?.spoolmandb_id ? h('p', { class: 'hint' }, t('spoolmandb.item_source', { id: item.spoolmandb_id })) : null,
    countField,
    fresh ? libraryPicker() : null,
    ...inputs, config.image ? pictureField() : null, ...datalists, error,
    h('div', { class: 'row end' },
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
      submit))), { dirty: changed });
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

// What was typed and filtered on the filament page is kept while switching between its two parts.
const filamentMemory = {};

/** The barcode scanner next to a search field: on a phone a barcode is scanned rather than typed. */
const scanButton = (onCode) => h('button', { class: 'btn tool icon-only', type: 'button', 'aria-label': t('filament.search_scan'), title: t('filament.search_scan'), onclick: async () => {
  const code = await scanBarcode();
  if (code) onCode(code.trim());
} }, icon('scan'));

// The stock: what is left per kind of filament (the rolls of a kind together), with a total per material above it.
function stockView(reloadRolls) {
  const plural = (n) => t('stock.rolls', { n });
  const name = (g) => spoolName(g, ' · ');
  const state = (g) => (!g.roll_count ? h('span', { class: 'badge muted' }, t('stock.sold_out_short')) : (g.notify_low && g.low ? h('span', { class: 'badge danger' }, t('stock.low_badge')) : null));
  const view = listView({
    id: 'stock', memory: filamentMemory, tilesClass: 'stock-grid',
    search: { label: t('filament.search'), placeholder: t('filament.search_ph'), text: filamentText, extra: scanButton((code) => view.setQuery(code)) },
    filters: filamentFilters(),
    sorts: [
      { key: 'name', label: t('sort.name'), value: (g) => spoolName(g, ' ') },
      { key: 'material', label: t('sort.material'), value: (g) => norm(g.material) || '~' },
      { key: 'left', label: t('sort.left'), value: (g) => Number(g.remaining_g) },
      { key: 'rolls', label: t('sort.rolls'), value: (g) => Number(g.roll_count), desc: true }],
    tie: (g) => spoolName(g, ' '),
    rowClass: (g) => (g.roll_count ? '' : 'archived'),
    columns: [
      { label: t('nav.filament'), sort: 'name', cls: 'main', cell: (g) => h('div', { class: 'cell-main' }, spoolIcon(colourOf(g), 28),
        h('div', {}, h('span', { class: 'cell-title' }, name(g), state(g)), g.barcode ? h('div', { class: 'cell-sub muted' }, t('filament.barcode_note', { code: g.barcode })) : null)) },
      { label: t('sort.material'), sort: 'material', cell: (g) => g.material || '—' },
      { label: t('sort.rolls'), sort: 'rolls', cls: 'num', cell: (g) => String(g.roll_count) },
      { label: t('stock.per_roll_short'), wide: true, cls: 'muted', cell: (g) => (g.roll_count ? g.rolls.map((r) => `${fmt(r.remaining_g, 0)} g`).join(', ') : '—') },
      { label: t('sort.left'), sort: 'left', cls: 'num strong', cell: (g) => `${fmt(g.remaining_g, 0)} g` }],
    tile: stockTile,
    // Totals per material, of what is listed: they follow the search and the filters.
    summary(groups) {
      const materials = new Map();
      for (const g of groups) {
        const material = String(g.material || t('stock.unknown_material')).trim();
        const m = materials.get(material.toLowerCase()) || { name: material, rolls: 0, grams: 0 };         // "PLA" and "pla" are one material
        m.rolls += g.roll_count;
        m.grams += Number(g.remaining_g);
        materials.set(material.toLowerCase(), m);
      }
      return h('ul', { class: 'stat-chips', 'aria-label': t('stock.title') }, [...materials.values()].map((m) => h('li', {}, h('strong', {}, m.name),
        h('span', { class: 'muted' }, `${plural(m.rolls)} · ${fmt(m.grams, 0)} g`))));
    },
    empty: `${t('filament.empty')} ${t('common.add_first')}`, noMatch: t('stock.none_match'),
  });
  async function load() {
    try { view.setItems((await api('GET', '/api/spools/stock')).groups); } catch (e) { toast(e.message, 'error'); }
    reloadRolls?.();
  }
  return { el: view.el, load };
}

export function resourceView(key, sub) {
  const config = resources()[key];
  const part = key === 'filament' ? (sub === 'rollen' ? 'rollen' : 'voorraad') : null;
  let showArchived = false;
  let items = [];
  const nameOf = (item) => (config.name ? config.name(item) : item.name);

  const actionsOf = (item) => rowActions([
    item.spoolman_id ? null : { icon: 'edit', label: t('common.edit_named', { name: nameOf(item) }), onclick: () => openForm(config, item, load) },
    ...(config.actions ? config.actions.call(config, item, load) : []),
    config.archivable && !item.spoolman_id ? { icon: item.archived ? 'restore' : 'archive', label: item.archived ? t('common.restore') : t('common.archive'), onclick: async () => {
      await api('PATCH', `${config.path}/${item.id}`, { archived: !item.archived });
      load();
    } } : null,
    item.spoolman_id ? null : { icon: 'trash', danger: true, label: t('common.delete_named', { name: nameOf(item) }), onclick: async () => {
      if (await confirmDialog(t('common.delete_confirm', { name: nameOf(item) }))) {
        await api('DELETE', `${config.path}/${item.id}`);
        load();
      }
    } }]);

  const tile = (item) => {
    const c = config.card(item);
    return h('article', { class: `glass card item${item.archived ? ' archived' : ''}` },
      h('div', { class: 'item-head' },
        c.icon || null,
        h('div', { class: 'grow' }, h('h3', {}, c.title, c.badge ? h('span', { class: 'badge' }, c.badge) : null,
          item.archived ? h('span', { class: 'badge muted' }, t('common.archived')) : null),
        c.subtitle ? h('p', { class: 'muted' }, c.subtitle) : null)),
      h('dl', { class: 'stats' }, c.stats.map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v)))),
      c.extra || null,
      c.footnote ? h('p', { class: 'muted footnote' }, c.footnote) : null,
      actionsOf(item));
  };

  const show = () => view?.setItems(items.filter((i) => showArchived || !i.archived));
  const archiveToggle = config.archivable
    ? h('label', { class: 'check tool-check' },
      h('input', { type: 'checkbox', class: 'toggle', role: 'switch', onchange: (e) => { showArchived = e.target.checked; show(); } }),
      t('common.show_archived'))
    : null;

  // The stock is a list of its own (kinds, not rolls); every other page lists its own things.
  const stock = part === 'voorraad' ? stockView() : null;
  const view = stock ? null : listView({
    id: part === 'rollen' ? 'rolls' : config.id, memory: key === 'filament' ? filamentMemory : undefined,
    search: { label: key === 'filament' ? t('filament.search') : t('list.search'), placeholder: key === 'filament' ? t('filament.search_ph') : t('list.search_ph'),
      text: config.search, extra: key === 'filament' ? scanButton((code) => view.setQuery(code)) : null },
    filters: config.filters, sorts: config.sorts, tie: nameOf, group: config.group,
    rowClass: (item) => (item.archived ? 'archived' : ''),
    columns: [...config.columns, { label: t('list.actions'), cls: 'actions', cell: actionsOf }],
    tile, toggles: [archiveToggle],
    empty: `${config.empty} ${t('common.add_first')}`, noMatch: key === 'filament' ? t('filament.no_match') : t('list.no_match'),
  });

  async function load() {
    if (stock) { stock.load(); return; }
    try {
      items = await api('GET', config.path);
      if (config.image) {                                              // which items have a picture, in one question
        const { images } = await api('GET', config.image).catch(() => ({ images: {} }));
        for (const item of items) item.image_version = images[item.id] || '';
      }
      show();
    } catch (e) { toast(e.message, 'error'); }
  }

  load();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, config.title)),
      h('div', { class: 'row' },
        // A delivery of rolls: scan them one after the other and add them in one go. A barcode that is not known yet opens this same form.
        key === 'filament' ? h('button', { class: 'btn', type: 'button', 'aria-label': t('bulk.title'), onclick: () => openBulkScan({
          newRoll: (code, saved) => openForm({ ...config, defaults: { ...config.defaults, barcode: code } }, null, saved), reload: load }) },
        icon('scan'), h('span', {}, t('bulk.open'))) : null,
        h('button', { class: 'btn primary', type: 'button', onclick: () => openForm(config, null, load) },
          icon('plus'), h('span', {}, t(`${config.id}.new`))))),
    h('p', { class: 'muted page-intro' }, config.intro),
    key === 'printers' ? livePanel() : null,                         // what each printer is doing now: hidden without HaspelSync
    key === 'filament' ? h('div', { class: 'subbar' },
      h('nav', { class: 'subnav', 'aria-label': t('filament.parts') },
        ...[['voorraad', 'filament.part_stock'], ['rollen', 'filament.part_rolls']].map(([to, label]) => h('a', { href: `#/filament/${to}`, 'aria-current': part === to ? 'page' : null }, t(label)))),
      spoolmanBar(load)) : null,
    key === 'onderdelen' || key === 'accessoires' ? h('nav', { class: 'subnav', 'aria-label': t('parts.tabs') },
      ...[['onderdelen', 'parts.title'], ['accessoires', 'accessories.title']].map(([to, label]) => h('a', { href: `#/onderdelen${to === 'accessoires' ? '/accessoires' : ''}`, 'aria-current': key === to ? 'page' : null }, t(label)))) : null,
    stock ? stock.el : view.el);
}
