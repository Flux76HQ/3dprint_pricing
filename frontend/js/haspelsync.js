import { api } from './api.js';
import { spoolIcon } from './filament-ui.js';
import { formatDateTime, formatTime, t } from './i18n.js';
import { confirmDialog, connectionBadge, field, fill, fmt, foldHead, h, toast } from './ui.js';

// HaspelSync (https://github.com/Rdiger-36/HaspelSync) shows what a Bambu Lab printer is doing and what is loaded in it. The server asks it (backend/app/haspelsync.py);
// everything on screen is what that answers, already validated: nothing here reads HaspelSync itself.

const POLL_MS = 5000;           // the server remembers an answer for 4 seconds, so a screen that asks more often only sees the same thing
const STATE_LABEL = { IDLE: 'haspelsync.state_idle', PREPARE: 'haspelsync.state_prepare', RUNNING: 'haspelsync.state_running', PAUSE: 'haspelsync.state_pause',
  FINISH: 'haspelsync.state_finish', FAILED: 'haspelsync.state_failed', CANCEL: 'haspelsync.state_cancel' };
const STATE_BADGE = { RUNNING: 'badge', PREPARE: 'badge', PAUSE: 'badge muted', FINISH: 'badge ok', FAILED: 'badge danger', CANCEL: 'badge danger', IDLE: 'badge muted' };

// --- the settings: where HaspelSync is and the key to reach it -------------------------------------------------------------

/** The HaspelSync card of Settings: the address and the API key, a test, and what is set in .env (shown, not changeable). Only for administrators; it stays hidden for
 * everybody else. The key is typed here, kept sealed on the server and never shown again: a field left empty keeps it. */
export function haspelsyncCard() {
  const card = h('div', { class: 'glass card stack', hidden: true });
  const badge = connectionBadge();                                 // in the heading, so it can be read while the card is folded

  async function draw() {
    let status;
    try { status = await api('GET', '/api/haspelsync'); } catch { return; }          // a convenience: the page works without it
    if (!status.can_configure) { card.hidden = true; return; }
    // Not configured, or asked whether HaspelSync answers (the heading says "checking" until it does); why not, when it does not, is shown in the card.
    const problem = h('p', { class: 'notice error', role: 'alert', hidden: true });
    if (!status.enabled) badge.set('off');
    else {
      badge.set('checking');
      api('GET', '/api/haspelsync/connection').then((c) => {
        badge.set(c.state, { detail: c.state === 'active' ? t('haspelsync.printers', { n: c.printers }) : null, message: c.message });
        problem.textContent = c.state === 'offline' ? c.message : '';
        problem.hidden = c.state !== 'offline';
      }).catch(() => badge.set('offline'));
    }
    const url = h('input', { type: 'text', inputmode: 'url', autocomplete: 'off', spellcheck: 'false', placeholder: 'http://haspelsync:4000', value: status.url || '', disabled: status.url_from_env });
    const key = h('input', { type: 'password', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off', disabled: status.key_from_env,
      placeholder: status.key_set ? '••••••••••••' : 'ams_…' });
    const save = async () => {
      const body = {};
      if (!status.url_from_env) body.url = url.value;
      if (!status.key_from_env && key.value.trim()) body.api_key = key.value.trim();
      try {
        await api('PUT', '/api/haspelsync/settings', body);
        toast(t('haspelsync.saved'));
      } catch (err) { toast(err.message, 'error'); }
      draw();
    };
    const test = async () => {
      try { toast(t('haspelsync.test_ok', { n: (await api('POST', '/api/haspelsync/test')).printers })); } catch (err) { toast(err.message, 'error'); }
    };
    const forget = async () => {
      if (!(await confirmDialog(t('haspelsync.key_remove_confirm'), t('haspelsync.key_remove')))) return;
      try { await api('PUT', '/api/haspelsync/settings', { api_key: null }); toast(t('haspelsync.saved')); } catch (err) { toast(err.message, 'error'); }
      draw();
    };
    const keyHint = status.key_from_env ? t('haspelsync.key_env')
      : !status.key_readable ? t('haspelsync.key_unreadable')
        : status.key_set ? t('haspelsync.key_saved') : t('haspelsync.key_hint');
    fill(card, foldHead('haspelsync', t('haspelsync.title'), { open: false, extra: badge.el }),
      h('p', { class: 'muted' }, t('haspelsync.intro')), problem,
      status.enabled ? h('p', { class: 'hint breakable' }, t('haspelsync.status', { host: status.host })) : null,
      h('div', { class: 'stack' },
        field(t('haspelsync.address'), url, status.url_from_env ? t('haspelsync.address_env') : t('haspelsync.address_hint')),
        field(t('haspelsync.key'), key, keyHint),
        !status.key_from_env && !status.url_from_env ? h('p', { class: 'hint' }, t('haspelsync.key_follows_address')) : null,
        h('div', { class: 'row' },
          status.url_from_env && status.key_from_env ? null : h('button', { class: 'btn primary', type: 'button', onclick: save }, t('common.save')),
          status.ready ? h('button', { class: 'btn', type: 'button', onclick: test }, t('haspelsync.test')) : null,
          status.key_set && !status.key_from_env ? h('button', { class: 'btn', type: 'button', onclick: forget }, t('haspelsync.key_remove')) : null)),
      h('p', { class: 'hint' }, t('haspelsync.where')));
    card.hidden = false;
  }
  draw();
  return card;
}

// --- a printer here is a printer of HaspelSync -----------------------------------------------------------------------------

/** The choice of which printer of HaspelSync a printer here is, for the printer's form. It stays hidden while there is no HaspelSync (a serial number the printer already has is
 * kept as it is) and says why when HaspelSync cannot be asked: the number it has stays selectable either way. `onchange` gets the serial number, or '' for none. */
export function serialField({ label, hint, value, onchange }) {
  const select = h('select', { id: 'f-haspelsync', onchange: (e) => onchange(e.target.value) });
  const note = h('p', { class: 'hint' }, hint);
  const box = h('div', { class: 'field', hidden: true }, h('label', { for: 'f-haspelsync' }, label), select, note);
  const option = (serial, text) => h('option', { value: serial, selected: serial === value }, text);
  const draw = (printers, problem) => {
    const known = new Set(printers.map((p) => p.id));
    fill(select, option('', t('haspelsync.none')), printers.map((p) => option(p.id, `${p.name} (${p.id})`)),
      value && !known.has(value) ? option(value, t('haspelsync.unknown_serial', { serial: value })) : null);
    note.textContent = problem || hint;
    note.className = problem ? 'hint error' : 'hint';
    box.hidden = false;
  };
  api('GET', '/api/haspelsync').then(async (status) => {
    if (!status.enabled) return;
    try { draw(await api('GET', '/api/haspelsync/printers')); } catch (err) { draw([], err.message); }
  }).catch(() => {});
  return box;
}

// --- the filament choice of a calculation: what is in the printers right now -------------------------------------------------

/** The filaments that are loaded in the printers right now, for the filament choice of a calculation: one group per linked printer that HaspelSync answers for (`{ printer_id, name,
 *  connected, slots }`, the loaded slots only, with their label, material, name, vendor, colours, grams left, the Spoolman spool they are and whether they are the one in use). It is asked
 *  after the calculation is open and never waited for, because HaspelSync is another service and may be slow or away: when it does not answer the list is empty and the choice is what it was. */
export async function printerFilaments() {
  try {
    const answer = await api('GET', '/api/haspelsync/live');
    return (answer.printers || []).filter((p) => p.live)
      .map((p) => ({ printer_id: p.printer_id, name: p.name, connected: p.live.connected, slots: (p.live.slots || []).filter((s) => s.loaded) }))
      .filter((group) => group.slots.length);
  } catch { return []; }
}

// --- the Printers page: what each printer is doing now and what is in it ----------------------------------------------------

const duration = (minutes) => (minutes >= 60 ? t('haspelsync.duration_hm', { h: Math.floor(minutes / 60), m: minutes % 60 }) : t('haspelsync.duration_m', { m: minutes }));

/** "Ready at 11:35", or with the day when it is not today. */
function endsAt(iso) {
  const today = new Date(iso).toDateString() === new Date().toDateString();
  return today ? t('haspelsync.ends', { time: formatTime(iso, { hour: '2-digit', minute: '2-digit' }) })
    : t('haspelsync.ends_on', { when: formatDateTime(iso, { weekday: 'short', hour: '2-digit', minute: '2-digit' }) });
}

/** A bar for a percentage; `label` is what a screen reader hears. The width is set from here because the page may not carry an inline style. */
function bar(percent, label) {
  const meter = h('div', { class: 'meter', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': percent, 'aria-label': label }, h('span'));
  meter.firstChild.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  return meter;
}

function slotRow(slot, use) {
  if (!slot.loaded) return h('li', { class: 'slot slot-none' }, h('span', { class: 'slot-label' }, slot.label), h('span', { class: 'muted' }, t('haspelsync.slot_empty')));
  const colours = slot.colours || [];
  const what = [slot.material, slot.name].filter(Boolean).join(' · ');
  const spool = h('span', { class: 'slot-spool', title: colours.length > 1 ? colours.join(', ') : null }, spoolIcon(colours[0] || null, 28));
  let left;
  if (slot.linked && slot.remaining_g != null) {
    const text = slot.remaining_pct != null ? t('haspelsync.slot_left', { grams: fmt(slot.remaining_g, 0), pct: slot.remaining_pct }) : t('haspelsync.slot_left_g', { grams: fmt(slot.remaining_g, 0) });
    left = [h('span', {}, text), slot.remaining_pct != null ? bar(slot.remaining_pct, t('haspelsync.meter', { left: fmt(slot.remaining_g, 0), total: fmt(slot.initial_g ?? slot.remaining_g, 0) })) : null];
  } else left = [h('span', { class: 'muted' }, t('haspelsync.slot_unlinked'))];
  const uses = use ? h('span', { class: 'muted' }, use.used_g != null ? t('haspelsync.slot_use', { used: fmt(use.used_g, 0), needed: fmt(use.needed_g, 0) }) : t('haspelsync.slot_need', { needed: fmt(use.needed_g, 0) })) : null;
  return h('li', { class: `slot${slot.active ? ' active' : ''}` },
    h('span', { class: 'slot-label' }, slot.label), spool,
    h('div', { class: 'slot-main' },
      h('span', { class: 'slot-what' }, what || '—', slot.vendor ? h('span', { class: 'muted' }, ` · ${slot.vendor}`) : null,
        slot.active ? h('span', { class: 'badge' }, t('haspelsync.slot_active')) : null),
      ...left, uses));
}

function unitLine(unit) {
  const parts = [t('haspelsync.ams', { id: unit.id })];
  if (unit.humidity != null) parts.push(unit.humidity_pct != null ? t('haspelsync.humidity_pct', { level: unit.humidity, pct: unit.humidity_pct }) : t('haspelsync.humidity', { level: unit.humidity }));
  if (unit.temperature != null) parts.push(t('haspelsync.temperature', { value: unit.temperature }));
  if (unit.drying) parts.push(unit.drying_min ? t('haspelsync.drying_left', { time: duration(unit.drying_min) }) : t('haspelsync.drying'));
  return h('li', {}, parts.join(' · '));
}

function jobBlock(job) {
  if (!job || (!job.busy && !job.name)) return h('p', { class: 'muted' }, t('haspelsync.no_job'));
  const facts = [
    job.layer != null ? (job.total_layers ? t('haspelsync.layer', { layer: job.layer, total: job.total_layers }) : t('haspelsync.layer_only', { layer: job.layer })) : null,
    job.busy && job.remaining_min != null ? t('haspelsync.remaining', { time: duration(job.remaining_min) }) : null,
    job.busy && job.ends_at ? endsAt(job.ends_at) : null,
  ].filter(Boolean);
  return h('div', { class: 'job stack' },
    h('div', { class: 'job-name' }, job.name || '—', job.preparing ? h('span', { class: 'muted' }, ` · ${t('haspelsync.preparing')}`) : null),
    job.progress_pct != null ? h('div', { class: 'job-bar' }, bar(job.progress_pct, t('haspelsync.progress_label')), h('strong', {}, `${job.progress_pct}%`)) : null,
    facts.length ? h('ul', { class: 'stat-chips' }, facts.map((f) => h('li', {}, f))) : null);
}

function printerCard(entry) {
  const view = entry.live;
  if (!view) {
    return h('article', { class: 'glass card item live-card' }, h('div', { class: 'item-head' }, h('div', { class: 'grow' }, h('h3', {}, entry.name))),
      h('p', { class: 'notice error', role: 'alert' }, entry.message));
  }
  const job = view.job || {};
  const badge = !view.connected ? h('span', { class: 'badge muted' }, t('haspelsync.offline'))
    : h('span', { class: STATE_BADGE[job.state] || 'badge muted' }, t(STATE_LABEL[job.state] || 'haspelsync.state_unknown'));
  const uses = new Map((view.uses || []).map((u) => [u.slot, u]));
  const loaded = (view.slots || []).filter((s) => s.loaded).length;
  return h('article', { class: 'glass card item live-card' },
    h('div', { class: 'item-head' }, h('div', { class: 'grow' }, h('h3', {}, entry.name, badge),
      view.last_report ? h('p', { class: 'muted' }, t('haspelsync.last_report', { time: formatTime(view.last_report, { hour: '2-digit', minute: '2-digit' }) })) : null)),
    !view.connected ? null : jobBlock(job),
    view.monitoring ? null : h('p', { class: 'notice warn', role: 'status' }, t('haspelsync.monitoring_off')),
    (view.slots || []).length ? h('div', { class: 'stack' }, h('h4', {}, t('haspelsync.filament'), h('span', { class: 'muted' }, ` · ${t('haspelsync.loaded', { n: loaded })}`)),
      h('ul', { class: 'slot-list' }, view.slots.map((slot) => slotRow(slot, uses.get(slot.label))))) : null,
    (view.ams || []).length ? h('ul', { class: 'stat-chips unit-chips' }, view.ams.map(unitLine)) : null);
}

/** The running print and the filament of every printer here that names a printer of HaspelSync, asked again every few seconds for as long as the page is on screen. It stays
 * hidden while there is no HaspelSync or no printer that names one, so an installation without it looks as before. */
export function livePanel() {
  const panel = h('section', { class: 'live-panel', hidden: true, 'aria-label': t('haspelsync.live_title') });
  let timer = null;
  let seen = false;
  let busy = false;                // one round at a time: coming back to the tab while one is still on its way must not start a second chain

  async function load() {
    let answer;
    try { answer = await api('GET', '/api/haspelsync/live'); } catch { return; }          // a convenience: the page works without it, and the last picture stays
    if (!answer.enabled || !answer.printers.length) { panel.hidden = true; return; }
    fill(panel, h('h2', {}, t('haspelsync.live_title')), h('div', { class: 'cards' }, answer.printers.map(printerCard)));
    panel.hidden = false;
  }
  const tick = async () => {
    if (busy) return;
    clearTimeout(timer);
    if (panel.isConnected) seen = true;
    else if (seen) { document.removeEventListener('visibilitychange', onVisible); return; }          // it was on the page and is gone: stop asking
    busy = true;
    try { if (!document.hidden) await load(); } finally { busy = false; }
    timer = setTimeout(tick, POLL_MS);
  };
  const onVisible = () => { if (!document.hidden) tick(); };                   // back on this tab: do not wait for the next round
  document.addEventListener('visibilitychange', onVisible);
  tick();
  return panel;
}
