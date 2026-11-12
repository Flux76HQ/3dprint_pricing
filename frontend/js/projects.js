import { busyBadge, coverUrl, productImagesCard } from './ai-images.js';
import { api, upload } from './api.js';
import { colourOf, spoolIcon } from './filament-ui.js';
import { formatDate, t } from './i18n.js';
import { listView } from './listview.js';
import { setDirty } from './updates.js';
import { backLink, blurToggle, confirmDialog, eur, field, fill, fmt, h, headAction, icon, numberInput, parseNum, spoolName, toast } from './ui.js';

// [value sent to the server, label key]
const UNITS = [['stuks', 'unit.pieces'], ['m', 'unit.meter'], ['g', 'unit.gram']];
const dateFmt = (value) => formatDate(value, { day: 'numeric', month: 'short', year: 'numeric' });

// --- links ----------------------------------------------------------------------

// What a link of a 3D model points at: [kind kept by the server, label key]. The model itself, or a place where it is offered for sale.
export const LINK_KINDS = [['model', 'link.model'], ['marktplaats', 'link.marktplaats'], ['bol', 'link.bol'], ['etsy', 'link.etsy'], ['vinted', 'link.vinted'],
  ['webshop', 'link.webshop'], ['other', 'link.other']];
const LINK_LABELS = Object.fromEntries(LINK_KINDS);
const kindLabel = (kind) => t(LINK_LABELS[kind] || LINK_LABELS.other);
const linkName = (link) => link.label || kindLabel(link.kind);
// The kind a pasted address most likely is, from its host.
const HOSTS = [[/(^|\.)marktplaats\.nl$/, 'marktplaats'], [/(^|\.)bol\.com$/, 'bol'], [/(^|\.)etsy\.com$/, 'etsy'], [/(^|\.)vinted\.[a-z.]+$/, 'vinted'],
  [/(^|\.)(makerworld\.com|printables\.com|thingiverse\.com|thangs\.com|cults3d\.com|myminifactory\.com)$/, 'model']];
function kindOfUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return (HOSTS.find(([pattern]) => pattern.test(host)) || [])[1] || null;
  } catch { return null; }
}
const isLink = (url) => /^https?:\/\/\S+$/i.test(String(url || '').trim());
/** The links of a model as small buttons that open in a new tab. */
const linkChips = (links) => (links && links.length ? h('span', { class: 'link-chips' }, links.map((link) => h('a', { class: 'link-chip', href: link.url,
  target: '_blank', rel: 'noopener noreferrer', title: link.url }, icon('external'), h('span', {}, linkName(link))))) : null);

// --- list -----------------------------------------------------------------------

export function projectListView(ctx) {
  const href = (p) => `#/berekeningen/${p.id}`;
  const sell = (p) => (Number(p.vat_pct) > 0 ? p.totals.sell_price_incl_vat : p.totals.sell_price);
  const priced = (p) => Number(p.vat_pct) > 0 || Number(p.margin_pct) > 0 || p.price_rounding !== 'none';
  const cover = (p) => (ctx.aiImages && p.cover_image_id ? h('img', { class: 'cover-thumb', src: coverUrl(p.cover_image_id), alt: '', loading: 'lazy' }) : null);
  const badges = (p) => [p.stock_booked_at ? h('span', { class: 'badge' }, t('calc.stock_booked')) : null, ctx.aiImages && p.ai_busy ? busyBadge() : null];
  const view = listView({
    id: 'models',
    search: { label: t('calc.search'), placeholder: t('calc.search_ph'), text: (p) => [p.name, `#${p.number}`, ...p.links.map((l) => `${linkName(l)} ${l.url}`)] },
    filters: [{ key: 'kind', label: t('calc.filter_links'), all: t('calc.filter_links_all'), value: (p) => (p.links.length ? p.links.map((l) => l.kind) : ['none']),
      name: (kind) => (kind === 'none' ? t('calc.filter_links_none') : kindLabel(kind)) }],
    sorts: [
      { key: 'updated', label: t('sort.updated'), value: (p) => String(p.updated_at || ''), desc: true },
      { key: 'name', label: t('sort.name'), value: (p) => p.name },
      { key: 'number', label: t('sort.number'), value: (p) => Number(p.number) },
      { key: 'cost', label: t('calc.cost_price'), value: (p) => Number(p.totals.cost_price) },
      { key: 'sell', label: t('calc.col_sell'), value: (p) => Number(sell(p)), desc: true }],
    tie: (p) => p.name,
    href,
    columns: [
      { label: t('sort.name'), sort: 'name', cls: 'main', cell: (p) => h('div', { class: 'cell-main' }, cover(p),
        h('div', {}, h('a', { class: 'cell-title', href: href(p) }, p.name), h('div', { class: 'cell-sub muted' }, `#${p.number}`, badges(p)))) },
      { label: t('calc.cost_price'), sort: 'cost', cls: 'num private', cell: (p) => eur(p.totals.cost_price) },
      { label: t('calc.col_excl'), cls: 'num', wide: true, cell: (p) => (priced(p) ? eur(p.totals.sell_price) : '—') },
      { label: t('calc.col_sell'), sort: 'sell', cls: 'num strong', cell: (p) => (priced(p) ? eur(sell(p)) : '—') },
      { label: t('calc.links'), cls: 'nowrap', wide: true, cell: (p) => linkChips(p.links) || h('span', { class: 'muted' }, '—') },
      { label: t('sort.updated'), sort: 'updated', cls: 'nowrap', wide: true, cell: (p) => dateFmt(p.updated_at) }],
    tile: (p) => h('a', { class: 'glass card item link-card', href: href(p) },
      h('div', { class: 'item-head' }, cover(p),
        h('div', { class: 'grow' }, h('h3', {}, h('span', { class: 'badge' }, `#${p.number}`), ' ', p.name, badges(p)),
          h('p', { class: 'muted' }, dateFmt(p.updated_at)))),
      h('dl', { class: 'stats' },
        h('div', {}, h('dt', {}, t('calc.cost_price')), h('dd', { class: 'private' }, eur(p.totals.cost_price))),
        Number(p.vat_pct) > 0
          ? h('div', {}, h('dt', {}, t('calc.sell_incl', { vat: fmt(p.vat_pct) })), h('dd', {}, eur(p.totals.sell_price_incl_vat)))
          : (priced(p) ? h('div', {}, h('dt', {}, t('calc.sell')), h('dd', {}, eur(p.totals.sell_price))) : null)),
      // Not links of their own here: the whole tile is one link, and a link inside a link is not allowed.
      p.links.length ? h('p', { class: 'muted footnote' }, p.links.map(linkName).join(' · ')) : null),
    empty: t('calc.none_yet'), noMatch: t('calc.no_match'),
  });
  api('GET', '/api/projects').then((items) => view.setItems(items.map((p) => ({ ...p, links: p.links || [] })))).catch((e) => toast(e.message, 'error'));
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, t('nav.calculations'))),
      h('div', { class: 'row' }, blurToggle(ctx),
        h('a', { class: 'btn primary', href: '#/berekeningen/nieuw' }, icon('plus'), h('span', {}, t('calc.new'))))),
    h('p', { class: 'muted page-intro' }, t('calc.intro')),
    view.el);
}

// --- editor ---------------------------------------------------------------------

// "Bambu ABS Basis Black · ABS · 1.430 g op voorraad (3 rollen)": a kind of filament, not a roll, so three rolls of it are one choice.
const stockLabel = (g) => [spoolName(g), g.material,
  g.roll_count > 1 ? t('calc.in_stock_rolls', { grams: fmt(g.remaining_g, 0), n: g.roll_count }) : t('calc.in_stock', { grams: fmt(g.remaining_g, 0) })].filter(Boolean).join(' · ');
const HEX_COLOUR = /^#[0-9a-f]{6}$/i;
/** A colour as `#rrggbb`: a slicer may write capitals, or a fourth pair for opacity. '' for anything that is no colour. */
const colourCode = (value) => (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(value || '') ? value.slice(0, 7).toLowerCase() : '');
/** A colour as the eye sees it (CIE L*a*b*): in these numbers equal steps look equally far apart, which they do not in red, green, blue. */
function lab(hex) {
  const [r, g, b] = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255).map((v) => (v > 0.04045 ? ((v + 0.055) / 1.055) ** 2.4 : v / 12.92));
  const f = (v) => (v > 0.008856 ? Math.cbrt(v) : 7.787 * v + 16 / 116);
  const [x, y, z] = [f((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047), f(0.2126 * r + 0.7152 * g + 0.0722 * b), f((0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883)];
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}
/** How different two colours (`#rrggbb`) look: 0 is the same, about 2 is the least one can see, 100 is black against white. */
function colourGap(a, b) {
  const [p, q] = [lab(a), lab(b)];
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
}
const SAME_COLOUR = 22;                           // a slicer's colour and a roll's are never typed the same: this close counts as the same
const blankFilament = () => ({ spool_id: '', colour: '', label: '', grams: '', price_per_kg: '' });
const blankPart = (group) => ({ group, packaging_id: '', part_id: '', accessory_id: '', label: '', quantity: '1', unit: 'stuks', unit_price: '' });

function fromSaved(project) {
  const d = project.data || {};
  const str = (v) => (v == null ? '' : String(v));
  return {
    id: project.id, number: project.number, name: project.name, notes: project.notes, object_description: project.object_description || '', margin_pct: str(project.margin_pct),
    file_id: project.file_id || null,
    models: (project.models || []).map((m) => ({ file_id: m.file_id, label: str(m.label), meta: null })),
    links: (project.links || []).map((l) => ({ kind: l.kind || 'other', label: str(l.label), url: str(l.url) })),
    vat_pct: str(project.vat_pct),
    stock_booked_at: project.stock_booked_at,
    filament: (d.filament || []).map((r) => ({ spool_id: r.spool_id || '', colour: colourCode(r.colour), label: str(r.label), grams: str(r.grams), price_per_kg: str(r.price_per_kg) })),
    parts: (d.parts || []).map((r) => ({ group: r.group || 'onderdeel', packaging_id: r.packaging_id || '', part_id: r.part_id || '', accessory_id: r.accessory_id || '', label: str(r.label), quantity: str(r.quantity), unit: r.unit || 'stuks', unit_price: str(r.unit_price) })),
    depreciation: ((d.print || {}).depreciation || []).map((r) => ({ label: str(r.label), printer_id: r.printer_id || '', hours: str(r.hours), price_per_hour: str(r.price_per_hour) })),
    energy: ((d.print || {}).energy || []).map((r) => ({ label: str(r.label), tariff_id: r.tariff_id || '', hours: str(r.hours), kw: str(r.kw), price_per_kwh: str(r.price_per_kwh) })),
  };
}

export function projectEditorView(id, navigate, ctx = { prefs: {}, setPrefs: async () => {} }) {
  const root = h('section', { class: 'page' }, h('p', { class: 'muted' }, t('common.loading')));
  Promise.all([
    api('GET', '/api/spools'), api('GET', '/api/spools/stock').catch(() => ({ groups: [] })), api('GET', '/api/printers'), api('GET', '/api/tariffs'), api('GET', '/api/packaging'),
    api('GET', '/api/parts'), api('GET', '/api/accessories'),
    id ? api('GET', `/api/projects/${id}`) : Promise.resolve(null),
    api('GET', '/api/spoolman').catch(() => ({ enabled: false })),         // only decides what is offered; the server refuses a booking itself
  ]).then(([spools, stock, printers, tariffs, packaging, parts, accessories, project, spoolman]) => {
    root.replaceChildren(buildEditor({
      spools: spools.filter((s) => !s.archived), stock: stock.groups, printers: printers.filter((p) => !p.archived), tariffs,
      packaging: packaging.filter((p) => !p.archived), parts: parts.filter((p) => !p.archived),
      accessories: accessories.filter((p) => !p.archived), project, navigate, ctx, spoolman: !!spoolman.enabled,
    }));
  }).catch((e) => root.replaceChildren(h('p', { class: 'error', role: 'alert' }, e.message)));
  return root;
}

function buildEditor({ spools, stock, printers, tariffs, packaging, parts, accessories, project, navigate, ctx, spoolman }) {
  const state = project ? fromSaved(project) : {
    id: null, name: '', notes: '', object_description: '', margin_pct: '0', stock_booked_at: null, file_id: null, models: [], links: [],
    vat_pct: ctx.prefs.vat_pct ?? '21',
    filament: [blankFilament()], parts: [], depreciation: [], energy: [],
  };
  let printHours = '1';
  let result = null;
  let dirty = false;
  let timer = null;
  const defaultTariff = tariffs.find((t) => t.is_default) || tariffs[0];
  const perKg = (s) => String(Math.round((Number(s.price) / Number(s.roll_weight_g)) * 1000 * 100) / 100);

  // Filament is chosen per kind in stock, not per roll. A line still names one roll (the price it copies, and what a saved
  // calculation holds); `kindOf` finds the kind a roll belongs to.
  const kindOf = (spoolId) => stock.find((g) => g.spool_ids.includes(spoolId)) || null;
  const rollOf = (g) => {                                          // the roll a line of this kind points at: the one nearest to empty
    const open = [...g.rolls].sort((a, b) => Number(a.remaining_g) - Number(b.remaining_g))[0];
    return spools.find((sp) => sp.id === (open ? open.id : g.spool_ids[0])) || null;
  };
  const stockWarning = h('div', { class: 'notice warn', role: 'status', hidden: true });
  /** Says so when the lines ask for more of a kind of filament than there is. */
  function checkStock() {
    const asked = new Map();
    if (!state.stock_booked_at) {                                  // once it is booked, what is left no longer includes this print
      for (const r of state.filament) {
        const g = kindOf(r.spool_id);
        if (g) asked.set(g, (asked.get(g) || 0) + (parseNum(r.grams) || 0));
      }
    }
    const short = [...asked].filter(([g, grams]) => grams > Number(g.remaining_g));
    fill(stockWarning, h('strong', {}, t('calc.stock_short_title')),
      h('ul', {}, short.map(([g, grams]) => h('li', {}, t('calc.stock_short', { name: [spoolName(g), g.material].filter(Boolean).join(' · '), need: fmt(grams, 1), left: fmt(g.remaining_g, 0) })))));
    stockWarning.hidden = !short.length;
  }

  const costEls = { filament: [], parts: [], depreciation: [], energy: [] };
  const totals = h('dl', { class: 'totals' });
  const calcError = h('p', { class: 'error', role: 'alert', hidden: true });
  const sections = h('div', { class: 'stack' });

  const payload = () => ({
    name: state.name, notes: state.notes, object_description: state.object_description, margin_pct: parseNum(state.margin_pct),
    vat_pct: parseNum(state.vat_pct), price_rounding: 'none',      // rounding is decided per order
    file_id: state.file_id,
    models: state.models.map((m) => ({ file_id: m.file_id, label: m.label.trim() })),
    links: state.links.filter((l) => l.url.trim()).map((l) => ({ kind: l.kind, label: l.label.trim(), url: l.url.trim() })),
    data: {
      filament: state.filament.map((r) => ({ spool_id: r.spool_id || null, colour: colourCode(r.colour) || null, label: r.label, grams: parseNum(r.grams), price_per_kg: parseNum(r.price_per_kg) })),
      parts: state.parts.map((r) => ({ group: r.group, packaging_id: r.packaging_id || null, part_id: r.part_id || null, accessory_id: r.accessory_id || null, label: r.label, quantity: parseNum(r.quantity), unit: r.unit, unit_price: parseNum(r.unit_price) })),
      print: {
        depreciation: state.depreciation.map((r) => ({ label: r.label, printer_id: r.printer_id || null, hours: parseNum(r.hours), price_per_hour: parseNum(r.price_per_hour) })),
        energy: state.energy.map((r) => ({ label: r.label, tariff_id: r.tariff_id || null, hours: parseNum(r.hours), kw: parseNum(r.kw), price_per_kwh: parseNum(r.price_per_kwh) })),
      },
    },
  });

  function renderTotals() {
    if (!result) return;
    // Cost-side rows are marked private so the "hide costs" setting can blur them; selling price, VAT stay visible.
    const row = (label, value, cls = '', priv = false) => [h('dt', { class: `${cls}${priv ? ' private' : ''}` }, label), h('dd', { class: `${cls}${priv ? ' private' : ''}` }, eur(value))];
    const cost = (label, value, cls = '') => row(label, value, cls, true);
    const s = result.subtotals;
    const hasMargin = Number(result.margin_amount) > 0 || result.rounding !== 'none';
    const hasVat = Number(result.vat_pct) > 0;
    totals.replaceChildren(
      ...cost(t('calc.filament'), s.filament), ...cost(t('calc.parts'), s.parts), ...cost(t('calc.charger'), s.charger),
      ...cost(t('calc.sub_parts'), s.parts_and_charger, 'sub'),
      ...(Number(s.packaging) > 0 ? cost(t('calc.packaging'), s.packaging) : []),
      ...cost(t('calc.depreciation'), s.depreciation), ...cost(t('calc.energy'), s.energy),
      ...cost(t('calc.sub_energy'), s.energy_and_depreciation, 'sub'),
      ...cost(t('calc.total_cost'), result.cost_price, 'grand'),
      ...(hasMargin ? cost(t('calc.margin', { pct: fmt(result.margin_pct_effective) }), result.margin_amount) : []),
      ...(hasMargin || hasVat ? row(t('calc.sell_excl'), result.sell_price, 'sub') : []),
      ...(hasVat ? [...row(t('calc.vat', { pct: fmt(result.vat_pct) }), result.vat_amount), ...row(t('calc.sell_incl_vat'), result.sell_price_incl_vat, 'grand')] : []));
    for (const key of Object.keys(costEls)) {
      costEls[key].forEach((el, i) => {
        if (el && result[key][i]) {
          el.textContent = eur(result[key][i].cost);
          if (result[key][i].hours_billed) el.title = t('calc.billed_as', { hours: fmt(result[key][i].hours_billed, 0) });
        }
      });
    }
  }

  async function recalc() {
    try {
      const body = payload();
      result = await api('POST', '/api/calculate', { data: body.data, margin_pct: body.margin_pct, vat_pct: body.vat_pct, price_rounding: body.price_rounding });
      calcError.hidden = true;
      renderTotals();
    } catch (e) {
      calcError.textContent = e.message;
      calcError.hidden = false;
    }
  }
  function touch() {
    checkStock();
    dirty = true;
    setDirty(true);
    clearTimeout(timer);
    timer = setTimeout(recalc, 200);
  }

  const bind = (obj, key, extra) => (v) => { obj[key] = v; if (extra) extra(); touch(); };
  const textInput = (obj, key, attrs = {}) => h('input', { type: 'text', value: obj[key], ...attrs, oninput: (e) => bind(obj, key)(e.target.value) });
  const costCell = (bucket, index) => {
    const el = h('output', { class: 'cost private' }, '—');
    costEls[bucket][index] = el;
    return h('div', { class: 'field cost-field' }, h('span', { class: 'lbl' }, t('calc.cost')), el);
  };
  const removeBtn = (label, onClick) => h('button', { class: 'btn small danger icon-only', type: 'button', 'aria-label': label, onclick: onClick }, icon('trash'));
  const select = (options, value, onChange) => h('select', { onchange: (e) => onChange(e.target.value) },
    options.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));

  function setHours(v) {
    printHours = v;
    state.depreciation.forEach((r) => { r.hours = v; });
    state.energy.forEach((r) => { r.hours = v; });
  }

  function addPrinterRows(p) {
    state.depreciation.push({ label: t('calc.depreciation_of', { name: p.name }), printer_id: p.id, hours: printHours, price_per_hour: String(Math.round((Number(p.purchase_price) / Number(p.lifetime_hours)) * 10000) / 10000) });
    state.energy.push({ label: t('calc.power_of', { name: p.name }), tariff_id: defaultTariff ? defaultTariff.id : '', hours: printHours, kw: String(Number(p.power_kw)), price_per_kwh: defaultTariff ? String(Number(defaultTariff.price_per_kwh)) : '' });
  }

  // A card of lines. On a wide screen the lines read as a table: only the first one says what its fields are.
  function section(title, hint, rows, addButtons, after = null) {
    return h('div', { class: 'glass card lines-card' },
      h('h2', {}, title), hint ? h('p', { class: 'muted' }, hint) : null,
      h('div', { class: 'lines' }, rows), after, h('div', { class: 'row line-actions' }, addButtons));
  }
  const addButton = (label, onclick) => h('button', { class: 'btn tool', type: 'button', onclick }, icon('plus'), h('span', {}, label));

  function filamentSection() {
    costEls.filament = [];
    // Every line shows its colour: that of the filament chosen from stock, else the one the print file gave the line.
    const withColour = (r, picker) => {
      const kind = kindOf(r.spool_id);
      const cell = field(t('calc.roll'), picker);
      const row = h('div', { class: 'with-swatch' });
      picker.replaceWith(row);
      row.append(spoolIcon(kind ? colourOf(kind) : colourCode(r.colour) || null, 32), picker);
      return cell;
    };
    const rows = state.filament.map((r, i) => h('div', { class: 'line filament' },
      withColour(r, select([['', t('calc.manual')], ...stock.map((g) => [g.key, stockLabel(g)])], kindOf(r.spool_id)?.key || '', (v) => {
        const s = v ? rollOf(stock.find((g) => g.key === v)) : null;
        r.spool_id = s ? s.id : '';
        if (s) { r.label = spoolName(s); r.price_per_kg = perKg(s); }
        touch(); redraw();
      })),
      field(t('calc.description'), textInput(r, 'label')),
      field(t('calc.print_weight'), numberInput(r.grams, bind(r, 'grams'))),
      field(t('calc.price_per_kg'), numberInput(r.price_per_kg, bind(r, 'price_per_kg'))),
      costCell('filament', i),
      removeBtn(t('calc.remove_filament'), () => { state.filament.splice(i, 1); touch(); redraw(); })));
    checkStock();
    return section(t('calc.filament'), spools.length ? null : t('calc.tip_spools'), rows,
      addButton(t('calc.add_filament'), () => { state.filament.push(blankFilament()); redraw(); }), stockWarning);
  }

  // Each group of lines can pick from its own list (packaging, parts, accessories); a line keeps the price it was given.
  const catalogues = {
    verpakking: { items: packaging, key: 'packaging_id', label: 'calc.packaging' },
    onderdeel: { items: parts, key: 'part_id', label: 'calc.part' },
    oplader: { items: accessories, key: 'accessory_id', label: 'calc.accessory' },
  };

  function partsSection(group, title, hint, canAdd = true) {
    const { items, key, label } = catalogues[group];
    const known = (r) => (r[key] && items.some((p) => p.id === r[key]) ? r[key] : '');
    const rows = state.parts.map((r, i) => (r.group !== group ? null : h('div', { class: 'line parts pack' },
      field(t(label), select([['', t('calc.manual')], ...items.map((p) => [p.id, `${p.name} · ${eur(p.price)}`])], known(r), (v) => {
        const p = items.find((x) => x.id === v);
        r[key] = v;
        if (p) { r.label = p.name; r.unit = p.unit || 'stuks'; r.unit_price = String(Number(p.price)); }
        touch(); redraw();
      })),
      field(t('calc.description'), textInput(r, 'label')),
      field(t('calc.quantity'), numberInput(r.quantity, bind(r, 'quantity'))),
      field(t('calc.unit'), select(UNITS.map(([v, k]) => [v, t(k)]), r.unit, (v) => { r.unit = v; touch(); })),
      field(r.unit === 'g' ? t('calc.price_per_kg') : (r.unit === 'm' ? t('calc.price_per_meter') : t('calc.price_per_piece')), numberInput(r.unit_price, bind(r, 'unit_price'))),
      costCell('parts', i),
      removeBtn(t('calc.remove_line'), () => { state.parts.splice(i, 1); touch(); redraw(); }))));
    return section(title, hint, rows,
      canAdd ? addButton(t('calc.add_line'), () => { state.parts.push(blankPart(group)); redraw(); }) : null);
  }

  function printSection() {
    const printerSelect = h('select', { 'aria-label': t('calc.printer') }, printers.map((p) => h('option', { value: p.id }, p.name)));
    const addPrinter = () => {
      const p = printers.find((x) => x.id === printerSelect.value);
      if (!p) return;
      addPrinterRows(p);
      touch(); redraw();
    };
    const hoursInput = numberInput(printHours, (v) => {
      setHours(v);
      touch();
      document.querySelectorAll('.line.print input[data-hours]').forEach((el) => { el.value = v; });
    });
    costEls.depreciation = [];
    costEls.energy = [];
    const depRows = state.depreciation.map((r, i) => h('div', { class: 'line print' },
      field(t('calc.depreciation_short'), textInput(r, 'label')),
      field(t('calc.hours'), numberInput(r.hours, bind(r, 'hours'), { 'data-hours': '1' })),
      field(t('calc.price_per_hour'), numberInput(r.price_per_hour, bind(r, 'price_per_hour'))),
      costCell('depreciation', i),
      removeBtn(t('calc.remove_depreciation'), () => { state.depreciation.splice(i, 1); touch(); redraw(); })));
    const energyRows = state.energy.map((r, i) => h('div', { class: 'line print energy' },
      field(t('calc.energy'), textInput(r, 'label')),
      field(t('calc.hours'), numberInput(r.hours, bind(r, 'hours'), { 'data-hours': '1' })),
      field(t('calc.power_kw'), numberInput(r.kw, bind(r, 'kw'))),
      field(t('calc.tariff'), select([['', t('calc.manual')], ...tariffs.map((t) => [t.id, `${t.name} · ${eur(t.price_per_kwh)}`])], r.tariff_id, (v) => {
        r.tariff_id = v;
        const t = tariffs.find((x) => x.id === v);
        if (t) r.price_per_kwh = String(Number(t.price_per_kwh));
        touch(); redraw();
      })),
      field(t('calc.price_per_kwh'), numberInput(r.price_per_kwh, bind(r, 'price_per_kwh'))),
      costCell('energy', i),
      removeBtn(t('calc.remove_energy'), () => { state.energy.splice(i, 1); touch(); redraw(); })));
    const extraEnergy = () => { state.energy.push({ label: t('calc.extra_energy_label'), tariff_id: defaultTariff ? defaultTariff.id : '', hours: printHours, kw: '', price_per_kwh: defaultTariff ? String(Number(defaultTariff.price_per_kwh)) : '' }); redraw(); };
    const extraDepreciation = () => { state.depreciation.push({ label: t('calc.depreciation_short'), printer_id: '', hours: printHours, price_per_hour: '' }); redraw(); };
    // Three parts, each with its own heading: how long and on which printer, then what the printer costs per hour, then what the power costs.
    const part = (title, rows, add) => h('div', { class: 'line-group' },
      h('div', { class: 'sub-head' }, h('h3', {}, title), add),
      rows.length ? h('div', { class: 'lines' }, rows) : h('p', { class: 'muted line-none' }, t('calc.no_lines')));
    return h('div', { class: 'glass card lines-card' },
      h('h2', {}, t('calc.print_title')),
      !printers.length ? h('p', { class: 'muted' }, t('calc.tip_printers')) : null,
      h('div', { class: 'print-setup' },
        field(t('calc.print_hours'), hoursInput),
        printers.length ? field(t('calc.printer'), printerSelect) : null,
        printers.length ? h('button', { class: 'btn', type: 'button', onclick: addPrinter }, icon('plus'), h('span', {}, t('calc.add_printer'))) : null,
        h('p', { class: 'hint' }, t('calc.print_hours_hint'))),
      part(t('calc.depreciation'), depRows, addButton(t('calc.extra_depreciation'), extraDepreciation)),
      part(t('calc.energy'), energyRows, addButton(t('calc.extra_energy'), extraEnergy)));
  }

  function redraw() {
    costEls.parts = [];
    fill(sections,
      filamentSection(),
      partsSection('onderdeel', t('calc.other_parts'), parts.length ? t('calc.other_parts_hint') : t('calc.parts_tip')),
      partsSection('oplader', t('calc.charger_title'), accessories.length ? t('calc.charger_hint') : t('calc.accessories_tip')),
      // Packaging is added on the order now; a calculation saved with packaging keeps it (and its cost) until the lines are removed.
      state.parts.some((r) => r.group === 'verpakking') ? partsSection('verpakking', t('calc.packaging_title'), t('calc.packaging_hint'), false) : null,
      printSection());
    renderTotals();
  }

  async function save(asCopy = false) {
    try {
      const body = payload();
      if (asCopy) body.name = t('calc.copy_name', { name: body.name });
      const saved = state.id && !asCopy ? await api('PUT', `/api/projects/${state.id}`, body) : await api('POST', '/api/projects', body);
      dirty = false;
      setDirty(false);
      toast(t('common.saved'));
      if (!state.id || asCopy) navigate(`#/berekeningen/${saved.id}`);
      else { state.stock_booked_at = saved.stock_booked_at; }
    } catch (e) { toast(e.message, 'error'); }
  }

  async function bookStock() {
    if (dirty) { toast(t('calc.save_first'), 'error'); return; }
    if (!(await confirmDialog(t('calc.book_confirm'), t('calc.book')))) return;
    try {
      const res = await api('POST', `/api/projects/${state.id}/book-stock`);
      toast(res.short.length ? t('calc.booked_short', { items: res.short.join(', ') }) : t('calc.stock_booked'), res.short.length ? 'error' : 'info');
      navigate(`#/berekeningen/${state.id}`, true);
    } catch (e) { toast(e.message, 'error'); }
  }

  // --- print file: upload, read, adopt -------------------------------------------------
  let fileMeta = null;
  let imagesCard = null;                              // the product images card, once it is there: the 3D model is shown in it
  let plateIndex = 0;                                 // ALL_PLATES = every plate of the file together
  const ALL_PLATES = -1;
  let densities = {};
  let material = 'PLA';
  let fillPct = '40';
  let estimateTimer = null;
  const fileBox = h('div', { class: 'glass card stack' });

  // The kind of filament in stock that a file's filament is: the same material, and the colour that looks nearest to the slicer's
  // (close enough to be that colour). Without a colour in the file it is only chosen when there is one kind of that material.
  // "PLA" in the file is also a roll typed as "PLA Matte" or "PLA+", but only when no roll is plain "PLA".
  const stockFor = (type, colour) => {
    const material = String(type || '').trim().toUpperCase();
    const of = (g) => (g.material || '').trim().toUpperCase();
    let same = stock.filter((g) => material && of(g) === material);
    if (!same.length) same = stock.filter((g) => material && of(g).startsWith(material) && !/[A-Z0-9]/.test(of(g)[material.length] || ' '));
    if (!HEX_COLOUR.test(colour || '')) return same.length === 1 ? same[0] : null;
    const near = same.map((g) => [g, colourOf(g)]).filter(([, hex]) => hex).map(([g, hex]) => [g, colourGap(hex, colour)])
      .filter(([, gap]) => gap <= SAME_COLOUR)
      .sort((a, b) => a[1] - b[1] || Number(b[0].remaining_g) - Number(a[0].remaining_g));     // nearest first, then where most is left
    return near.length ? near[0][0] : null;
  };
  const filamentRow = (label, grams, type, colour) => {
    const code = colourCode(colour);
    const g = stockFor(type, code);
    const sp = g ? rollOf(g) : null;
    return { spool_id: sp ? sp.id : '', colour: code, label: sp ? spoolName(sp) : label, grams: String(grams), price_per_kg: sp ? perKg(sp) : '' };
  };

  // All plates as one: hours and grams added up, the same filament (type and colour) on different plates as one line.
  function combinePlates(plates) {
    const byFilament = new Map();
    let hours = null;
    for (const pl of plates) {
      if (pl.hours) hours = (hours || 0) + pl.hours;
      for (const f of pl.filaments) {
        const key = `${f.type}|${colourCode(f.color) || f.color}`;
        const known = byFilament.get(key);
        if (known) known.grams += f.grams;
        else byFilament.set(key, { ...f });
      }
    }
    const filaments = [...byFilament.values()].map((f) => ({ ...f, grams: Math.round(f.grams * 10) / 10 }));
    const grams = Math.round(filaments.reduce((sum, f) => sum + f.grams, 0) * 10) / 10;
    return { hours: hours && Math.round(hours * 100) / 100, grams: grams || null, filaments };
  }

  // Takes the filament and the hours from the slicer into the calculation: a line per filament of the file, each on the kind in
  // stock with its material and colour (and priced from it), whole print hours, and a printer line with depreciation and energy.
  function adoptSliced(plate, auto = false) {
    state.filament = plate.filaments.map((f) => filamentRow(`${f.type} ${f.color}`.trim() || t('calc.filament'), f.grams, f.type, f.color));
    const notes = [];
    let whole = null;
    if (plate.hours) {
      whole = Math.ceil(plate.hours);                 // machine time is charged in whole hours, rounded up
      setHours(String(whole));
      if (!state.depreciation.length) {
        if (printers.length) addPrinterRows(printers[0]);
        else notes.push(t('file.note_printer'));
      }
      if (!defaultTariff) notes.push(t('file.note_tariff'));
    }
    if (state.filament.some((r) => !r.price_per_kg)) notes.push(t('file.note_roll'));
    touch(); redraw();
    const what = `${fmt(plate.grams || 0, 1)} g${whole ? `, ${fmt(plate.hours, 2)} ${t('file.hours_short')} → ${whole} ${t('file.hours_short')}` : ''}`;
    toast(`${auto ? t('file.adopted_auto') : t('file.adopted')}: ${what}.${notes.length ? ` ${t('file.attention')}: ${notes.join('; ')}.` : ''}`, notes.length ? 'error' : 'info');
  }

  const autoToggle = () => h('label', { class: 'check' },
    h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: ctx.prefs.auto_adopt_file !== false,
      onchange: (e) => ctx.setPrefs({ auto_adopt_file: e.target.checked }) }),
    t('file.auto_adopt'));

  async function adoptEstimate() {
    try {
      const res = await api('GET', `/api/print-files/${fileMeta.id}/estimate?density=${densities[material]}&fill=${parseNum(fillPct)}`);
      state.filament = [filamentRow(t('file.estimate_label', { material, file: fileMeta.filename }), res.grams, material)];
      touch(); redraw();
      toast(t('file.estimate_adopted'));
    } catch (e) { toast(e.message, 'error'); }
  }

  // The links of the model: where it comes from, and where it is offered for sale. A pasted address says what it is by its host.
  const MAX_LINKS = 12;
  const linksBox = h('div', { class: 'line-group links' });
  function drawLinks() {
    const rows = state.links.map((link, i) => {
      const openLink = h('a', { class: 'btn tool icon-only', target: '_blank', rel: 'noopener noreferrer', title: t('file.open_link'), 'aria-label': t('file.open_link') }, icon('external'));
      const kind = select(LINK_KINDS.map(([value, label]) => [value, t(label)]), link.kind, (v) => { link.kind = v; link.picked = true; touch(); });
      const mark = () => {
        if (isLink(link.url)) openLink.href = link.url.trim(); else openLink.removeAttribute('href');
        openLink.setAttribute('aria-disabled', String(!isLink(link.url)));
      };
      const url = h('input', { type: 'url', inputmode: 'url', value: link.url, maxlength: 500, placeholder: t('file.link_ph'), oninput: (e) => {
        link.url = e.target.value;
        const guess = kindOfUrl(link.url.trim());
        if (guess && !link.picked) { link.kind = guess; kind.value = guess; }       // until a kind was chosen by hand
        mark(); touch();
      } });
      mark();
      return h('div', { class: 'line weblink' },
        field(t('file.link_kind'), kind),
        field(t('file.link_url'), url),
        field(t('file.link_label'), textInput(link, 'label', { maxlength: 60, placeholder: t('file.link_label_ph') })),
        h('div', { class: 'row-actions' }, openLink, removeBtn(t('file.link_remove'), () => { state.links.splice(i, 1); touch(); drawLinks(); })));
    });
    const add = () => {
      state.links.push({ kind: state.links.some((l) => l.kind === 'model') ? 'other' : 'model', label: '', url: '' });
      drawLinks();
      linksBox.querySelector('.line:last-child input[type=url]')?.focus();
    };
    fill(linksBox,
      h('div', { class: 'sub-head' }, h('h3', {}, t('file.links_title')), state.links.length < MAX_LINKS ? addButton(t('file.link_add'), add) : null),
      rows.length ? h('div', { class: 'lines' }, rows) : h('p', { class: 'muted line-none' }, t('file.links_hint')));
  }
  drawLinks();

  // The 3D models of the object, one per part: to look at and to make pictures from. They are apart from the file above them,
  // which is the one the filament is worked out from.
  function modelsBox() {
    const add = h('input', { type: 'file', accept: '.stl,.3mf', multiple: true, 'aria-label': t('file.model_add'), onchange: async () => {
      add.disabled = true;
      for (const file of add.files) {
        const form = new FormData();
        form.append('file', file);
        try {
          const meta = await upload('/api/print-files', form);
          state.models.push({ file_id: meta.id, label: '', meta });
          touch();
        } catch (err) { toast(`${file.name}: ${err.message}`, 'error'); }
      }
      drawFile();
    } });
    const rows = state.models.map((m, i) => h('div', { class: 'list-row' },
      h('div', { class: 'model-row' },
        field(t('file.model_label'), textInput(m, 'label', { maxlength: 60, placeholder: t('file.model_label_ph') })),
        h('p', { class: 'muted' }, m.meta ? m.meta.filename : t('common.loading'))),
      h('div', { class: 'row' },
        imagesCard ? h('button', { class: 'btn small', type: 'button', onclick: () => imagesCard.showModel(m.file_id) }, t('file.view_3d')) : null,
        h('a', { class: 'btn small', href: `/api/print-files/${m.file_id}/download` }, t('file.download')),
        removeBtn(t('file.model_remove'), () => { state.models.splice(i, 1); touch(); drawFile(); }))));
    return h('div', { class: 'stack' },
      h('h3', {}, t('file.models_title')), h('p', { class: 'muted' }, t('file.models_intro')),
      ...rows, field(t('file.model_add'), add, t('file.model_add_hint')));
  }

  function drawFile() {
    const parts = [h('h2', {}, t('file.title')), h('h3', {}, t('file.calc_title')), h('p', { class: 'muted' }, t('file.calc_intro'))];
    if (!fileMeta) {
      const input = h('input', { type: 'file', accept: '.stl,.3mf', onchange: async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        input.disabled = true; status.textContent = t('file.reading');
        const form = new FormData();
        form.append('file', file);
        try {
          fileMeta = await upload('/api/print-files', form);
          state.file_id = fileMeta.id; plateIndex = 0; touch();
          if (!Object.keys(densities).length) densities = await api('GET', '/api/print-files/materials');
        } catch (err) { toast(err.message, 'error'); }
        drawFile();
        const first = fileMeta && fileMeta.analysis.plates[0];
        if (first && ctx.prefs.auto_adopt_file !== false) adoptSliced(first, true);
      } });
      const status = h('p', { class: 'muted', role: 'status' });
      parts.push(field(t('file.field'), input, t('file.field_hint')), autoToggle(), status);
    } else {
      const a = fileMeta.analysis;
      parts.push(h('div', { class: 'list-row' },
        h('div', {}, h('strong', {}, fileMeta.filename),
          h('p', { class: 'muted' }, `${fileMeta.size_bytes < 1048576 ? `${fmt(fileMeta.size_bytes / 1024, 0)} kB` : `${fmt(fileMeta.size_bytes / 1048576, 1)} MB`} · `, h('span', { class: `badge${a.exact ? '' : ' muted'}` }, a.exact ? t('file.exact') : t('file.estimated')))),
        h('div', { class: 'row' },
          imagesCard && !state.models.length ? h('button', { class: 'btn small', type: 'button', onclick: () => imagesCard.showModel() }, t('file.view_3d')) : null,
          h('a', { class: 'btn small', href: `/api/print-files/${fileMeta.id}/download` }, t('file.download')),
          h('button', { class: 'btn small', type: 'button', onclick: () => { fileMeta = null; state.file_id = null; touch(); drawFile(); } }, t('file.unlink')))));
      if (a.plates.length) {
        const all = a.plates.length > 1 && plateIndex === ALL_PLATES;
        const plate = all ? combinePlates(a.plates) : a.plates[Math.min(Math.max(plateIndex, 0), a.plates.length - 1)];
        if (a.plates.length > 1) {
          const total = combinePlates(a.plates);
          parts.push(field(t('file.plate'), h('select', { onchange: (e) => { plateIndex = Number(e.target.value); drawFile(); } },
            [...a.plates.map((pl, i) => h('option', { value: i, selected: i === plateIndex }, `${t('file.plate')} ${pl.index}${pl.grams ? ` · ${fmt(pl.grams, 1)} g` : ''}`)),
              h('option', { value: ALL_PLATES, selected: all }, `${t('file.all_plates')}${total.grams ? ` · ${fmt(total.grams, 1)} g` : ''}`)])));
        }
        parts.push(h('dl', { class: 'stats' },
          h('div', {}, h('dt', {}, t('file.print_time')), h('dd', {}, plate.hours ? t('file.hours', { n: fmt(plate.hours, 2) }) : '—')),
          h('div', {}, h('dt', {}, t('file.filament_total')), h('dd', {}, plate.grams ? `${fmt(plate.grams, 1)} g` : '—'))),
        h('ul', { class: 'plain-list' }, plate.filaments.map((f) => {
          const dot = h('span', { class: 'dot', 'aria-hidden': 'true' });
          if (colourCode(f.color)) dot.style.background = colourCode(f.color);
          return h('li', { class: 'row' }, dot, `${f.type || t('calc.filament')} ${f.color}`.trim(), h('span', { class: 'muted' }, `· ${fmt(f.grams, 1)} g`));
        })),
        h('button', { class: 'btn primary', type: 'button', onclick: () => adoptSliced(plate) }, t('file.adopt')),
        autoToggle());
      } else {
        const estimate = h('output', { class: 'cost' }, '…');
        const refresh = () => {
          clearTimeout(estimateTimer);
          estimateTimer = setTimeout(async () => {
            try {
              const res = await api('GET', `/api/print-files/${fileMeta.id}/estimate?density=${densities[material]}&fill=${parseNum(fillPct)}`);
              estimate.textContent = `≈ ${fmt(res.grams, 1)} g`;
            } catch (e) { estimate.textContent = e.message; }
          }, 150);
        };
        parts.push(h('dl', { class: 'stats' },
          h('div', {}, h('dt', {}, t('file.volume')), h('dd', {}, `${fmt(a.volume_cm3, 1)} cm³`)),
          a.bbox_mm ? h('div', {}, h('dt', {}, t('file.dimensions')), h('dd', {}, `${a.bbox_mm.map((v) => fmt(v, 0)).join(' × ')} mm`)) : null),
        h('p', { class: 'muted' }, t('file.no_slicer')),
        h('div', { class: 'two' },
          field(t('file.material'), h('select', { onchange: (e) => { material = e.target.value; refresh(); } },
            Object.keys(densities).map((m) => h('option', { value: m, selected: m === material }, `${m} (${fmt(densities[m])} g/cm³)`)))),
          field(t('file.fill'), numberInput(fillPct, (v) => { fillPct = v; refresh(); }), t('file.fill_hint'))),
        h('div', { class: 'row' }, estimate, h('button', { class: 'btn primary', type: 'button', onclick: adoptEstimate }, t('file.adopt_estimate'))));
        refresh();
      }
    }
    fill(fileBox, ...parts, modelsBox(), linksBox);
  }

  // what the linked models are called: asked once, for the list
  state.models.forEach((m) => {
    api('GET', `/api/print-files/${m.file_id}`).then((meta) => { m.meta = meta; drawFile(); }).catch(() => { m.meta = { filename: '?' }; drawFile(); });
  });
  if (state.file_id) {
    Promise.all([api('GET', `/api/print-files/${state.file_id}`), api('GET', '/api/print-files/materials')])
      .then(([meta, dens]) => { fileMeta = meta; densities = dens; drawFile(); })
      .catch(() => { state.file_id = null; drawFile(); });
  } else {
    api('GET', '/api/print-files/materials').then((d) => { densities = d; }).catch(() => {});
  }
  drawFile();

  const nameInput = textInput(state, 'name', { required: true, maxlength: 120, placeholder: t('calc.name_ph') });
  const marginInput = numberInput(state.margin_pct, bind(state, 'margin_pct'), { class: 'private' });
  const vatInput = numberInput(state.vat_pct, bind(state, 'vat_pct'), { list: 'vat-presets' });
  const vatPresets = h('datalist', { id: 'vat-presets' }, ['0', '9', '21'].map((v) => h('option', { value: v })));
  const notes = h('textarea', { rows: 2, oninput: (e) => bind(state, 'notes')(e.target.value) }, state.notes || '');
  const objectDescription = h('textarea', { rows: 2, maxlength: 500, placeholder: t('calc.object_description_ph'),
    oninput: (e) => bind(state, 'object_description')(e.target.value) }, state.object_description || '');
  // With Spoolman linked, what is used is kept there: booking it here as well would take the same grams off twice.
  const bookable = state.id && !state.stock_booked_at && state.filament.some((r) => r.spool_id);
  const canBook = bookable && !spoolman;

  const remove = async () => {
    if (await confirmDialog(t('calc.delete_confirm'))) {
      await api('DELETE', `/api/projects/${state.id}`).catch((e) => toast(e.message, 'error'));
      navigate('#/berekeningen');
    }
  };
  // What can be done with the model, as one compact group in the title bar: always within reach, however far the page is scrolled.
  const actions = h('div', { class: 'row actions' },
    state.id ? h('div', { class: 'btn-group', role: 'group', 'aria-label': t('calc.actions') },
      headAction('copy', t('calc.save_copy'), () => save(true)),
      canBook ? headAction('box', t('calc.book_stock_short'), bookStock) : null,
      headAction('trash', t('common.delete'), remove, ' danger')) : null,
    headAction('save', t('common.save'), () => save(false), ' primary'));
  // The colour of the 3D model where its file names none: what the first filament line says, the print file's own colour for it
  // before that of the roll chosen for it.
  const modelColour = () => {                         // (declared before the card that asks for it)
    for (const r of state.filament) {
      const kind = kindOf(r.spool_id);
      const colour = colourCode(r.colour) || (kind ? colourOf(kind) : '');
      if (colour) return colour;
    }
    return '';
  };
  if (ctx.aiImages && state.id) {
    imagesCard = productImagesCard(state.id, () => state.object_description, () => !!ctx.prefs.business_mode,
      // the models to look at: the 3D models of the calculation, or, while there are none, the file its filament is worked out from
      () => ({
        models: state.models.length
          ? state.models.map((m, i) => ({ fileId: m.file_id, label: m.label.trim() || (m.meta ? m.meta.filename : `${t('file.model')} ${i + 1}`) }))
          : (state.file_id ? [{ fileId: state.file_id, label: fileMeta ? fileMeta.filename : t('file.model') }] : []),
        colour: modelColour(),
      }));
    drawFile();                                       // the file card has a button that leads to it
  }

  redraw();
  recalc();
  return h('div', { class: 'editor' },
    h('header', { class: 'page-head' },
      h('div', {}, backLink('#/berekeningen', t('nav.calculations')),
        h('h1', {}, state.id ? t('calc.title') : t('calc.new'), state.number ? h('span', { class: 'badge' }, `#${state.number}`) : null),
        state.stock_booked_at ? h('span', { class: 'badge' }, t('calc.stock_booked')) : null),
      actions),
    h('div', { class: 'editor-grid' },
      h('div', { class: 'stack' },
        h('div', { class: 'glass card stack' },
          field(t('calc.project'), nameInput),
          h('div', { class: 'two even' },
            field(t('calc.margin_field'), marginInput, t('calc.margin_hint')),
            field(t('calc.vat_field'), vatInput, t('calc.vat_hint'))),
          vatPresets,
          h('div', { class: 'two even' },
            field(t('common.notes'), notes),
            field(t('calc.object_description'), objectDescription, t('calc.object_description_hint')))),
        fileBox,
        imagesCard,
        sections),
      h('aside', { class: 'glass card summary', 'aria-label': t('calc.cost_price') },
        h('div', { class: 'row between' }, h('h2', {}, t('calc.cost_price')), blurToggle(ctx)), totals, calcError,
        bookable && spoolman ? h('p', { class: 'hint' }, t('calc.book_spoolman')) : null)));
}
