// Settings -> Koppelingen (administrators only; the server refuses these calls to anyone else): the connections to Spoolman and HaspelSync (spoolman.js, haspelsync.js),
// API keys, with which another application reads orders, invoices and customers, and webhooks, which tell another application that something happened. Every one is a card
// that folds away and says in its heading whether the connection is active, not connected or not configured. A key and a signing key are shown once, when they are made:
// the server keeps only a hash of the first and a sealed copy of the second.
import { api } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { confirmIdentity } from './password.js';
import { connectionBadge, field, fill, foldHead, h, icon, switchRow, toast } from './ui.js';

// What a webhook can be told: [name the server knows it by, label key]. The order is the server's.
const EVENT_LABELS = { 'invoice.created': 'hooks.ev_invoice_created', 'invoice.updated': 'hooks.ev_invoice_updated', 'order.created': 'hooks.ev_order_created',
  'order.updated': 'hooks.ev_order_updated', 'order.status_changed': 'hooks.ev_order_status', 'order.deleted': 'hooks.ev_order_deleted', ping: 'hooks.ev_ping' };
const STATE_LABELS = { pending: 'hooks.state_pending', delivered: 'hooks.state_delivered', dead: 'hooks.state_dead' };
const eventName = (event) => (EVENT_LABELS[event] ? t(EVENT_LABELS[event]) : event);
const when = (value) => (value ? formatDateTime(value) : '—');

/** The box that shows a fresh key, with a Copy button: the only time it can be seen. */
function onceBox(value, title, hint) {
  const input = h('input', { type: 'text', class: 'mono', readonly: true, value, 'aria-label': title, onfocus: (e) => e.target.select() });
  return h('div', { class: 'notice info stack', role: 'status' },
    h('strong', {}, title),
    h('div', { class: 'row nowrap' }, input, h('button', { class: 'btn', type: 'button', onclick: async () => {
      try { await navigator.clipboard.writeText(value); toast(t('common.copied')); } catch { input.select(); toast(t('common.copy_failed'), 'error'); }
    } }, icon('copy'), h('span', {}, t('common.copy')))),
    h('p', { class: 'hint' }, hint));
}

function keysCard() {
  const badge = connectionBadge();
  const list = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  const shown = h('div');
  const name = h('input', { type: 'text', autocomplete: 'off', maxlength: 60, required: true, placeholder: t('keys.name_ph') });
  const address = `${location.origin}/api/v1`;

  async function load() {
    let data;
    try { data = await api('GET', '/api/integrations/keys'); } catch (e) { badge.set('offline', { message: e.message }); fill(list, h('p', { class: 'error', role: 'alert' }, e.message)); return; }
    badge.set(data.keys.length ? 'active' : 'off', { detail: data.keys.length ? t('keys.count', { n: data.keys.length }) : null });        // a key is the only thing to set up: with none, nothing can connect
    fill(list, data.keys.length ? h('ul', { class: 'plain-list' }, data.keys.map((key) => h('li', { class: 'list-row' },
      h('div', {}, h('strong', {}, key.name), ' ', h('code', {}, `${key.shown}…`),
        h('p', { class: 'muted' }, `${t('keys.made', { date: when(key.created_at) })} · ${key.last_used_at ? t('keys.used', { date: when(key.last_used_at) }) : t('keys.never_used')}`)),
      h('button', { class: 'btn small danger', type: 'button', onclick: () => revoke(key) }, icon('trash'), h('span', {}, t('keys.revoke'))))))
      : h('p', { class: 'muted' }, t('keys.none')));
  }

  async function create(e) {
    e.preventDefault();
    const proof = await confirmIdentity({ action: 'api-key-create', title: t('keys.confirm_title'), message: t('keys.confirm_msg'), confirmLabel: t('keys.make') });
    if (!proof) return;                                              // cancelled: nothing is made
    try {
      const made = await api('POST', '/api/integrations/keys', { name: name.value.trim(), ...proof });
      name.value = '';
      fill(shown, onceBox(made.key, t('keys.once_title', { name: made.item.name }), t('keys.once_hint')));
      load();
    } catch (err) { toast(err.message, 'error'); }
  }

  async function revoke(key) {
    const proof = await confirmIdentity({ action: 'api-key-revoke', target: key.id, title: t('keys.revoke_title'),
      message: t('keys.revoke_msg', { name: key.name }), confirmLabel: t('keys.revoke') });
    if (!proof) return;
    try { await api('DELETE', `/api/integrations/keys/${key.id}`, proof); toast(t('keys.revoked', { name: key.name })); fill(shown); load(); } catch (e) { toast(e.message, 'error'); }
  }

  load();
  return h('div', { class: 'glass card stack' },
    foldHead('integration-keys', t('keys.title'), { open: false, extra: badge.el }),
    h('p', { class: 'muted' }, t('keys.intro')),
    h('dl', { class: 'kv' }, h('span', {}, t('keys.address')), h('strong', {}, h('code', {}, address))),
    list, shown,
    h('form', { class: 'row', onsubmit: create }, h('div', { class: 'grow' }, field(t('keys.name'), name, t('keys.name_hint'))),
      h('button', { class: 'btn primary', type: 'submit' }, icon('plus'), h('span', {}, t('keys.make')))));
}

function hooksCard() {
  const badge = connectionBadge();
  const list = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  const shown = h('div');
  const name = h('input', { type: 'text', autocomplete: 'off', maxlength: 60, required: true, placeholder: t('hooks.name_ph') });
  const url = h('input', { type: 'url', inputmode: 'url', autocomplete: 'off', maxlength: 500, required: true, placeholder: 'https://finance.example.nl/hooks/printpricing' });
  const picks = h('div', { class: 'checks' });
  let events = [];

  const drawPicks = () => fill(picks, events.map((event) => h('label', { class: 'check' },
    h('input', { type: 'checkbox', value: event, checked: event.startsWith('invoice.') }), eventName(event))));
  const picked = () => [...picks.querySelectorAll('input:checked')].map((box) => box.value);

  /** The last messages to one address: what, how it went and why not, with "send again" for one that was given up. */
  function logOf(endpoint) {
    const body = h('div', { class: 'stack' });
    async function draw() {
      fill(body, h('p', { class: 'muted' }, t('common.loading')));
      try {
        const { deliveries } = await api('GET', `/api/integrations/webhooks/${endpoint.id}/deliveries`);
        fill(body, deliveries.length ? h('ul', { class: 'plain-list hook-log' }, deliveries.map((d) => h('li', { class: 'list-row' },
          h('div', {}, h('strong', {}, eventName(d.event)), ' ', h('span', { class: `pill ${d.state === 'delivered' ? 'ok' : d.state === 'dead' ? 'error' : 'warn'}` }, t(STATE_LABELS[d.state])),
            h('p', { class: 'muted' }, [when(d.created_at), t('hooks.attempts', { n: d.attempts }),
              d.last_error ? t(d.last_error, { code: d.last_status ?? '' }) : null,
              d.state === 'pending' && d.next_attempt_at ? t('hooks.next', { date: when(d.next_attempt_at) }) : null].filter(Boolean).join(' · '))),
          d.state === 'dead' && d.event !== 'ping' ? h('button', { class: 'btn small', type: 'button', onclick: async () => {
            try { await api('POST', `/api/integrations/webhooks/${endpoint.id}/deliveries/${d.id}/retry`); toast(t('hooks.queued')); draw(); load(); } catch (e) { toast(e.message, 'error'); }
          } }, icon('sync'), h('span', {}, t('hooks.retry'))) : null))) : h('p', { class: 'muted' }, t('hooks.log_empty')));
      } catch (e) { fill(body, h('p', { class: 'error', role: 'alert' }, e.message)); }
    }
    return h('details', { ontoggle: (e) => { if (e.target.open) draw(); } }, h('summary', {}, t('hooks.log')), body);
  }

  function row(endpoint) {
    const state = [
      endpoint.enabled ? null : h('span', { class: 'pill warn' }, endpoint.disabled_reason === 'failing' ? t('hooks.off_failing') : endpoint.disabled_reason === 'gone' ? t('hooks.off_gone') : t('hooks.off')),
      endpoint.readable ? null : h('span', { class: 'pill error' }, t('hooks.unreadable')),
      endpoint.waiting ? h('span', { class: 'pill' }, t('hooks.waiting', { n: endpoint.waiting })) : null,
      endpoint.dead ? h('span', { class: 'pill error' }, t('hooks.dead', { n: endpoint.dead })) : null];
    return h('li', { class: 'hook stack' },
      h('div', { class: 'list-row' },
        h('div', {}, h('strong', {}, endpoint.name), ' ', state, h('p', { class: 'muted hint breakable' }, endpoint.url),
          h('p', { class: 'muted' }, endpoint.events.map(eventName).join(' · '))),
        h('div', { class: 'row' },
          h('button', { class: 'btn small', type: 'button', onclick: (e) => test(endpoint, e.currentTarget) }, t('hooks.test')),
          h('button', { class: 'btn small', type: 'button', onclick: () => rotate(endpoint) }, t('hooks.rotate')),
          h('button', { class: 'btn small danger', type: 'button', 'aria-label': t('common.delete_named', { name: endpoint.name }), onclick: () => remove(endpoint) }, icon('trash')))),
      switchRow(t('hooks.enabled'), endpoint.failing_since ? t('hooks.failing_since', { date: when(endpoint.failing_since) }) : t('hooks.enabled_hint'), endpoint.enabled, async (on) => {
        try { await api('PATCH', `/api/integrations/webhooks/${endpoint.id}`, { enabled: on }); } catch (e) { toast(e.message, 'error'); }
        load();
      }),
      logOf(endpoint));
  }

  async function load() {
    let data;
    try { data = await api('GET', '/api/integrations/webhooks'); } catch (e) { badge.set('offline', { message: e.message }); fill(list, h('p', { class: 'error', role: 'alert' }, e.message)); return; }
    // An address that was switched off because it kept failing (or is gone), or whose signing key cannot be read, is not connected; one that works is active; with none that works, nothing is set up.
    const broken = data.endpoints.filter((e) => !e.readable || (!e.enabled && (e.disabled_reason === 'failing' || e.disabled_reason === 'gone')));
    const working = data.endpoints.filter((e) => e.enabled && e.readable);
    if (broken.length) badge.set('offline', { detail: t('hooks.problem', { n: broken.length }) });
    else if (working.length) badge.set('active', { detail: t('hooks.count', { n: working.length }) });
    else badge.set('off');
    if (!events.length) { events = data.events; drawPicks(); }
    fill(list, data.endpoints.length ? h('ul', { class: 'plain-list hooks' }, data.endpoints.map(row)) : h('p', { class: 'muted' }, t('hooks.none')));
  }

  async function create(e) {
    e.preventDefault();
    if (!picked().length) { toast(t('hooks.pick_event'), 'error'); return; }
    const proof = await confirmIdentity({ action: 'webhook-create', title: t('hooks.confirm_title'), message: t('hooks.confirm_msg'), confirmLabel: t('hooks.add') });
    if (!proof) return;
    try {
      const made = await api('POST', '/api/integrations/webhooks', { name: name.value.trim(), url: url.value.trim(), events: picked(), ...proof });
      name.value = '';
      url.value = '';
      fill(shown, onceBox(made.signing_key, t('hooks.once_title', { name: made.endpoint.name }), t('hooks.once_hint')));
      load();
    } catch (err) { toast(err.message, 'error'); }
  }

  async function test(endpoint, button) {
    button.disabled = true;
    try { const res = await api('POST', `/api/integrations/webhooks/${endpoint.id}/test`); toast(t('hooks.test_ok', { code: res.status })); } catch (e) { toast(e.message, 'error'); }
    button.disabled = false;
  }

  async function rotate(endpoint) {
    const proof = await confirmIdentity({ action: 'webhook-rotate', target: endpoint.id, title: t('hooks.rotate_title'),
      message: t('hooks.rotate_msg', { name: endpoint.name }), confirmLabel: t('hooks.rotate') });
    if (!proof) return;
    try {
      const made = await api('POST', `/api/integrations/webhooks/${endpoint.id}/rotate`, proof);
      fill(shown, onceBox(made.signing_key, t('hooks.once_title', { name: endpoint.name }), t('hooks.once_hint')));
      load();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function remove(endpoint) {
    const proof = await confirmIdentity({ action: 'webhook-delete', target: endpoint.id, title: t('hooks.delete_title'),
      message: t('hooks.delete_msg', { name: endpoint.name }), confirmLabel: t('common.delete') });
    if (!proof) return;
    try { await api('DELETE', `/api/integrations/webhooks/${endpoint.id}`, proof); toast(t('hooks.deleted', { name: endpoint.name })); fill(shown); load(); } catch (e) { toast(e.message, 'error'); }
  }

  load();
  return h('div', { class: 'glass card stack' },
    foldHead('integration-hooks', t('hooks.title'), { open: false, extra: badge.el }),
    h('p', { class: 'muted' }, t('hooks.intro')),
    list, shown,
    h('form', { class: 'stack hook-form', onsubmit: create },
      h('h3', {}, t('hooks.new')),
      h('div', { class: 'two' }, field(t('hooks.url'), url, t('hooks.url_hint')), field(t('hooks.name'), name)),
      h('div', { class: 'field' }, h('span', { class: 'lbl' }, t('hooks.events')), picks),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'submit' }, icon('plus'), h('span', {}, t('hooks.add'))))));
}

/** The cards of the page: its introduction, the cards of connections made elsewhere (`first`: Spoolman and HaspelSync), then API keys and webhooks. */
export function integrationsCards(first = []) {
  return [
    h('p', { class: 'muted page-intro' }, t('integrations.intro')),
    ...first,
    keysCard(),
    hooksCard()];
}
