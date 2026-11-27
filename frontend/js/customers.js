import { api } from './api.js';
import { t } from './i18n.js';
import { listView } from './listview.js';
import { setDirty } from './updates.js';
import { backLink, confirmDialog, field, h, headAction, icon, toast } from './ui.js';

export const emptyCustomer = () => ({ number: '', name: '', address: '', postal_code: '', city: '', country: '', email: '', phone: '', notes: '',
  origin: '', marktplaats_profile_url: '', marktplaats_chat_url: '' });

// Where a customer came from: [word kept by the server, label key]; '' is "not said". The server accepts the same words (`customers.ORIGINS`; `test_customers.py` compares them).
export const ORIGINS = [['', 'customers.origin_none'], ['marktplaats', 'customers.origin_marktplaats'], ['webshop', 'customers.origin_webshop'], ['other', 'customers.origin_other']];
export const originName = (origin) => t((ORIGINS.find(([word]) => word === origin) || ORIGINS[0])[1]);
const isLink = (url) => /^https?:\/\/\S+$/i.test(String(url || '').trim());

/** Where the customer came from and, for Marktplaats, the links to their profile there and to the chat with them (each with a button that opens it), writing into `state`
 *  as they are typed. Used on the customer screen and in the "new customer" form of an order. The links show only while the origin is Marktplaats; the server keeps them
 *  only then too. */
export function originFields(state, onInput = () => {}) {
  const link = (key, label, hint) => {
    const open = h('a', { class: 'btn tool icon-only', target: '_blank', rel: 'noopener noreferrer', title: t('customers.open_link', { name: label }),
      'aria-label': t('customers.open_link', { name: label }) }, icon('external'));
    const mark = () => {                                          // a button that opens what is typed, once that is an address
      if (isLink(state[key])) open.href = state[key].trim(); else open.removeAttribute('href');
      open.setAttribute('aria-disabled', String(!isLink(state[key])));
    };
    const input = h('input', { type: 'url', inputmode: 'url', maxlength: 500, autocomplete: 'off', placeholder: 'https://', value: state[key] || '',
      oninput: (e) => { state[key] = e.target.value; mark(); onInput(); } });
    const row = field(label, input, hint);
    const together = h('div', { class: 'input-open' });
    input.replaceWith(together);
    together.append(input, open);
    mark();
    return row;
  };
  const links = h('div', { class: 'stack', id: 'marktplaats-links', hidden: state.origin !== 'marktplaats' },
    link('marktplaats_profile_url', t('customers.mp_profile'), t('customers.mp_profile_hint')),
    link('marktplaats_chat_url', t('customers.mp_chat'), t('customers.mp_chat_hint')));
  const origin = h('select', { onchange: (e) => { state.origin = e.target.value; links.hidden = state.origin !== 'marktplaats'; onInput(); } },
    ORIGINS.map(([word, label]) => h('option', { value: word, selected: word === state.origin }, t(label))));
  return [field(t('customers.origin'), origin, t('customers.origin_hint')), links];
}

/** The fields of a customer, writing into `state` as they are typed. Used on the customer screen and in the "new customer" form of an order. */
export function customerFields(state, onInput = () => {}) {
  const text = (key, attrs = {}) => h('input', { type: 'text', value: state[key] || '', maxlength: 200, ...attrs,
    oninput: (e) => { state[key] = e.target.value; onInput(); } });
  return [
    h('div', { class: 'two' },
      field(t('orders.customer_name'), text('name', { required: true, maxlength: 120, autocomplete: 'off' })),
      field(t('orders.customer_number'), text('number', { maxlength: 40, autocomplete: 'off', placeholder: t('customers.number_auto') }))),
    field(t('orders.address'), text('address', { autocomplete: 'off' })),
    h('div', { class: 'two' },
      field(t('orders.postal_code'), text('postal_code', { maxlength: 20, autocomplete: 'off' })),
      field(t('orders.city'), text('city', { maxlength: 100, autocomplete: 'off' }))),
    field(t('orders.country'), text('country', { maxlength: 60, autocomplete: 'off' })),
    h('div', { class: 'two even' },
      field(t('orders.email'), text('email', { type: 'email', autocomplete: 'off', inputmode: 'email' })),
      field(t('orders.phone'), text('phone', { type: 'tel', maxlength: 40, autocomplete: 'off', inputmode: 'tel' }))),
  ];
}

/** A search field and the list of the customers that match it, for a pop-up: choosing one calls `onPick(customer)`. Returns the field (with its label), the list and
 *  the input, so the caller can lay them out and put the focus there. */
export function customerPicker(customers, onPick) {
  const results = h('ul', { class: 'plain-list picker', 'aria-live': 'polite' });
  const input = h('input', { type: 'text', autocomplete: 'off', placeholder: t('customers.search_ph'), 'aria-label': t('customers.search') });
  const matches = (c, q) => !q || [c.name, c.number, c.city, c.email].some((v) => String(v || '').toLowerCase().includes(q.toLowerCase()));
  const draw = () => {
    const found = customers.filter((c) => matches(c, input.value.trim()));
    results.replaceChildren(...(found.length ? found.map((c) => h('li', {}, h('button', { class: 'btn picker-item', type: 'button', onclick: () => onPick(c) },
      h('span', { class: 'badge' }, c.number), h('span', { class: 'grow' }, c.name), h('span', { class: 'muted' }, c.city || '')))) : [h('li', { class: 'muted' }, t('customers.no_match'))]));
  };
  input.addEventListener('input', draw);
  draw();
  return { field: field(t('customers.search'), input), results, input };
}

/** The details of a customer as lines of text (address, contact). */
export function customerLines(c) {
  const place = [c.postal_code, c.city].filter(Boolean).join(' ');
  return [c.address, place, c.country, c.email, c.phone].filter(Boolean);
}

// --- list -----------------------------------------------------------------------

const LIST_CAP = 500;                                 // what the server lists at most; with more customers than that, the search is asked of the server too

export function customerListView() {
  const href = (c) => `#/klanten/${c.id}`;
  let timer = null;
  let asked = '';
  const mail = (c) => (c.email ? h('a', { href: `mailto:${c.email}` }, c.email) : '—');
  const view = listView({
    id: 'customers',
    search: { label: t('customers.search'), placeholder: t('customers.search_ph'), text: (c) => [c.name, c.number, c.city, c.email, c.phone, c.postal_code] },
    filters: [{ key: 'city', label: t('orders.city'), all: t('customers.all_cities'), value: (c) => c.city },
      { key: 'origin', label: t('customers.origin'), all: t('customers.all_origins'), value: (c) => originName(c.origin) }],
    sorts: [
      { key: 'name', label: t('sort.name'), value: (c) => c.name },
      { key: 'number', label: t('orders.customer_number'), value: (c) => c.number },
      { key: 'city', label: t('orders.city'), value: (c) => c.city || '\uffff' },
      { key: 'orders', label: t('nav.orders'), value: (c) => Number(c.orders), desc: true }],
    tie: (c) => c.name,
    href,
    columns: [
      { label: t('sort.name'), sort: 'name', cls: 'main', cell: (c) => h('div', {}, h('a', { class: 'cell-title', href: href(c) }, c.name),
        h('div', { class: 'cell-sub muted' }, t('customers.number_n', { number: c.number }))) },
      { label: t('orders.city'), sort: 'city', cell: (c) => c.city || '—' },
      { label: t('orders.email'), wide: true, cell: mail },
      { label: t('orders.phone'), cls: 'nowrap', wide: true, cell: (c) => c.phone || '—' },
      { label: t('customers.origin'), cls: 'nowrap', wide: true, cell: (c) => (c.origin ? originName(c.origin) : '—') },
      { label: t('nav.orders'), sort: 'orders', cls: 'num', cell: (c) => (Number(c.orders) ? h('a', { href: `#/bestellingen/klant/${c.id}`, title: t('customers.orders_view') }, String(c.orders)) : '0') }],
    tile: (c) => h('article', { class: 'glass card item' },
      h('div', { class: 'item-head' },
        h('div', {}, h('h3', {}, h('a', { href: href(c) }, c.name)),
          h('p', { class: 'muted' }, [t('customers.number_n', { number: c.number }), c.city, c.origin ? originName(c.origin) : ''].filter(Boolean).join(' · '))),
        h('span', { class: 'badge' }, t('customers.orders_n', { n: c.orders }))),
      customerLines(c).length ? h('p', { class: 'muted' }, customerLines(c).join(' · ')) : null),
    empty: `${t('customers.none_yet')} ${t('common.add_first')}`, noMatch: t('customers.no_match'),
  });

  async function load(query = '') {
    try {
      const items = await api('GET', `/api/customers${query ? `?q=${encodeURIComponent(query)}` : ''}`);
      asked = query;
      view.setItems(items);
      // The list is filtered here while typing. Only when there are more customers than one answer holds does the server search as well.
      if (items.length >= LIST_CAP || query) view.el.oninput = () => {
        clearTimeout(timer);
        timer = setTimeout(() => { if (view.query.trim() !== asked) load(view.query.trim()); }, 250);
      };
    } catch (e) { toast(e.message, 'error'); }
  }

  load();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, t('nav.customers'))),
      h('a', { class: 'btn primary', href: '#/klanten/nieuw' }, icon('plus'), h('span', {}, t('customers.new')))),
    h('p', { class: 'muted page-intro' }, t('customers.intro')),
    view.el);
}

// --- editor ---------------------------------------------------------------------

export function customerEditorView(id, navigate) {
  const root = h('section', { class: 'page' }, h('p', { class: 'muted' }, t('common.loading')));
  (id ? api('GET', `/api/customers/${id}`) : Promise.resolve(null))
    .then((customer) => root.replaceChildren(buildEditor(customer, navigate)))
    .catch((e) => root.replaceChildren(h('p', { class: 'error', role: 'alert' }, e.message)));
  return root;
}

function buildEditor(customer, navigate) {
  const state = customer ? { ...emptyCustomer(), ...customer } : emptyCustomer();
  const orderCount = customer ? customer.orders : 0;
  let dirty = false;
  const touch = () => { dirty = true; setDirty(true); };
  const notes = h('textarea', { rows: 3, maxlength: 2000, oninput: (e) => { state.notes = e.target.value; touch(); } }, state.notes || '');

  async function save() {
    if (!state.name.trim()) { toast(t('customers.name_required'), 'error'); return; }
    const body = { number: state.number.trim(), name: state.name.trim(), address: state.address, postal_code: state.postal_code, city: state.city,
      country: state.country, email: state.email.trim(), phone: state.phone, notes: state.notes,
      origin: state.origin, marktplaats_profile_url: state.marktplaats_profile_url.trim(), marktplaats_chat_url: state.marktplaats_chat_url.trim() };
    try {
      if (customer) await api('PUT', `/api/customers/${customer.id}`, body);
      else await api('POST', '/api/customers', body);
      dirty = false;
      setDirty(false);
      toast(t('customers.saved'));
      navigate('#/klanten');
    } catch (e) { toast(e.message, 'error'); }
  }

  // A new customer with everything of this one and the next klantnummer; its orders stay with this one. Made from what is saved, so what is typed and not saved is asked for first.
  async function duplicate() {
    if (dirty) { toast(t('customers.duplicate_save_first'), 'error'); return; }
    try {
      const copy = await api('POST', `/api/customers/${customer.id}/duplicate`);
      toast(t('customers.duplicated', { number: copy.number }));
      navigate(`#/klanten/${copy.id}`);
    } catch (e) { toast(e.message, 'error'); }
  }

  async function remove() {
    if (!(await confirmDialog(t('customers.delete_confirm', { name: state.name })))) return;
    try { await api('DELETE', `/api/customers/${customer.id}`); setDirty(false); navigate('#/klanten'); } catch (e) { toast(e.message, 'error'); }
  }

  return h('div', { class: 'editor' },
    h('header', { class: 'page-head' },
      h('div', {}, backLink('#/klanten', t('nav.customers')),
        h('h1', {}, customer ? customer.name : t('customers.new'))),
      h('div', { class: 'row actions' },
        customer ? h('div', { class: 'btn-group', role: 'group', 'aria-label': t('customers.actions') },
          headAction('copy', t('customers.duplicate'), duplicate, '', { id: 'duplicate-customer' }),
          headAction('trash', t('common.delete'), remove, ' danger', { id: 'delete-customer', disabled: orderCount > 0, title: orderCount > 0 ? t('customers.delete_blocked') : t('common.delete') })) : null,
        headAction('save', t('common.save'), save, ' primary', { id: 'save-customer' }))),
    h('div', { class: 'glass card stack' },
      ...customerFields(state, touch),
      ...originFields(state, touch),
      field(t('orders.notes'), notes, t('customers.notes_hint')),
      customer ? h('p', { class: 'muted' }, t('customers.orders_of', { n: orderCount }), orderCount > 0 ? [' ', h('a', { href: `#/bestellingen/klant/${customer.id}`, id: 'customer-orders' }, t('customers.orders_view'))] : null) : null,
      customer && orderCount > 0 ? h('p', { class: 'hint' }, t('customers.delete_blocked')) : null));
}
