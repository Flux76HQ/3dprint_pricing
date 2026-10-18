import { api, downloadFile } from './api.js';
import { formatDate, t } from './i18n.js';
import { setDirty } from './updates.js';
import { confirmDialog, enhanceDialog, eur, field, h, icon, numberInput, parseNum, saveBlob, toast } from './ui.js';

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
      h('div', {}, h('h1', {}, t('nav.orders')), h('p', { class: 'muted' }, t('orders.intro'))),
      h('a', { class: 'btn primary', href: '#/bestellingen/nieuw' }, icon('plus'), h('span', {}, t('orders.new')))),
    h('div', { class: 'filters' }, chips, search),
    list);
}

// --- editor ---------------------------------------------------------------------

const str = (v) => (v == null ? '' : String(v));

function fromSaved(order) {
  return {
    id: order.id, number: order.number, status: order.status, order_date: order.order_date, delivery_date: str(order.delivery_date),
    customer_name: order.customer_name, customer_number: order.customer_number, subject: order.subject, address: order.address, postal_code: order.postal_code, city: order.city, country: order.country,
    email: order.email, phone: order.phone, notes: order.notes, invoice_number: order.invoice_number, invoice_date: str(order.invoice_date), has_invoice_pdf: !!order.has_invoice_pdf,
    lines: order.lines.map((l) => ({ project_id: l.project_id, project_number: l.project_number, description: l.description,
      quantity: str(l.quantity), unit_price: str(l.unit_price), vat_pct: str(Number(l.vat_pct)) })),
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
    id: null, number: null, status: 'nieuw', order_date: today(), delivery_date: '', customer_name: '', customer_number: '', subject: '', address: '', postal_code: '', city: '',
    country: '', email: '', phone: '', notes: '', invoice_number: null, invoice_date: '', has_invoice_pdf: false, lines: [],
  };
  let result = null;
  let dirty = false;
  let timer = null;
  const totals = h('dl', { class: 'totals' });
  const calcError = h('p', { class: 'error', role: 'alert', hidden: true });
  const linesBox = h('div', { class: 'lines' });
  const invoiceBox = h('div', { class: 'stack' });
  const statusBox = h('div', { class: 'chips', role: 'group', 'aria-label': t('orders.status') });
  const lineTotals = [];

  const payload = () => ({
    status: state.status, order_date: state.order_date, delivery_date: state.delivery_date || null, customer_name: state.customer_name.trim(),
    customer_number: state.customer_number.trim(), subject: state.subject.trim(),
    address: state.address, postal_code: state.postal_code, city: state.city, country: state.country, email: state.email.trim(), phone: state.phone,
    notes: state.notes, invoice_date: state.invoice_date || null,
    lines: state.lines.map((l) => ({ project_id: l.project_id, description: l.description, quantity: parseNum(l.quantity),
      unit_price: parseNum(l.unit_price), vat_pct: parseNum(l.vat_pct) })),
  });

  // The totals are the server's: it takes the VAT out per rate, and what is shown here is what an invoice will say.
  async function recalc() {
    try {
      result = await api('POST', '/api/orders/totals', { lines: payload().lines });
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
  }

  // --- lines -------------------------------------------------------------------------
  const removeBtn = (label, onClick) => h('button', { class: 'btn small danger icon-only', type: 'button', 'aria-label': label, onclick: onClick }, icon('trash'));

  function drawLines() {
    lineTotals.length = 0;
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
      return h('div', { class: 'line order' },
        h('div', { class: 'field' }, h('label', { for: inputId }, t('orders.description'), ' ', badge), input),
        field(t('orders.quantity'), numberInput(l.quantity, (v) => { l.quantity = v; touch(); }, { inputmode: 'numeric' })),
        field(t('orders.unit_price'), numberInput(l.unit_price, (v) => { l.unit_price = v; touch(); })),
        field(t('orders.vat'), numberInput(l.vat_pct, (v) => { l.vat_pct = v; touch(); }, { list: 'order-vat-presets' })),
        h('div', { class: 'field cost-field' }, h('span', { class: 'lbl' }, t('orders.line_total')), total),
        removeBtn(t('orders.remove_line'), () => { state.lines.splice(i, 1); touch(); drawLines(); }));
    }));
    renderTotals();
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
        const existing = state.lines.find((l) => l.project_id === p.id);
        if (existing) existing.quantity = String(Math.floor(parseNum(existing.quantity)) + 1);
        else state.lines.push({ project_id: p.id, project_number: p.number, description: p.name, quantity: '1',
          unit_price: str(p.totals.sell_price_incl_vat), vat_pct: str(Number(p.vat_pct)) });
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
    invoiceBox.replaceChildren(...parts);
  }

  drawStatus();
  drawLines();
  drawInvoice();
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
        h('div', { class: 'glass card stack' }, h('h2', {}, t('orders.customer')),
          h('div', { class: 'two' },
            field(t('orders.customer_name'), textInput('customer_name', { required: true, maxlength: 120, autocomplete: 'name' })),
            field(t('orders.customer_number'), textInput('customer_number', { maxlength: 40, autocomplete: 'off' }))),
          field(t('orders.address'), textInput('address', { maxlength: 200, autocomplete: 'street-address' })),
          h('div', { class: 'two' },
            field(t('orders.postal_code'), textInput('postal_code', { maxlength: 20, autocomplete: 'postal-code' })),
            field(t('orders.city'), textInput('city', { maxlength: 100, autocomplete: 'address-level2' }))),
          field(t('orders.country'), textInput('country', { maxlength: 60, autocomplete: 'country-name' })),
          h('div', { class: 'two even' },
            field(t('orders.email'), textInput('email', { type: 'email', maxlength: 200, autocomplete: 'email', inputmode: 'email' })),
            field(t('orders.phone'), textInput('phone', { type: 'tel', maxlength: 40, autocomplete: 'tel', inputmode: 'tel' })))),
        h('div', { class: 'glass card' }, h('h2', {}, t('orders.models')), h('p', { class: 'muted' }, t('orders.models_hint')), linesBox,
          h('datalist', { id: 'order-vat-presets' }, ['0', '9', '21'].map((v) => h('option', { value: v }))),
          h('div', { class: 'row' },
            h('button', { class: 'btn primary small', type: 'button', id: 'add-model', onclick: pickModel }, icon('plus'), h('span', {}, t('orders.add_model'))),
            h('button', { class: 'btn small', type: 'button', onclick: () => {
              state.lines.push({ project_id: null, project_number: null, description: '', quantity: '1', unit_price: '', vat_pct: defaultVat });
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
