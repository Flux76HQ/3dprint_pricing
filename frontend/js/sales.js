import { api } from './api.js';
import { formatDate, t } from './i18n.js';
import { eur, fill, fmt, h, switchRow, toast } from './ui.js';

// What the orders earned: revenue (excl. VAT), cost and the margin that is left, over a week, a month or a year. The figures are the server's
// (`reports.py`); this page only draws them: the totals of now, a chart of the chosen period and the orders behind it.
const PERIODS = ['week', 'month', 'year'];
const PERIOD_KEYS = { week: 'sales.week', month: 'sales.month', year: 'sales.year' };
const NOW_KEYS = { week: 'sales.this_week', month: 'sales.this_month', year: 'sales.this_year' };
const day = (iso, options) => formatDate(`${iso}T12:00:00`, options);       // a date without a time: noon keeps it on that day in every time zone

/** The words that name the window being looked at: "week 48 · 23 nov – 29 nov 2026", "november 2026", "2026". */
function windowLabel(data) {
  if (data.period === 'year') return day(data.start, { year: 'numeric' });
  if (data.period === 'month') return day(data.start, { month: 'long', year: 'numeric' });
  return `${day(data.start, { day: 'numeric', month: 'short' })} – ${day(data.end, { day: 'numeric', month: 'short', year: 'numeric' })}`;
}

const stat = (label, value, cls = '') => h('div', { class: cls }, h('dt', {}, label), h('dd', {}, value));
const pct = (v) => (v == null ? '—' : `${fmt(v, 1)}%`);

/** One bar per day (week, month) or month (year): the cost at the bottom, the margin on top, so the height is the revenue. */
function chart(data) {
  const top = Math.max(...data.buckets.map((b) => Number(b.revenue)), 0);
  const label = (b) => (data.period === 'year' ? day(b.date, { month: 'short' }) : data.period === 'week' ? day(b.date, { weekday: 'short' }) : String(Number(b.date.slice(8))));
  const bars = data.buckets.map((b) => {
    const cost = h('span', { class: 'bar-cost' });
    const margin = h('span', { class: 'bar-margin' });
    const stack = h('span', { class: 'bar-stack' }, margin, cost);
    const share = top > 0 ? Number(b.revenue) / top * 100 : 0;
    stack.style.height = `${share}%`;
    const revenue = Number(b.revenue);
    if (revenue > 0) { cost.style.height = `${Math.min(Number(b.cost) / revenue, 1) * 100}%`; margin.style.height = `${Math.max(1 - Number(b.cost) / revenue, 0) * 100}%`; }
    return h('li', { class: 'bar', title: `${data.period === 'year' ? day(b.date, { month: 'long' }) : day(b.date, { day: 'numeric', month: 'short' })}: ${t('sales.revenue')} ${eur(b.revenue)} · ${t('sales.cost')} ${eur(b.cost)} · ${t('sales.margin')} ${eur(b.margin)}` },
      h('span', { class: 'bar-area' }, stack), h('span', { class: 'bar-label muted' }, label(b)));
  });
  return h('div', { class: 'glass card stack' },
    h('div', { class: 'chart-head' }, h('h2', {}, t('sales.chart_title')),
      h('ul', { class: 'legend' }, h('li', {}, h('i', { class: 'swatch margin' }), t('sales.margin')), h('li', {}, h('i', { class: 'swatch cost' }), t('sales.cost')))),
    top > 0 ? h('ol', { class: `bars bars-${data.period}`, role: 'img', 'aria-label': t('sales.chart_title') }, bars) : h('p', { class: 'muted' }, t('sales.nothing')));
}

function ordersTable(data) {
  const totals = data.totals;
  const num = (v, cls = '') => h('td', { class: `num ${cls}`.trim() }, eur(v));
  return h('div', { class: 'table-wrap glass card' }, h('table', { class: 'data-table sales-table' },
    h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, t('sales.order')), h('th', { scope: 'col', class: 'wide' }, t('sales.date')), h('th', { scope: 'col', class: 'num' }, t('sales.revenue')),
      h('th', { scope: 'col', class: 'num' }, t('sales.cost')), h('th', { scope: 'col', class: 'num' }, t('sales.margin')))),
    h('tbody', {}, data.orders.map((o) => h('tr', { class: 'opens', onclick: () => { location.hash = `#/bestellingen/${o.id}`; } },
      h('th', { scope: 'row' }, h('a', { href: `#/bestellingen/${o.id}`, onclick: (e) => e.stopPropagation() }, o.subject || t('orders.number', { n: o.number })),
        h('div', { class: 'cell-sub muted' }, o.customer_name)),
      h('td', { class: 'wide' }, day(o.order_date, { day: 'numeric', month: 'short' })), num(o.revenue), num(o.cost), num(o.margin, 'strong')))),
    h('tfoot', {}, h('tr', {}, h('th', { scope: 'row', colspan: 2 }, t('sales.total_of', { n: totals.orders })), num(totals.revenue, 'strong'), num(totals.cost, 'strong'), num(totals.margin, 'strong')))));
}

/** The sales overview page. */
export function salesView() {
  const state = { period: 'month', offset: 0, include_open: false };
  const root = h('section', { class: 'page sales' });
  const body = h('div', { class: 'stack' });
  let seq = 0;

  const periodButtons = h('div', { class: 'chips', role: 'group', 'aria-label': t('sales.period') });
  const drawPeriods = () => periodButtons.replaceChildren(...PERIODS.map((p) => h('button', { type: 'button', class: 'seg', 'aria-pressed': String(state.period === p),
    onclick: () => { state.period = p; state.offset = 0; load(); } }, t(PERIOD_KEYS[p]))));

  async function load() {
    const mine = ++seq;
    drawPeriods();
    try {
      const data = await api('GET', `/api/reports/sales?period=${state.period}&offset=${state.offset}&include_open=${state.include_open}`);
      if (mine === seq) draw(data);
    } catch (e) { toast(e.message, 'error'); }
  }

  function draw(data) {
    const nowCard = (p) => h('div', { class: 'glass card stack' }, h('h3', {}, t(NOW_KEYS[p])),
      h('p', { class: 'big' }, eur(data.now[p].margin)),
      h('dl', { class: 'stats' }, stat(t('sales.revenue'), eur(data.now[p].revenue)), stat(t('sales.cost'), eur(data.now[p].cost)), stat(t('sales.orders'), String(data.now[p].orders))));
    const totals = data.totals;
    fill(body,
      h('div', { class: 'cards sales-now' }, PERIODS.map(nowCard)),
      h('div', { class: 'glass card stack' },
        h('div', { class: 'row sales-nav' },
          periodButtons,
          h('div', { class: 'btn-group', role: 'group', 'aria-label': t('sales.move') },
            h('button', { class: 'btn tool', type: 'button', title: t('sales.previous'), 'aria-label': t('sales.previous'), onclick: () => { state.offset -= 1; load(); } }, '‹'),
            h('button', { class: 'btn tool', type: 'button', disabled: state.offset === 0, onclick: () => { state.offset = 0; load(); } }, t('sales.today')),
            h('button', { class: 'btn tool', type: 'button', title: t('sales.next'), 'aria-label': t('sales.next'), onclick: () => { state.offset += 1; load(); } }, '›'))),
        h('h2', {}, windowLabel(data)),
        h('dl', { class: 'stats' }, stat(t('sales.revenue'), eur(totals.revenue)), stat(t('sales.cost'), eur(totals.cost)), stat(t('sales.margin'), eur(totals.margin), 'strong'),
          stat(t('sales.margin_pct'), pct(totals.margin_pct)), stat(t('sales.orders'), String(totals.orders))),
        totals.unknown_cost_lines ? h('p', { class: 'hint' }, t('sales.unknown_cost', { n: totals.unknown_cost_lines })) : null,
        switchRow(t('sales.include_open'), t('sales.include_open_hint'), state.include_open, (on) => { state.include_open = on; load(); })),
      chart(data),
      data.orders.length ? ordersTable(data) : h('p', { class: 'muted' }, t('sales.nothing')));
  }

  fill(root, h('header', { class: 'page-head' }, h('div', {}, h('h1', {}, t('sales.title')))), h('p', { class: 'page-intro muted' }, t('sales.intro')), body);
  load();
  return root;
}
