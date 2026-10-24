import { api, downloadFile } from './api.js';
import { formatDate, t } from './i18n.js';
import { customerFields, customerLines, emptyCustomer } from './customers.js';
import { setDirty } from './updates.js';
import { ROUNDINGS, confirmDialog, enhanceDialog, eur, field, fill, fmt, h, icon, numberInput, parseNum, saveBlob, toast } from './ui.js';

// The stages of an order, in order. The words come from the language files.
export const STATUSES = ['nieuw', 'verwerkt', 'verstuurd', 'afgehandeld'];
const STATUS_KEYS = { nieuw: 'orders.status_nieuw', verwerkt: 'orders.status_verwerkt', verstuurd: 'orders.status_verstuurd', afgehandeld: 'orders.status_afgehandeld' };
const statusLabel = (s) => t(STATUS_KEYS[s]);
// A date without a time is a day on the calendar, not a moment in UTC: noon keeps it on that day in every time zone.
const dateFmt = (v) => (v ? formatDate(`${v}T12:00:00`, { day: 'numeric', month: 'short', year: 'numeric' }) : '—');
const today = () => new Date().toLocaleDateString('sv-SE');          // YYYY-MM-DD in the local time zone

const stat = (label, value) => h('div', {}, h('dt', {}, label), h('dd', {}, value));

// --- list -----------------------------------------------------------------------

export function orderListView() {
  let status = '';
  let query = '';
  let timer = null;
  const list = h('div', { class: 'cards' }, h('p', { class: 'muted' }, t('common.loading')));
  const chips = h('div', { class: 'chips', role: 'group', 'aria-label': t('orders.filter_status') });
  const search = h('input', { type: 'text', 'aria-label': t('orders.search'), placeholder: t('orders.search_ph'), autocomplete: 'off',
    oninput: (e) => { query = e.target.value.trim(); clearTimeout(timer); timer = setTimeout(load, 250); } });

  function drawChips() {
    chips.replaceChildren(...['', ...STATUSES].map((value) => h('button', { type: 'button', class: 'seg', 'aria-pressed': String(status === value),
      onclick: () => { status = value; drawChips(); load(); } }, value ? statusLabel(value) : t('orders.all'))));
  }

  // One select on the card sets the stage at once, without opening the order.
  function statusSelect(order) {
    return h('select', { class: 'status', 'aria-label': t('orders.status_of', { name: order.customer_name }),
      onchange: async (e) => {
        try {
          await api('PATCH', `/api/orders/${order.id}/status`, { status: e.target.value });
          toast(t('orders.status_set', { status: statusLabel(e.target.value) }));
          load();
        } catch (err) { toast(err.message, 'error'); load(); }
      } }, STATUSES.map((s) => h('option', { value: s, selected: s === order.status }, statusLabel(s))));
  }

  function draw(items) {
    if (!items.length) {
      list.replaceChildren(h('p', { class: 'empty glass card' }, status || query ? t('orders.no_match') : `${t('orders.none_yet')} ${t('common.add_first')}`));
      return;
    }
    list.replaceChildren(...items.map((o) => h('article', { class: 'glass card item' },
      h('div', { class: 'item-head' },
        h('div', {}, h('h3', {}, h('a', { href: `#/bestellingen/${o.id}` }, o.customer_name)),
          h('p', { class: 'muted' }, `${t('orders.number', { n: o.number })} · ${dateFmt(o.order_date)}`)),
        statusSelect(o)),
      h('dl', { class: 'stats' },
        stat(t('orders.total'), eur(o.total)), stat(t('orders.lines'), String(o.line_count)),
        o.delivery_date ? stat(t('orders.delivery'), dateFmt(o.delivery_date)) : null,
        o.invoice_number ? stat(t('orders.invoice'), o.invoice_number) : null))));
  }

  async function load() {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (query) params.set('q', query);
    try { draw(await api('GET', `/api/orders${params.toString() ? `?${params}` : ''}`)); } catch (e) { toast(e.message, 'error'); }
  }

  drawChips();
  load();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, t('nav.orders'))),
      h('a', { class: 'btn primary', href: '#/bestellingen/nieuw' }, icon('plus'), h('span', {}, t('orders.new')))),
    h('p', { class: 'muted page-intro' }, t('orders.intro')),
    h('div', { class: 'filters' }, chips, search),
    list);
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
      quantity: str(l.quantity), unit_price: str(l.unit_price), vat_pct: str(Number(l.vat_pct)), optional: !!l.optional,
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
    id: null, number: null, customer_id: null, status: 'nieuw', price_rounding: ctx.prefs.price_rounding || 'none', order_date: today(), delivery_date: '', customer_name: '', customer_number: '', subject: '', address: '', postal_code: '', city: '',
    country: '', email: '', phone: '', notes: '', invoice_number: null, invoice_date: '', has_invoice_pdf: false, lines: [],
  };
  let result = null;
  let dirty = false;
  let timer = null;
  const totals = h('dl', { class: 'totals' });
  const calcError = h('p', { class: 'error', role: 'alert', hidden: true });
  const linesBox = h('div', { class: 'lines' });
  const invoiceBox = h('div', { class: 'stack' });
  const customerBox = h('div', { class: 'stack' });
  const statusBox = h('div', { class: 'chips', role: 'group', 'aria-label': t('orders.status') });
  const lineTotals = [];
  const lineUnits = [];
  const marginHints = [];

  const payload = () => ({
    customer_id: state.customer_id, status: state.status, price_rounding: state.price_rounding, order_date: state.order_date, delivery_date: state.delivery_date || null,
    subject: state.subject.trim(), notes: state.notes, invoice_date: state.invoice_date || null,
    lines: state.lines.map((l) => ({ project_id: l.project_id, description: l.description, quantity: parseNum(l.quantity), vat_pct: parseNum(l.vat_pct), optional: !!l.optional,
      ...(l.cost_price == null ? { unit_price: parseNum(l.unit_price) } : { cost_price: parseNum(l.cost_price), margin_pct: parseNum(l.margin_pct) }) })),
  });

  // The prices and totals are the server's: it works out the price of a calculated line, takes the VAT out per rate, and what is shown here
  // is what an invoice will say.
  async function recalc() {
    try {
      const { lines, price_rounding } = payload();
      result = await api('POST', '/api/orders/totals', { lines, price_rounding });
      calcError.hidden = true;
      renderTotals();
    } catch (e) { calcError.textContent = e.message; calcError.hidden = false; }
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
      if (calculated) { lineUnits[i] = unit; marginHints[i] = hint; }
      const optional = h('label', { class: 'check' },
        h('input', { type: 'checkbox', checked: !!l.optional, onchange: (e) => { l.optional = e.target.checked; touch(); } }), t('orders.optional'));
      // the model's own line (not one of its accessories) can be brought up to date with the calculation it was made from
      const sync = l.project_id && !l.optional
        ? h('button', { class: 'btn small icon-only sync-line', type: 'button', title: t('orders.sync'), 'aria-label': t('orders.sync_line', { name: l.description || `#${l.project_number}` }),
          onclick: (e) => syncLine(l, e.currentTarget) }, icon('sync'))
        : null;
      return h('div', { class: `line order${calculated ? ' calc' : ''}` },
        h('div', { class: 'field' }, h('label', { for: inputId }, t('orders.description'), ' ', badge), sync ? h('div', { class: 'input-row' }, input, sync) : input, optional),
        field(t('orders.quantity'), numberInput(l.quantity, (v) => { l.quantity = v; touch(); }, { inputmode: 'numeric' })),
        calculated ? field(t('orders.margin'), numberInput(l.margin_pct, (v) => { l.margin_pct = v; touch(); }, { class: 'private' })) : null,
        calculated ? h('div', { class: 'field cost-field' }, h('span', { class: 'lbl' }, t('orders.unit_price_calc')), unit)
          : field(t('orders.unit_price'), numberInput(l.unit_price, (v) => { l.unit_price = v; touch(); })),
        field(t('orders.vat'), numberInput(l.vat_pct, (v) => { l.vat_pct = v; touch(); }, { list: 'order-vat-presets' })),
        h('div', { class: 'field cost-field' }, h('span', { class: 'lbl' }, t('orders.line_total')), total),
        removeBtn(t('orders.remove_line'), () => { state.lines.splice(i, 1); touch(); drawLines(); }),
        calculated ? hint : null);
    }));
    renderTotals();
  }

  // The lines a calculation adds to an order: the model itself, and the accessories of the calculation (cables, chargers) as lines of their
  // own that the invoice lists apart, because the product works without them. They are priced at what they cost; the model's line keeps
  // the rest of the cost price and the margin.
  const UNIT_SHORT = { stuks: t('unit.pieces'), m: 'm', g: 'g' };
  function modelLines(p) {
    const extras = (p.totals.parts || []).filter((x) => x.group === 'oplader' && Number(x.cost) > 0);
    const modelCost = Math.round((Number(p.totals.cost_price) - Number(p.totals.subtotals.charger || 0)) * 100) / 100;
    const model = { project_id: p.id, project_number: p.number, description: p.name, quantity: '1', unit_price: '', optional: false,
      cost_price: String(extras.length ? modelCost : p.totals.cost_price), margin_pct: str(Number(p.margin_pct)), vat_pct: str(Number(p.vat_pct)) };
    return [model, ...extras.map((x) => {
      const qty = Number(x.quantity), price = Number(x.unit_price);
      const whole = x.unit === 'stuks' && Number.isInteger(qty) && qty >= 1 && qty <= 100000 && Math.round(price * 100) / 100 === price;
      return { project_id: p.id, project_number: p.number, optional: true, quantity: whole ? String(qty) : '1', unit_price: '',
        description: whole ? x.label : `${x.label} (${fmt(qty)} ${UNIT_SHORT[x.unit] || x.unit})`,
        cost_price: String(whole ? price : x.cost), margin_pct: '0', vat_pct: str(Number(p.vat_pct)) };
    })];
  }

  // The model's line keeps the cost price its calculation had when it was added; this fetches the calculation as it is now and takes its cost
  // price again (the margin, VAT and quantity of the line are the order's own and stay). A line from before the cost price was kept gets
  // the calculation's cost price and margin, so the server can price it from then on. Saving the order stores it.
  async function syncLine(l, button) {
    button.disabled = true;
    try {
      const fresh = modelLines(await api('GET', `/api/projects/${l.project_id}`))[0];
      if (l.cost_price != null && Number(l.cost_price) === Number(fresh.cost_price)) { toast(t('orders.sync_current')); return; }
      l.cost_price = fresh.cost_price;
      if (!String(l.margin_pct ?? '').trim()) l.margin_pct = fresh.margin_pct;
      touch(); drawLines();
      toast(t('orders.sync_done', { cost: eur(fresh.cost_price) }));
    } catch (e) { toast(e.message, 'error'); } finally { button.disabled = false; }
  }

  // Loose accessories from the accessory list (cables, chargers), without a calculation: an optional line at cost price, which the
  // invoice lists apart from the products. Choosing the same one again adds one more of it.
  async function pickAccessory() {
    let items;
    try { items = (await api('GET', '/api/accessories')).filter((a) => !a.archived); } catch (e) { toast(e.message, 'error'); return; }
    const results = h('ul', { class: 'plain-list picker', 'aria-live': 'polite' });
    const added = new Map();
    const search = h('input', { type: 'text', autocomplete: 'off', placeholder: t('orders.search_accessories_ph'), 'aria-label': t('orders.search_accessories') });
    const per = (a) => (a.unit === 'stuks' ? '' : ` / ${a.unit === 'g' ? 'kg' : a.unit}`);
    const describe = (a) => (a.unit === 'stuks' ? a.name : t('orders.accessory_per', { name: a.name, unit: a.unit === 'g' ? 'kg' : a.unit }));
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const found = items.filter((a) => !q || a.name.toLowerCase().includes(q));
      results.replaceChildren(...(found.length ? found.map((a) => h('li', {}, h('button', { class: 'btn picker-item', type: 'button', onclick: () => {
        const existing = state.lines.find((l) => !l.project_id && l.optional && l.description === describe(a) && Number(l.cost_price) === Number(a.price));
        if (existing) existing.quantity = String(Math.floor(parseNum(existing.quantity)) + 1);
        else state.lines.push({ project_id: null, project_number: null, optional: true, description: describe(a), quantity: '1', unit_price: '', cost_price: str(Number(a.price)),
          margin_pct: '0', vat_pct: defaultVat });
        added.set(a.id, (added.get(a.id) || 0) + 1);
        touch(); drawLines(); draw();
      } }, h('span', { class: 'grow' }, a.name), added.has(a.id) ? h('span', { class: 'muted' }, `+${added.get(a.id)}`) : null,
      h('strong', {}, `${eur(a.price)}${per(a)}`)))) : [h('li', { class: 'muted' }, items.length ? t('orders.no_accessories_match') : t('orders.no_accessories'))]));
    };
    search.addEventListener('input', draw);
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
      h('h2', {}, t('orders.add_accessory')), h('p', { class: 'muted' }, t('orders.add_accessory_hint')),
      field(t('orders.search_accessories'), search), results,
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
      results.replaceChildren(...(found.length ? found.map((p) => h('li', {}, h('button', { class: 'btn picker-item', type: 'button', onclick: () => {
        const existing = state.lines.find((l) => l.project_id === p.id && !l.optional);
        if (existing) existing.quantity = String(Math.floor(parseNum(existing.quantity)) + 1);
        else state.lines.push(...modelLines(p));
        added.set(p.id, (added.get(p.id) || 0) + 1);
        touch(); drawLines(); draw();
      } }, h('span', { class: 'badge' }, `#${p.number}`), h('span', { class: 'grow' }, p.name),
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
      const results = h('ul', { class: 'plain-list picker', 'aria-live': 'polite' });
      const search = h('input', { type: 'text', autocomplete: 'off', placeholder: t('customers.search_ph'), 'aria-label': t('customers.search') });
      const matches = (c, q) => !q || [c.name, c.number, c.city, c.email].some((v) => String(v || '').toLowerCase().includes(q.toLowerCase()));
      const draw = () => {
        const found = customers.filter((c) => matches(c, search.value.trim()));
        results.replaceChildren(...(found.length ? found.map((c) => h('li', {}, h('button', { class: 'btn picker-item', type: 'button', onclick: () => done(c) },
          h('span', { class: 'badge' }, c.number), h('span', { class: 'grow' }, c.name), h('span', { class: 'muted' }, c.city || '')))) : [h('li', { class: 'muted' }, t('customers.no_match'))]));
      };
      search.addEventListener('input', draw);
      body.replaceChildren(h('h2', {}, t('customers.pick')), h('p', { class: 'muted' }, t('customers.pick_hint')), field(t('customers.search'), search), results,
        h('div', { class: 'row end' },
          h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
          h('button', { class: 'btn primary', type: 'button', id: 'new-customer', onclick: drawCreate }, icon('plus'), h('span', {}, t('customers.create')))));
      draw();
      search.focus();
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

  drawStatus();
  drawLines();
  drawInvoice();
  drawCustomer();
  recalc();
  return h('div', { class: 'editor' },
    h('header', { class: 'page-head' },
      h('div', {}, h('a', { class: 'back', href: '#/bestellingen' }, t('orders.back')),
        h('h1', {}, state.id ? t('orders.title_n', { n: state.number }) : t('orders.new')))),
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
          field(t('orders.rounding'), h('select', { onchange: (e) => { state.price_rounding = e.target.value; touch(); } },
            ROUNDINGS.map(([v, k]) => h('option', { value: v, selected: state.price_rounding === v }, t(k)))), t('orders.rounding_hint')),
          linesBox,
          h('datalist', { id: 'order-vat-presets' }, ['0', '9', '21'].map((v) => h('option', { value: v }))),
          h('div', { class: 'row' },
            h('button', { class: 'btn primary small', type: 'button', id: 'add-model', onclick: pickModel }, icon('plus'), h('span', {}, t('orders.add_model'))),
            h('button', { class: 'btn small', type: 'button', id: 'add-accessory', onclick: pickAccessory }, icon('plus'), h('span', {}, t('orders.add_accessory'))),
            h('button', { class: 'btn small', type: 'button', onclick: () => {
              state.lines.push({ project_id: null, project_number: null, optional: false, description: '', quantity: '1', unit_price: '', cost_price: null, margin_pct: '', vat_pct: defaultVat });
              touch(); drawLines();
            } }, icon('plus'), h('span', {}, t('orders.add_free_line'))))),
        h('div', { class: 'glass card' }, field(t('orders.notes'), h('textarea', { rows: 3, maxlength: 2000, oninput: (e) => bind('notes')(e.target.value) }, state.notes || ''), t('orders.notes_hint')))),
      h('aside', { class: 'glass card summary', 'aria-label': t('orders.total') },
        h('h2', {}, t('orders.total')), totals, calcError,
        h('div', { class: 'stack' },
          h('button', { class: 'btn primary', type: 'button', id: 'save-order', onclick: save }, t('common.save')),
          h('h3', {}, t('orders.status')), statusBox,
          h('h3', {}, t('orders.invoice')), invoiceBox,
          state.id ? h('button', { class: 'btn danger', type: 'button', onclick: async () => {
            if (!(await confirmDialog(t('orders.delete_confirm', { name: state.customer_name || t('orders.number', { n: state.number }) })))) return;
            try { await api('DELETE', `/api/orders/${state.id}`); dirty = false; setDirty(false); navigate('#/bestellingen'); } catch (e) { toast(e.message, 'error'); }
          } }, t('common.delete')) : null))));
}
