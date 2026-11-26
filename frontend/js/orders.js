import { api, downloadFile } from './api.js';
import { coverFileUrl, coverUrl } from './ai-images.js';
import { formatDate, t } from './i18n.js';
import { customerFields, customerLines, customerPicker, emptyCustomer } from './customers.js';
import { colourOf, spoolIcon } from './filament-ui.js';
import { listView } from './listview.js';
import { openLightbox } from './lightbox.js';
import { setDirty } from './updates.js';
import { ROUNDINGS, backLink, confirmDialog, enhanceDialog, eur, field, fill, fmt, h, headAction, icon, numberInput, parseNum, saveBlob, spoolName, toast } from './ui.js';

// The stages of an order, in order. The words come from the language files.
export const STATUSES = ['nieuw', 'in_behandeling', 'verwerkt', 'verstuurd', 'afgehandeld'];
const STATUS_KEYS = { nieuw: 'orders.status_nieuw', in_behandeling: 'orders.status_in_behandeling', verwerkt: 'orders.status_verwerkt', verstuurd: 'orders.status_verstuurd', afgehandeld: 'orders.status_afgehandeld' };
const statusLabel = (s) => t(STATUS_KEYS[s]);
// A date without a time is a day on the calendar, not a moment in UTC: noon keeps it on that day in every time zone.
const dateFmt = (v) => (v ? formatDate(`${v}T12:00:00`, { day: 'numeric', month: 'short', year: 'numeric' }) : '—');
const today = () => new Date().toLocaleDateString('sv-SE');          // YYYY-MM-DD in the local time zone

const stat = (label, value) => h('div', {}, h('dt', {}, label), h('dd', {}, value));
// The cover picture of a calculation as a small thumbnail; the address holds the picture's id, which never changes, so the browser keeps it.
const cover = (id) => h('img', { class: 'cover-thumb', src: coverUrl(id), alt: '', loading: 'lazy' });

// What the overview calls an order: its “Betreft”, or, as on the invoice, “Bestelling <number>” when none was filled in. The customer goes
// under it, smaller; the number is left out of the small line when it already is the title.
const titleOf = (o) => o.subject || t('orders.number', { n: o.number });
const numberOf = (o) => (o.subject ? t('orders.number', { n: o.number }) : null);

// An open order that takes more filament than there is (the server says it: `filament_short`, the kinds with what is missing of each, the same rule as the
// *Filament* card of the order itself): a label, and under it which filament and how much, so that it can be bought without opening the order.
function filamentFlag(o) {
  const short = o.filament_short || [];
  if (!short.length) return null;
  const kinds = short.map((k) => t('orders.filament_short_kind', { name: [spoolName(k, ' · '), k.material].filter(Boolean).join(' · '), short: fmt(k.short_g, 0) }));
  return h('div', { class: 'filament-flag', role: 'status' }, h('span', { class: 'pill warn' }, t('orders.filament_short_flag')), h('span', { class: 'muted' }, kinds.join('; ')));
}

// --- list -----------------------------------------------------------------------

/** The overview of orders. `customer` (an id) narrows it to the orders of that customer, as the link on a customer does. */
export function orderListView({ customer = '' } = {}) {
  const href = (o) => `#/bestellingen/${o.id}`;
  let customers = new Map();                                       // customer id -> how the filter names it, from the rows (the newest order's name comes first)
  // One select on the row sets the stage at once, without opening the order.
  function statusSelect(order) {
    return h('select', { class: 'status', 'data-status': order.status, 'aria-label': t('orders.status_of', { name: order.customer_name }),
      onchange: async (e) => {
        try {
          await api('PATCH', `/api/orders/${order.id}/status`, { status: e.target.value });
          toast(t('orders.status_set', { status: statusLabel(e.target.value) }));
          load();
        } catch (err) { toast(err.message, 'error'); load(); }
      } }, STATUSES.map((s) => h('option', { value: s, selected: s === order.status }, statusLabel(s))));
  }
  const view = listView({
    id: 'orders',
    search: { label: t('orders.search'), placeholder: t('orders.search_ph'),
      text: (o) => [o.subject, o.customer_name, o.customer_number, o.city, o.invoice_number, String(o.number)] },
    chips: { label: t('orders.filter_status'), all: t('orders.all'), options: STATUSES.map((s) => [s, statusLabel(s)]), value: (o) => o.status },
    // All the orders of one customer: the pull-down offers the customers that have orders here, with their number (two can share a name).
    filters: [{ key: 'customer', label: t('orders.customer'), all: t('orders.all_customers'), value: (o) => o.customer_id, name: (id) => customers.get(id) || id }],
    // Orders can be chosen, several at once, to give them to another customer. One that has an invoice cannot be: that invoice went out for the customer it was made for.
    select: { id: (o) => o.id, can: (o) => !o.invoice_number, cannot: t('orders.locked_by_invoice'), label: (o) => titleOf(o),
      actions: [{ icon: 'account-group', label: t('orders.assign'), primary: true, run: (rows) => assignDialog(rows) }] },
    sorts: [
      { key: 'date', label: t('orders.date'), value: (o) => `${o.order_date || ''} ${String(o.number).padStart(9, '0')}`, desc: true },
      { key: 'number', label: t('sort.number'), value: (o) => Number(o.number), desc: true },
      { key: 'subject', label: t('orders.subject'), value: (o) => titleOf(o) },
      { key: 'customer', label: t('orders.customer'), value: (o) => o.customer_name },
      { key: 'status', label: t('orders.status'), value: (o) => STATUSES.indexOf(o.status) },
      { key: 'delivery', label: t('orders.delivery'), value: (o) => o.delivery_date || '9999' },
      { key: 'total', label: t('orders.total'), value: (o) => Number(o.total), desc: true }],
    tie: (o) => o.customer_name,
    href,
    columns: [
      { label: t('orders.subject'), sort: 'subject', cls: 'main', cell: (o) => h('div', {}, h('a', { class: 'cell-title', href: href(o) }, titleOf(o)),
        h('div', { class: 'cell-sub muted' }, [o.customer_name, numberOf(o), o.city].filter(Boolean).join(' · ')), filamentFlag(o)) },
      { label: t('orders.date'), sort: 'date', cls: 'nowrap', cell: (o) => dateFmt(o.order_date) },
      { label: t('orders.status'), sort: 'status', cell: (o) => statusSelect(o) },
      { label: t('orders.lines'), cls: 'num', wide: true, cell: (o) => String(o.line_count) },
      { label: t('orders.delivery'), sort: 'delivery', cls: 'nowrap', wide: true, cell: (o) => (o.delivery_date ? dateFmt(o.delivery_date) : '—') },
      { label: t('orders.invoice'), wide: true, cell: (o) => o.invoice_number || '—' },
      { label: t('orders.total'), sort: 'total', cls: 'num strong', cell: (o) => eur(o.total) }],
    tile: (o) => h('article', { class: 'glass card item' },
      h('div', { class: 'item-head' },
        h('div', {}, h('h3', {}, h('a', { href: href(o) }, titleOf(o))),
          h('p', { class: 'item-customer' }, o.customer_name),
          h('p', { class: 'muted item-meta' }, [numberOf(o), dateFmt(o.order_date)].filter(Boolean).join(' · '))),
        statusSelect(o)),
      filamentFlag(o),
      h('dl', { class: 'stats' },
        stat(t('orders.total'), eur(o.total)), stat(t('orders.lines'), String(o.line_count)),
        o.delivery_date ? stat(t('orders.delivery'), dateFmt(o.delivery_date)) : null,
        o.invoice_number ? stat(t('orders.invoice'), o.invoice_number) : null)),
    empty: `${t('orders.none_yet')} ${t('common.add_first')}`, noMatch: t('orders.no_match'),
  });

  // Everything is fetched once; searching, filtering and sorting happen here while typing.
  async function load() {
    try {
      const orders = await api('GET', '/api/orders');
      customers = new Map();
      for (const o of orders) if (!customers.has(o.customer_id)) customers.set(o.customer_id, [o.customer_name, o.customer_number].filter(Boolean).join(' · '));
      view.setItems(orders);
    } catch (e) { toast(e.message, 'error'); }
  }

  // Gives the chosen orders to another customer: pick one (the same list as in an order), see what will happen, and do it; the server does all of them or none.
  // Resolves true when it was done, so that the choice is let go.
  function assignDialog(rows) {
    return new Promise((resolve) => {
      let done = false;
      const body = h('div', { class: 'stack' });
      const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, body));
      const failure = h('p', { class: 'error', role: 'alert', hidden: true });
      const n = rows.length;

      function review(c) {
        failure.hidden = true;
        const go = h('button', { class: 'btn primary', type: 'button', id: 'assign-do', onclick: async () => {
          go.disabled = true;
          try {
            const res = await api('POST', '/api/orders/assign-customer', { order_ids: rows.map((o) => o.id), customer_id: c.id });
            done = true;
            toast(res.updated ? t('orders.assigned', { n: res.updated, name: c.name }) : t('orders.assigned_none', { name: c.name }));
            dialog.close();
            load();
          } catch (e) { failure.textContent = e.message; failure.hidden = false; go.disabled = false; }
        } }, t('orders.assign_do'));
        body.replaceChildren(h('h2', {}, t('orders.assign_title')),
          h('p', {}, t('orders.assign_confirm', { n, name: c.name })),
          h('p', { class: 'muted' }, [c.number, c.city].filter(Boolean).join(' · ')),
          failure,
          h('div', { class: 'row end' }, h('button', { class: 'btn', type: 'button', onclick: pick }, t('customers.back_to_list')), go));
      }

      async function pick() {
        let all;
        try { all = await api('GET', '/api/customers'); } catch (e) { toast(e.message, 'error'); dialog.close(); return; }
        const list = customerPicker(all, review);
        body.replaceChildren(h('h2', {}, t('orders.assign_title')), h('p', { class: 'muted' }, t('orders.assign_hint', { n })), list.field, list.results,
          h('div', { class: 'row end' }, h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel'))));
        list.input.focus();
      }

      dialog.addEventListener('close', () => { dialog.remove(); resolve(done); });
      document.body.append(dialog);
      dialog.showModal();
      pick();
    });
  }

  load();
  if (customer) view.setFilter('customer', customer);
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, t('nav.orders'))),
      h('a', { class: 'btn primary', href: '#/bestellingen/nieuw' }, icon('plus'), h('span', {}, t('orders.new')))),
    h('p', { class: 'muted page-intro' }, t('orders.intro')),
    view.el);
}

// --- editor ---------------------------------------------------------------------

const str = (v) => (v == null ? '' : String(v));
const fmtPct = (v) => Number(v).toLocaleString(document.documentElement.lang || undefined, { maximumFractionDigits: 2 });

function fromSaved(order) {
  return {
    id: order.id, number: order.number, customer_id: order.customer_id, status: order.status, price_rounding: order.price_rounding || 'none', order_date: order.order_date, delivery_date: str(order.delivery_date),
    customer_name: order.customer_name, customer_number: order.customer_number, subject: order.subject, address: order.address, postal_code: order.postal_code, city: order.city, country: order.country,
    email: order.email, phone: order.phone, notes: order.notes, invoice_number: order.invoice_number, invoice_date: str(order.invoice_date), has_invoice_pdf: !!order.has_invoice_pdf,
    lines: order.lines.map((l) => ({ project_id: l.project_id, project_number: l.project_number, description: l.description,
      quantity: str(l.quantity), unit_price: str(l.unit_price), vat_pct: str(Number(l.vat_pct)), optional: !!l.optional, packaging: !!l.packaging,
      cover_image_id: l.cover_image_id || null,
      // a line made from a model starts from the model's selling price (`base_price`, with the rounding the model had) and its margin is an extra on top of that
      base_price: l.base_price == null ? null : str(l.base_price), price_rounding: l.price_rounding || null,
      // a line made from a calculation has a cost price and its own margin; the server works out its price
      cost_price: l.cost_price == null ? null : str(l.cost_price), margin_pct: l.margin_pct == null ? '' : str(Number(l.margin_pct)) })),
  };
}

export function orderEditorView(id, navigate, ctx = { prefs: {} }) {
  const root = h('section', { class: 'page' }, h('p', { class: 'muted' }, t('common.loading')));
  (id ? api('GET', `/api/orders/${id}`) : Promise.resolve(null))
    .then((order) => root.replaceChildren(buildEditor(order, navigate, ctx)))
    .catch((e) => root.replaceChildren(h('p', { class: 'error', role: 'alert' }, e.message)));
  return root;
}

function buildEditor(order, navigate, ctx) {
  const defaultVat = str(ctx.prefs.vat_pct ?? '21');
  const state = order ? fromSaved(order) : {
    id: null, number: null, customer_id: null, status: 'nieuw', price_rounding: 'none', order_date: today(), delivery_date: '', customer_name: '', customer_number: '', subject: '', address: '', postal_code: '', city: '',
    country: '', email: '', phone: '', notes: '', invoice_number: null, invoice_date: '', has_invoice_pdf: false, lines: [],
  };
  let result = null;
  let dirty = false;
  let timer = null;
  const totals = h('dl', { class: 'totals' });
  const calcError = h('p', { class: 'error', role: 'alert', hidden: true });
  const linesBox = h('div', { class: 'lines' });
  const invoiceBox = h('div', { class: 'stack' });
  const labelBox = h('div', { class: 'stack' });
  const customerBox = h('div', { class: 'stack' });
  const statusBox = h('div', { class: 'chips', role: 'group', 'aria-label': t('orders.status') });
  const filamentBox = h('div', { class: 'stack' });
  const filamentCard = h('div', { class: 'glass card stack', hidden: true }, h('h2', {}, t('orders.filament_title')), filamentBox);
  let filamentSeq = 0;
  const lineTotals = [];
  const lineUnits = [];
  const marginHints = [];

  const payload = () => ({
    customer_id: state.customer_id, status: state.status, price_rounding: state.price_rounding, order_date: state.order_date, delivery_date: state.delivery_date || null,
    subject: state.subject.trim(), notes: state.notes, invoice_date: state.invoice_date || null,
    lines: state.lines.map(linePayload),
  });
  function linePayload(l) {
    return { project_id: l.project_id, description: l.description, quantity: parseNum(l.quantity), vat_pct: parseNum(l.vat_pct), optional: !!l.optional, packaging: !!l.packaging,
      ...(l.cost_price == null ? { unit_price: parseNum(l.unit_price) } : { cost_price: parseNum(l.cost_price), margin_pct: parseNum(l.margin_pct) }),
      ...(l.base_price == null ? {} : { base_price: parseNum(l.base_price), price_rounding: l.price_rounding || 'none' }) };
  }

  // The prices and totals are the server's: it works out the price of a calculated line, takes the VAT out per rate, and what is shown here
  // is what an invoice will say.
  async function recalc() {
    try {
      const { lines, price_rounding } = payload();
      result = await api('POST', '/api/orders/totals', { lines, price_rounding });
      calcError.hidden = true;
      renderTotals();
      checkFilament();
    } catch (e) { calcError.textContent = e.message; calcError.hidden = false; }
  }
  // The filament the models of this order take, next to what is on the shelf and what other open orders already hold. The server says it
  // (`reservations.check`); an order that is sent or done holds nothing any more, and the card says so.
  async function checkFilament() {
    const seq = ++filamentSeq;
    const modelled = state.lines.filter((l) => l.project_id && !l.optional && !l.packaging);
    if (!modelled.length) { filamentCard.hidden = true; return; }
    try {
      const found = await api('POST', '/api/orders/filament-check', {
        lines: state.lines.map((l) => ({ project_id: l.project_id, quantity: parseNum(l.quantity), optional: !!l.optional, packaging: !!l.packaging })),
        status: state.status, order_id: state.id });
      if (seq !== filamentSeq) return;                              // a newer answer is on its way
      renderFilament(found);
    } catch { if (seq === filamentSeq) filamentCard.hidden = true; }
  }
  function renderFilament(found) {
    filamentCard.hidden = !found.kinds.length;
    const rows = found.kinds.map((k) => {
      const free = Number(k.remaining_g) - Number(k.reserved_others_g);
      const short = Number(k.short_g) > 0;
      return h('li', { class: short ? 'filament-row short' : 'filament-row' },
        spoolIcon(colourOf(k), 28),
        h('div', {}, h('strong', {}, [spoolName(k, ' · '), k.material].filter(Boolean).join(' · ')),
          h('p', { class: 'muted' }, found.reserving ? t('orders.filament_need', { need: fmt(k.need_g, 0), free: fmt(Math.max(free, 0), 0) }) : `${fmt(k.need_g, 0)} g`),
          found.reserving ? h('p', { class: 'hint' }, t('orders.filament_detail', { left: fmt(k.remaining_g, 0), others: fmt(k.reserved_others_g, 0) })) : null,
          short ? h('p', { class: 'error' }, t('orders.filament_missing', { short: fmt(k.short_g, 0) })) : null));
    });
    fill(filamentBox,
      !found.reserving ? h('p', { class: 'hint' }, t('orders.filament_released', { status: statusLabel(state.status).toLowerCase() }))
        : found.short ? h('div', { class: 'notice warn', role: 'alert' }, h('strong', {}, t('orders.filament_short_title')))
          : h('p', { class: 'hint', role: 'status' }, t('orders.filament_ok')),
      h('ul', { class: 'filament-list' }, rows),
      found.reserving ? h('p', { class: 'hint' }, t('orders.filament_hint')) : null);
  }
  function touch() {
    dirty = true;
    setDirty(true);
    clearTimeout(timer);
    timer = setTimeout(recalc, 200);
  }
  const bind = (key) => (v) => { state[key] = v; touch(); };
  const textInput = (key, attrs = {}) => h('input', { type: 'text', value: state[key], ...attrs, oninput: (e) => bind(key)(e.target.value) });
  const dateInput = (key, attrs = {}) => h('input', { type: 'date', value: state[key], ...attrs, onchange: (e) => bind(key)(e.target.value) });

  function renderTotals() {
    if (!result) return;
    const row = (label, value, cls = '') => [h('dt', { class: cls }, label), h('dd', { class: cls }, eur(value))];
    const vatRows = result.vat.filter((r) => Number(r.vat) > 0);
    totals.replaceChildren(
      ...(vatRows.length ? [...row(t('orders.total_excl'), result.total_excl), ...vatRows.flatMap((r) => row(t('orders.vat_row', { pct: r.pct }), r.vat))] : []),
      ...row(vatRows.length ? t('orders.total_incl') : t('orders.total'), result.total, 'grand'));
    lineTotals.forEach((el, i) => { if (el && result.line_totals[i] != null) el.textContent = eur(result.line_totals[i]); });
    lineUnits.forEach((el, i) => { if (el && result.priced_lines[i]) el.textContent = eur(result.priced_lines[i].unit_price); });
    marginHints.forEach((el, i) => {                                 // rounding can lift the margin above the one typed
      const effective = result.priced_lines[i]?.margin_pct_effective;
      const lifted = el && effective != null && Number(effective) > parseNum(state.lines[i].margin_pct) + 0.004;
      if (el) { el.textContent = lifted ? t('orders.margin_lifted', { to: fmtPct(effective) }) : ''; el.hidden = !lifted; }
    });
  }

  // --- lines -------------------------------------------------------------------------
  const removeBtn = (label, onClick) => h('button', { class: 'btn small danger icon-only', type: 'button', 'aria-label': label, onclick: onClick }, icon('trash'));

  function drawLines() {
    lineTotals.length = lineUnits.length = marginHints.length = 0;
    if (!state.lines.length) { linesBox.replaceChildren(h('p', { class: 'muted' }, t('orders.no_lines'))); renderTotals(); return; }
    linesBox.replaceChildren(...state.lines.map((l, i) => {
      const input = h('input', { type: 'text', value: l.description, maxlength: 200, oninput: (e) => { l.description = e.target.value; touch(); } });
      const inputId = `ol${Math.random().toString(36).slice(2, 9)}`;
      input.id = inputId;
      const badge = l.project_number
        ? (l.project_id ? h('a', { class: 'badge', href: `#/berekeningen/${l.project_id}`, title: t('orders.open_calc') }, `#${l.project_number}`)
          : h('span', { class: 'badge muted', title: t('orders.calc_gone') }, `#${l.project_number}`))
        : null;
      const total = h('output', { class: 'cost' }, '—');
      lineTotals[i] = total;
      const calculated = l.cost_price != null;
      const unit = h('output', { class: 'cost' }, '—');
      const hint = h('p', { class: 'hint private', role: 'status', hidden: true });
      const fromModel = l.base_price != null;                           // starts from the model's selling price; its margin is an extra on top
      const modelPrice = fromModel ? h('p', { class: 'hint' }, t('orders.model_price', { price: eur(l.base_price) })) : null;
      if (calculated) { lineUnits[i] = unit; marginHints[i] = hint; }
      const optional = l.packaging ? h('p', { class: 'hint' }, t('orders.packaging_line'))                       // packaging is never on the invoice, so it is not optional either
        : h('label', { class: 'check' },
          h('input', { type: 'checkbox', checked: !!l.optional, onchange: (e) => { l.optional = e.target.checked; touch(); } }), t('orders.optional'));
      // the model's own line shows the cover of the calculation (a picture exists only where the product images are on); an accessory or a loose line has none
      // tapping it shows the picture large in a pop-up (the same one the product pictures open in); it is a button, so a keyboard and a screen reader reach it
      const picture = ctx.aiImages && l.project_id && !l.optional && l.cover_image_id
        ? h('button', { class: 'cover-open', type: 'button', title: t('orders.picture_open'), 'aria-label': t('orders.picture_open_of', { name: l.description || `#${l.project_number}` }),
          onclick: () => openLightbox([{ src: coverFileUrl(l.cover_image_id), alt: l.description, title: l.description }]) }, cover(l.cover_image_id))
        : null;
      // the model's own line (not one of its accessories) can be brought up to date with the calculation it was made from
      const sync = l.project_id && !l.optional
        ? h('button', { class: 'btn small icon-only sync-line', type: 'button', title: t('orders.sync'), 'aria-label': t('orders.sync_line', { name: l.description || `#${l.project_number}` }),
          onclick: (e) => syncLine(l, e.currentTarget) }, icon('sync'))
        : null;
      return h('div', { class: `line order${calculated ? ' calc' : ''}` },
        h('div', { class: 'field' }, h('label', { for: inputId }, t('orders.description'), ' ', badge),
          picture || sync ? h('div', { class: 'input-row' }, picture, input, sync) : input, optional),
        field(t('orders.quantity'), numberInput(l.quantity, (v) => { l.quantity = v; touch(); }, { inputmode: 'numeric' })),
        calculated ? field(t(fromModel ? 'orders.margin_extra' : 'orders.margin'), numberInput(l.margin_pct, (v) => { l.margin_pct = v; touch(); }, { class: 'private', ...(fromModel ? { title: t('orders.margin_extra_title') } : {}) })) : null,
        calculated ? h('div', { class: 'field cost-field' }, h('span', { class: 'lbl' }, t('orders.unit_price_calc')), unit)
          : field(t('orders.unit_price'), numberInput(l.unit_price, (v) => { l.unit_price = v; touch(); })),
        field(t('orders.vat'), numberInput(l.vat_pct, (v) => { l.vat_pct = v; touch(); }, { list: 'order-vat-presets' })),
        h('div', { class: 'field cost-field' }, h('span', { class: 'lbl' }, t('orders.line_total')), total),
        removeBtn(t('orders.remove_line'), () => { state.lines.splice(i, 1); touch(); drawLines(); }),
        calculated ? hint : null,
        modelPrice);
    }));
    renderTotals();
  }

  // The lines a calculation adds to an order: the model itself, and the accessories of the calculation (cables, chargers) as lines of their
  // own that the invoice lists apart, because the product works without them. The accessories are priced at what they cost; the model's line
  // keeps the rest of the cost price (for the sales overview) and starts from the model's selling price (`modelLinesOf` asks the server for it).
  const UNIT_SHORT = { stuks: t('unit.pieces'), m: 'm', g: 'g' };
  function modelLines(p) {
    const extras = (p.totals.parts || []).filter((x) => x.group === 'oplader' && Number(x.cost) > 0);
    const modelCost = Math.round((Number(p.totals.cost_price) - Number(p.totals.subtotals.charger || 0)) * 100) / 100;
    const model = { project_id: p.id, project_number: p.number, description: p.name, quantity: '1', unit_price: '', optional: false,
      cost_price: String(extras.length ? modelCost : p.totals.cost_price), margin_pct: '0', vat_pct: str(Number(p.vat_pct)) };      // 0: the extra margin on top of the model's price
    return [model, ...extras.map((x) => {
      const qty = Number(x.quantity), price = Number(x.unit_price);
      const whole = x.unit === 'stuks' && Number.isInteger(qty) && qty >= 1 && qty <= 100000 && Math.round(price * 100) / 100 === price;
      return { project_id: p.id, project_number: p.number, optional: true, quantity: whole ? String(qty) : '1', unit_price: '',
        description: whole ? x.label : `${x.label} (${fmt(qty)} ${UNIT_SHORT[x.unit] || x.unit})`,
        cost_price: String(whole ? price : x.cost), margin_pct: '0', vat_pct: str(Number(p.vat_pct)) };
    })];
  }

  // The lines to add for one calculation, the model's line with its price: the server says what the model sells for (with the rounding the model
  // has) less what the accessory lines cost, so that the lines together are the model's selling price. Nothing is added up here.
  async function modelLinesOf(projectId) {
    const p = await api('GET', `/api/projects/${projectId}`);
    const lines = modelLines(p);
    const basis = await api('POST', '/api/orders/model-basis', { project_id: p.id, accessories: lines.slice(1).map(linePayload) });
    lines[0].base_price = basis.base_price;
    lines[0].price_rounding = basis.price_rounding;
    return { lines, margin: str(Number(p.margin_pct)) };
  }

  // The model's line keeps the cost price its calculation had when it was added; this fetches the calculation as it is now and takes its cost
  // price again (the extra margin, VAT and quantity of the line are the order's own and stay); a line that starts from the model's selling price
  // takes that price and its rounding again too. A line from before that price was kept stays priced from its cost price, margin and the
  // rounding of the order, as it was: it gets the calculation's cost price (and its margin, when it had none). Saving the order stores it.
  async function syncLine(l, button) {
    button.disabled = true;
    try {
      const { lines, margin } = await modelLinesOf(l.project_id);
      const fresh = lines[0];
      if (l.base_price != null) {
        if (Number(l.cost_price) === Number(fresh.cost_price) && Number(l.base_price) === Number(fresh.base_price) && (l.price_rounding || 'none') === fresh.price_rounding) { toast(t('orders.sync_current')); return; }
        Object.assign(l, { cost_price: fresh.cost_price, base_price: fresh.base_price, price_rounding: fresh.price_rounding });
        touch(); drawLines();
        toast(t('orders.sync_done_model', { price: eur(fresh.base_price) }));
        return;
      }
      if (l.cost_price != null && Number(l.cost_price) === Number(fresh.cost_price)) { toast(t('orders.sync_current')); return; }
      l.cost_price = fresh.cost_price;
      if (!String(l.margin_pct ?? '').trim()) l.margin_pct = margin;
      touch(); drawLines();
      toast(t('orders.sync_done', { cost: eur(fresh.cost_price) }));
    } catch (e) { toast(e.message, 'error'); } finally { button.disabled = false; }
  }

  // Loose items from a price list, without a calculation: an accessory (cable, charger) is an optional line, which the invoice lists apart
  // from the products; packaging material (box, tape, filler) is a line that counts in the total of the order but is never listed on the invoice (`packaging`,
  // the server leaves it out). Both are at cost price
  // with margin 0. Choosing the same one again adds one more of it.
  const CATALOGUES = {
    accessory: { path: '/api/accessories', optional: true, per: 'orders.accessory_per', title: 'orders.add_accessory', hint: 'orders.add_accessory_hint',
      search: 'orders.search_accessories', placeholder: 'orders.search_accessories_ph', none: 'orders.no_accessories', noMatch: 'orders.no_accessories_match' },
    packaging: { path: '/api/packaging', optional: false, packaging: true, per: 'orders.packaging_per', title: 'orders.add_packaging', hint: 'orders.add_packaging_hint',
      search: 'orders.search_packaging', placeholder: 'orders.search_packaging_ph', none: 'orders.no_packaging', noMatch: 'orders.no_packaging_match' },
  };
  async function pickItem(kind) {
    const c = CATALOGUES[kind];
    let items;
    try { items = (await api('GET', c.path)).filter((a) => !a.archived); } catch (e) { toast(e.message, 'error'); return; }
    const results = h('ul', { class: 'plain-list picker', 'aria-live': 'polite' });
    const added = new Map();
    const search = h('input', { type: 'text', autocomplete: 'off', placeholder: t(c.placeholder), 'aria-label': t(c.search) });
    const per = (a) => (a.unit === 'stuks' || !a.unit ? '' : ` / ${a.unit === 'g' ? 'kg' : a.unit}`);
    const describe = (a) => (a.unit === 'stuks' || !a.unit ? a.name : t(c.per, { name: a.name, unit: a.unit === 'g' ? 'kg' : a.unit }));
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const found = items.filter((a) => !q || a.name.toLowerCase().includes(q));
      results.replaceChildren(...(found.length ? found.map((a) => h('li', {}, h('button', { class: 'btn picker-item', type: 'button', onclick: () => {
        const existing = state.lines.find((l) => !l.project_id && !!l.optional === c.optional && !!l.packaging === !!c.packaging && l.description === describe(a) && Number(l.cost_price) === Number(a.price));
        if (existing) existing.quantity = String(Math.floor(parseNum(existing.quantity)) + 1);
        else state.lines.push({ project_id: null, project_number: null, optional: c.optional, packaging: !!c.packaging, description: describe(a), quantity: '1', unit_price: '', cost_price: str(Number(a.price)),
          margin_pct: '0', vat_pct: defaultVat });
        added.set(a.id, (added.get(a.id) || 0) + 1);
        touch(); drawLines(); draw();
      } }, h('span', { class: 'grow' }, a.name), added.has(a.id) ? h('span', { class: 'muted' }, `+${added.get(a.id)}`) : null,
      h('strong', {}, `${eur(a.price)}${per(a)}`)))) : [h('li', { class: 'muted' }, items.length ? t(c.noMatch) : t(c.none))]));
    };
    search.addEventListener('input', draw);
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
      h('h2', {}, t(c.title)), h('p', { class: 'muted' }, t(c.hint)),
      field(t(c.search), search), results,
      h('div', { class: 'row end' }, h('button', { class: 'btn primary', type: 'button', onclick: () => dialog.requestClose() }, t('orders.done')))));
    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog);
    draw();
    dialog.showModal();
    search.focus();
  }

  // The calculations to choose from: find one by its number or part of its name; picking adds a line (again: one more of it).
  async function pickModel() {
    let projects;
    try { projects = await api('GET', '/api/projects'); } catch (e) { toast(e.message, 'error'); return; }
    const results = h('ul', { class: 'plain-list picker', 'aria-live': 'polite' });
    const added = new Map();
    const search = h('input', { type: 'text', autocomplete: 'off', placeholder: t('orders.search_models_ph'), 'aria-label': t('orders.search_models') });
    const matches = (p, q) => !q || String(p.number) === q.replace(/^#/, '') || `#${p.number}`.startsWith(q) || p.name.toLowerCase().includes(q.toLowerCase());
    const draw = () => {
      const found = projects.filter((p) => matches(p, search.value.trim()));
      results.replaceChildren(...(found.length ? found.map((p) => h('li', {}, h('button', { class: 'btn picker-item', type: 'button', onclick: async (event) => {
        const existing = state.lines.find((l) => l.project_id === p.id && !l.optional);
        if (existing) existing.quantity = String(Math.floor(parseNum(existing.quantity)) + 1);
        else {
          // The list holds a model's prices, not its lines; the accessories that become lines of their own are in the model itself.
          const button = event.currentTarget;
          button.disabled = true;
          try {
            const { lines } = await modelLinesOf(p.id);
            lines[0].cover_image_id = p.cover_image_id || null;                // the list has it, the model itself does not
            state.lines.push(...lines);
          } catch (e) { toast(e.message, 'error'); button.disabled = false; return; }
        }
        added.set(p.id, (added.get(p.id) || 0) + 1);
        touch(); drawLines(); draw();
      } }, ctx.aiImages && p.cover_image_id ? cover(p.cover_image_id) : null, h('span', { class: 'badge' }, `#${p.number}`), h('span', { class: 'grow' }, p.name),
      added.has(p.id) ? h('span', { class: 'muted' }, `+${added.get(p.id)}`) : null,
      h('strong', {}, eur(p.totals.sell_price_incl_vat))))) : [h('li', { class: 'muted' }, projects.length ? t('orders.no_models_match') : t('orders.no_models'))]));
    };
    search.addEventListener('input', draw);
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
      h('h2', {}, t('orders.add_model')), h('p', { class: 'muted' }, t('orders.add_model_hint')),
      field(t('orders.search_models'), search), results,
      h('div', { class: 'row end' }, h('button', { class: 'btn primary', type: 'button', onclick: () => dialog.requestClose() }, t('orders.done')))));
    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog);
    draw();
    dialog.showModal();
    search.focus();
  }

  // --- customer ----------------------------------------------------------------------
  // An order has a customer: chosen from the customers there are, or made on the spot. The details are shown here; they live with the customer.
  function drawCustomer() {
    const parts = [];
    if (state.customer_id) {
      parts.push(h('div', { class: 'customer-block' },
        h('p', {}, h('strong', {}, state.customer_name), ' ', h('span', { class: 'badge' }, t('customers.number_n', { number: state.customer_number }))),
        ...customerLines(state).map((line) => h('p', { class: 'muted' }, line))));
    } else parts.push(h('p', { class: 'muted' }, t('customers.none_selected')));
    parts.push(h('div', { class: 'row' },
      h('button', { class: `btn small${state.customer_id ? '' : ' primary'}`, type: 'button', id: 'pick-customer', onclick: pickCustomer },
        state.customer_id ? t('customers.change') : t('customers.pick')),
      state.customer_id ? h('a', { class: 'btn small', href: `#/klanten/${state.customer_id}` }, t('customers.edit')) : null));
    fill(customerBox, ...parts);
  }

  function chooseCustomer(c) {
    Object.assign(state, { customer_id: c.id, customer_name: c.name, customer_number: c.number, address: c.address, postal_code: c.postal_code,
      city: c.city, country: c.country, email: c.email, phone: c.phone });
    touch();
    drawCustomer();
  }

  async function pickCustomer() {
    let customers;
    try { customers = await api('GET', '/api/customers'); } catch (e) { toast(e.message, 'error'); return; }
    const body = h('div', { class: 'stack' });
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, body));
    const done = (c) => { chooseCustomer(c); dialog.requestClose(); };

    function drawCreate() {
      const draft = emptyCustomer();
      const failure = h('p', { class: 'error', role: 'alert', hidden: true });
      body.replaceChildren(h('h2', {}, t('customers.create')), ...customerFields(draft), failure,
        h('div', { class: 'row end' },
          customers.length ? h('button', { class: 'btn', type: 'button', onclick: drawPick }, t('customers.back_to_list')) : h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
          h('button', { class: 'btn primary', type: 'button', id: 'create-customer', onclick: async () => {
            if (!draft.name.trim()) { failure.textContent = t('customers.name_required'); failure.hidden = false; return; }
            try {
              done(await api('POST', '/api/customers', { ...draft, number: draft.number.trim(), name: draft.name.trim(), email: draft.email.trim() }));
            } catch (e) { failure.textContent = e.message; failure.hidden = false; }
          } }, t('customers.create_and_choose'))));
    }

    function drawPick() {
      const list = customerPicker(customers, done);
      body.replaceChildren(h('h2', {}, t('customers.pick')), h('p', { class: 'muted' }, t('customers.pick_hint')), list.field, list.results,
        h('div', { class: 'row end' },
          h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
          h('button', { class: 'btn primary', type: 'button', id: 'new-customer', onclick: drawCreate }, icon('plus'), h('span', {}, t('customers.create')))));
      list.input.focus();
    }

    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog);
    (customers.length ? drawPick : drawCreate)();
    dialog.showModal();
  }

  // --- status, invoice, save -------------------------------------------------------------
  function drawStatus() {
    statusBox.replaceChildren(...STATUSES.map((s) => h('button', { type: 'button', class: 'seg', 'aria-pressed': String(state.status === s), onclick: async () => {
      if (state.status === s) return;
      state.status = s;
      if (state.id) {                                  // a saved order changes stage at once; a new one waits for Save
        try { await api('PATCH', `/api/orders/${state.id}/status`, { status: s }); toast(t('orders.status_set', { status: statusLabel(s) })); } catch (e) { toast(e.message, 'error'); }
      } else touch();
      checkFilament();
      drawStatus();
      statusSelect.value = s;
    } }, statusLabel(s))));
  }
  const statusSelect = h('select', { onchange: (e) => { state.status = e.target.value; touch(); drawStatus(); } },
    STATUSES.map((s) => h('option', { value: s, selected: s === state.status }, statusLabel(s))));

  async function save() {
    if (!state.customer_id) { toast(t('customers.choose_one'), 'error'); return null; }
    try {
      const body = payload();
      const saved = state.id ? await api('PUT', `/api/orders/${state.id}`, body) : await api('POST', '/api/orders', body);
      dirty = false;
      setDirty(false);
      toast(t('common.saved'));
      if (!state.id) { navigate(`#/bestellingen/${saved.id}`); return saved; }
      state.invoice_number = saved.invoice_number;
      state.invoice_date = str(saved.invoice_date);
      drawInvoice();
      return saved;
    } catch (e) { toast(e.message, 'error'); return null; }
  }

  async function makeInvoice() {
    if (!state.id) return;
    if (dirty && !(await save())) return;               // the invoice says what the order says: save what is on the screen first
    try {
      const { blob, name } = await downloadFile(`/api/orders/${state.id}/invoice`, { method: 'POST' });
      saveBlob(blob, name);
      const fresh = await api('GET', `/api/orders/${state.id}`);
      state.invoice_number = fresh.invoice_number;
      state.invoice_date = str(fresh.invoice_date);
      state.has_invoice_pdf = !!fresh.has_invoice_pdf;
      drawInvoice();
      toast(t('orders.invoice_made', { name }));
    } catch (e) { toast(e.message, 'error'); }
  }

  async function downloadInvoice() {
    try {
      const { blob, name } = await downloadFile(`/api/orders/${state.id}/invoice`);       // the PDF as it was kept
      saveBlob(blob, name);
    } catch (e) { toast(e.message, 'error'); }
  }

  function drawInvoice() {
    const parts = [];
    if (state.invoice_number) {
      parts.push(h('p', { class: 'status-line' }, t('orders.invoice_number', { number: state.invoice_number })),
        field(t('orders.invoice_date'), dateInput('invoice_date'), t('orders.invoice_date_hint')));
    } else parts.push(h('p', { class: 'muted' }, state.id ? t('orders.no_invoice') : t('orders.save_first')));
    parts.push(h('button', { class: 'btn primary', type: 'button', disabled: !state.id || !state.lines.length, onclick: makeInvoice, id: 'make-invoice' },
      icon('clipboard'), h('span', {}, state.invoice_number ? t('orders.invoice_again') : t('orders.make_invoice'))));
    if (state.has_invoice_pdf) {
      parts.push(h('button', { class: 'btn', type: 'button', onclick: downloadInvoice, id: 'download-invoice' }, t('orders.download_invoice')),
        h('p', { class: 'hint' }, t('orders.invoice_kept_hint')));
    }
    fill(invoiceBox, ...parts);
  }

  // --- label ------------------------------------------------------------------------------
  // A PDF with one label of this order, on a sheet of the template that is picked. The sheet and its places have the server's names (`/api/labels/options`,
  // asked for only when there is a template); the choice is remembered in this browser, and once a label is made the place moves on to the next one on the
  // sheet, so a half-used sheet can be used up.
  const labelChoice = (() => {
    let kept = {};
    try { kept = JSON.parse(localStorage.getItem('pp-label') || '{}') || {}; } catch { /* private mode: nothing is remembered */ }
    return { template: String(kept.template || ''), slot: Number(kept.slot) || 1 };
  })();
  let labelOptions = null;
  const labelTemplates = () => ctx.prefs.label_templates || [];                    // read when it is needed, never copied
  const rememberLabel = () => { try { localStorage.setItem('pp-label', JSON.stringify(labelChoice)); } catch { /* not kept */ } };
  const slotsOf = (template) => labelOptions.formats.find((f) => f.id === template.format)?.slots || [{ id: 1, name: '1' }];

  function drawLabel() {
    const list = labelTemplates();
    if (!list.length) {
      fill(labelBox, h('p', { class: 'muted' }, t('orders.label_none')), h('div', { class: 'row' }, h('a', { class: 'btn small', href: '#/instellingen/labels' }, t('orders.label_settings'))));
      return;
    }
    if (!labelOptions) { fill(labelBox, h('p', { class: 'muted' }, t('common.loading'))); return; }
    const template = list.find((x) => x.id === labelChoice.template) || list[0];
    labelChoice.template = template.id;
    const slots = slotsOf(template);
    if (!slots.some((s) => s.id === labelChoice.slot)) labelChoice.slot = slots[0].id;
    fill(labelBox,
      field(t('orders.label_template'), h('select', { onchange: (e) => { labelChoice.template = e.target.value; rememberLabel(); drawLabel(); } },
        list.map((x) => h('option', { value: x.id, selected: x.id === template.id }, x.name)))),
      slots.length > 1 ? field(t('orders.label_slot'), h('select', { onchange: (e) => { labelChoice.slot = Number(e.target.value); rememberLabel(); } },
        slots.map((s) => h('option', { value: String(s.id), selected: s.id === labelChoice.slot }, s.name))), t('orders.label_slot_hint')) : null,
      h('button', { class: 'btn', type: 'button', disabled: !state.id, onclick: makeLabel, id: 'make-label' }, icon('printer'), h('span', {}, t('orders.label_make'))),
      state.id ? null : h('p', { class: 'muted' }, t('orders.save_first')));
  }

  async function makeLabel() {
    if (!state.id) return;
    if (dirty && !(await save())) return;               // the label says what the order says: save what is on the screen first
    try {
      const { blob, name } = await downloadFile(`/api/orders/${state.id}/label?template=${encodeURIComponent(labelChoice.template)}&slot=${labelChoice.slot}`);
      saveBlob(blob, name);
      toast(t('orders.label_made', { name }));
      const used = labelTemplates().find((x) => x.id === labelChoice.template);
      if (used) {
        const slots = slotsOf(used);
        labelChoice.slot = slots[(slots.findIndex((s) => s.id === labelChoice.slot) + 1) % slots.length].id;      // the next label on the sheet
        rememberLabel();
      }
      drawLabel();
    } catch (e) { toast(e.message, 'error'); }
  }

  // A new order for the same customer with the same lines, from what is saved (so unsaved changes are asked for first); the server makes it new and without an invoice.
  async function duplicate() {
    if (dirty) { toast(t('orders.duplicate_save_first'), 'error'); return; }
    try {
      const copy = await api('POST', `/api/orders/${state.id}/duplicate`);
      toast(t('orders.duplicated', { n: copy.number }));
      navigate(`#/bestellingen/${copy.id}`);
    } catch (e) { toast(e.message, 'error'); }
  }

  drawStatus();
  const remove = async () => {
    if (!(await confirmDialog(t('orders.delete_confirm', { name: state.customer_name || t('orders.number', { n: state.number }) })))) return;
    try { await api('DELETE', `/api/orders/${state.id}`); dirty = false; setDirty(false); navigate('#/bestellingen'); } catch (e) { toast(e.message, 'error'); }
  };

  drawLines();
  drawInvoice();
  drawLabel();
  if (labelTemplates().length) {
    api('GET', '/api/labels/options').then((found) => { labelOptions = found; drawLabel(); })
      .catch((e) => fill(labelBox, h('p', { class: 'error', role: 'alert' }, e.message)));
  }
  drawCustomer();
  recalc();
  return h('div', { class: 'editor' },
    h('header', { class: 'page-head' },
      h('div', {}, backLink('#/bestellingen', t('nav.orders')),
        h('h1', {}, state.id ? t('orders.title_n', { n: state.number }) : t('orders.new'))),
      // As on every editor: what can be done with it in the title bar, always within reach.
      h('div', { class: 'row actions' },
        state.id ? h('div', { class: 'btn-group', role: 'group', 'aria-label': t('orders.actions') },
          headAction('copy', t('orders.duplicate'), duplicate, '', { id: 'duplicate-order' }), headAction('trash', t('common.delete'), remove, ' danger')) : null,
        headAction('save', t('common.save'), save, ' primary', { id: 'save-order' }))),
    h('div', { class: 'editor-grid' },
      h('div', { class: 'stack' },
        h('div', { class: 'glass card stack' }, h('h2', {}, t('orders.order')),
          h('div', { class: 'three' },
            field(t('orders.order_date'), dateInput('order_date', { required: true })),
            field(t('orders.delivery_date'), dateInput('delivery_date')),
            field(t('orders.status'), statusSelect)),
          field(t('orders.subject'), textInput('subject', { maxlength: 200, placeholder: t('orders.subject_ph') }), t('orders.subject_hint'))),
        h('div', { class: 'glass card stack' }, h('h2', {}, t('orders.customer')), customerBox),
        h('div', { class: 'glass card stack' }, h('h2', {}, t('orders.models')), h('p', { class: 'muted' }, t('orders.models_hint')),
          // an order has no rounding of its own any more (the model's price is rounded at the model); one that was made with one keeps it for the lines it priced
          state.price_rounding !== 'none' ? field(t('orders.rounding'), h('select', { onchange: (e) => { state.price_rounding = e.target.value; touch(); } },
            ROUNDINGS.map(([v, k]) => h('option', { value: v, selected: state.price_rounding === v }, t(k)))), `${t('orders.rounding_hint')} ${t('orders.rounding_old')}`) : null,
          linesBox,
          h('datalist', { id: 'order-vat-presets' }, ['0', '9', '21'].map((v) => h('option', { value: v }))),
          h('div', { class: 'row' },
            h('button', { class: 'btn primary small', type: 'button', id: 'add-model', onclick: pickModel }, icon('plus'), h('span', {}, t('orders.add_model'))),
            h('button', { class: 'btn small', type: 'button', id: 'add-accessory', onclick: () => pickItem('accessory') }, icon('plus'), h('span', {}, t('orders.add_accessory'))),
            h('button', { class: 'btn small', type: 'button', id: 'add-packaging', onclick: () => pickItem('packaging') }, icon('plus'), h('span', {}, t('orders.add_packaging'))),
            h('button', { class: 'btn small', type: 'button', onclick: () => {
              state.lines.push({ project_id: null, project_number: null, optional: false, description: '', quantity: '1', unit_price: '', cost_price: null, margin_pct: '', vat_pct: defaultVat });
              touch(); drawLines();
            } }, icon('plus'), h('span', {}, t('orders.add_free_line'))))),
        filamentCard,
        h('div', { class: 'glass card' }, field(t('orders.notes'), h('textarea', { rows: 3, maxlength: 2000, oninput: (e) => bind('notes')(e.target.value) }, state.notes || ''), t('orders.notes_hint')))),
      h('aside', { class: 'glass card summary', 'aria-label': t('orders.total') },
        h('h2', {}, t('orders.total')), totals, calcError,
        h('div', { class: 'stack' },
          h('h3', {}, t('orders.status')), statusBox,
          h('h3', {}, t('orders.invoice')), invoiceBox,
          h('h3', {}, t('orders.label')), labelBox))));
}
