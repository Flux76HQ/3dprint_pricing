import { api } from './api.js';
import { t } from './i18n.js';
import { setDirty } from './updates.js';
import { confirmDialog, field, h, icon, toast } from './ui.js';

export const emptyCustomer = () => ({ number: '', name: '', address: '', postal_code: '', city: '', country: '', email: '', phone: '', notes: '' });

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

/** The details of a customer as lines of text (address, contact). */
export function customerLines(c) {
  const place = [c.postal_code, c.city].filter(Boolean).join(' ');
  return [c.address, place, c.country, c.email, c.phone].filter(Boolean);
}

// --- list -----------------------------------------------------------------------

export function customerListView() {
  let query = '';
  let timer = null;
  const list = h('div', { class: 'cards' }, h('p', { class: 'muted' }, t('common.loading')));
  const search = h('input', { type: 'text', 'aria-label': t('customers.search'), placeholder: t('customers.search_ph'), autocomplete: 'off',
    oninput: (e) => { query = e.target.value.trim(); clearTimeout(timer); timer = setTimeout(load, 250); } });

  function draw(items) {
    if (!items.length) {
      list.replaceChildren(h('p', { class: 'empty glass card' }, query ? t('customers.no_match') : `${t('customers.none_yet')} ${t('common.add_first')}`));
      return;
    }
    list.replaceChildren(...items.map((c) => h('article', { class: 'glass card item' },
      h('div', { class: 'item-head' },
        h('div', {}, h('h3', {}, h('a', { href: `#/klanten/${c.id}` }, c.name)),
          h('p', { class: 'muted' }, [t('customers.number_n', { number: c.number }), c.city].filter(Boolean).join(' · '))),
        h('span', { class: 'badge' }, t('customers.orders_n', { n: c.orders }))),
      customerLines(c).length ? h('p', { class: 'muted' }, customerLines(c).join(' · ')) : null)));
  }

  async function load() {
    try { draw(await api('GET', `/api/customers${query ? `?q=${encodeURIComponent(query)}` : ''}`)); } catch (e) { toast(e.message, 'error'); }
  }

  load();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, t('nav.customers')), h('p', { class: 'muted' }, t('customers.intro'))),
      h('a', { class: 'btn primary', href: '#/klanten/nieuw' }, icon('plus'), h('span', {}, t('customers.new')))),
    h('div', { class: 'filters' }, search),
    list);
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
  const notes = h('textarea', { rows: 3, maxlength: 2000, oninput: (e) => { state.notes = e.target.value; setDirty(true); } }, state.notes || '');

  async function save() {
    if (!state.name.trim()) { toast(t('customers.name_required'), 'error'); return; }
    const body = { number: state.number.trim(), name: state.name.trim(), address: state.address, postal_code: state.postal_code, city: state.city,
      country: state.country, email: state.email.trim(), phone: state.phone, notes: state.notes };
    try {
      if (customer) await api('PUT', `/api/customers/${customer.id}`, body);
      else await api('POST', '/api/customers', body);
      setDirty(false);
      toast(t('customers.saved'));
      navigate('#/klanten');
    } catch (e) { toast(e.message, 'error'); }
  }

  async function remove() {
    if (!(await confirmDialog(t('customers.delete_confirm', { name: state.name })))) return;
    try { await api('DELETE', `/api/customers/${customer.id}`); setDirty(false); navigate('#/klanten'); } catch (e) { toast(e.message, 'error'); }
  }

  return h('div', { class: 'editor' },
    h('header', { class: 'page-head' },
      h('div', {}, h('a', { class: 'back', href: '#/klanten' }, t('customers.back')),
        h('h1', {}, customer ? customer.name : t('customers.new')))),
    h('div', { class: 'glass card stack' },
      ...customerFields(state, () => setDirty(true)),
      field(t('orders.notes'), notes, t('customers.notes_hint')),
      customer ? h('p', { class: 'muted' }, t('customers.orders_of', { n: orderCount })) : null,
      h('div', { class: 'row' },
        h('button', { class: 'btn primary', type: 'button', id: 'save-customer', onclick: save }, t('common.save')),
        customer ? h('button', { class: 'btn danger', type: 'button', id: 'delete-customer', disabled: orderCount > 0, onclick: remove }, t('common.delete')) : null),
      customer && orderCount > 0 ? h('p', { class: 'hint' }, t('customers.delete_blocked')) : null));
}
