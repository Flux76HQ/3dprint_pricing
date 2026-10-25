import { aiLogCard, aiSettingsCard } from './ai-images.js';
import { api, confirmWithPasskey, createPasskey, downloadFile, sendFile, upload } from './api.js';
import { filamentLibraryCards } from './filament-library.js';
import { iosSteps, installState, onInstallChange, promptInstall } from './install.js';
import { formatDate, formatDateTime, formatTime, t } from './i18n.js';
import { langSwitch } from './langswitch.js';
import { confirmIdentity, passwordCard } from './password.js';
import { currentSubscription, disablePush, enablePush, forgetPush, pushSupport, thisDeviceFingerprint } from './push.js';
import { applyNavGlass, confirmDialog, fmt, ROUNDINGS, field, fill, h, icon, navStyle, numberInput, saveBlob, switchRow, toast, versionLabel } from './ui.js';
import { checkForUpdate, loadedVersion } from './updates.js';

// [value, label key]: labels are looked up when drawn, so they follow the language.
export const ACCENTS = [
  ['#6c5ce7', 'accent.violet'], ['#0a84ff', 'accent.blue'], ['#5e5ce6', 'accent.indigo'], ['#bf5af2', 'accent.purple'],
  ['#e0457b', 'accent.pink'], ['#e5484d', 'accent.red'], ['#d9730d', 'accent.orange'], ['#2f9e44', 'accent.green'], ['#0c9aa6', 'accent.teal'],
];
const THEMES = [['system', 'theme.system'], ['light', 'theme.light'], ['dark', 'theme.dark']];

function installCard() {
  const body = h('div', { class: 'stack' });
  const draw = () => {
    const state = installState();
    if (state === 'installed') body.replaceChildren(h('p', { class: 'status-line' }, t('install.installed')));
    else if (state === 'prompt') {
      body.replaceChildren(h('p', {}, t('install.intro')),
        h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: async () => { await promptInstall(); draw(); } }, t('install.app'))));
    } else if (state === 'ios') {
      body.replaceChildren(h('p', {}, iosSteps()), h('p', { class: 'muted' }, t('install.ios_push')));
    } else {
      body.replaceChildren(h('p', { class: 'muted' }, t('install.unavailable')));
    }
  };
  draw();
  let seen = false;
  const off = onInstallChange(() => {            // stop listening once this screen has been replaced
    if (body.isConnected) seen = true; else if (seen) { off(); return; }
    draw();
  });
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('install.app')), body);
}

function updatesCard() {
  const v = loadedVersion();
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('updates.title')),
    h('p', { class: 'status-line' }, t('updates.running'), ' ', h('strong', { id: 'app-version' }, v ? versionLabel(v) : t('updates.unknown'))),
    h('p', { class: 'muted' }, t('updates.auto')),
    h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: () => checkForUpdate({ manual: true }) }, t('updates.check'))));
}

const DEFAULT_QUIET = () => ({ enabled: false, start: '22:00', end: '07:00', tz: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Amsterdam' });

// The thresholds of the low-stock notification: one for every kind of filament and an optional one per material. Which kinds
// are watched is chosen on the rolls. Saving a field does not redraw the card (that would take the focus from the field you
// tab to); only a refused value does.
function lowStockRows(ctx, stock, redraw) {
  const low = { threshold_g: 500, materials: {}, ...(ctx.prefs.low_stock || {}) };
  const save = async (change) => {
    const saved = await ctx.setPrefs({ low_stock: { ...low, ...change } });
    if (saved) Object.assign(low, change); else redraw();
    return saved;
  };
  const whole = (v) => (/^\d+$/.test(v) ? Number(v) : v);                // anything else goes to the server, which says what is wrong
  const own = [];
  const rows = [h('strong', {}, t('notify.low_stock')), h('p', { class: 'muted' }, t('notify.low_stock_hint')),
    field(t('notify.low_default'), h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', value: low.threshold_g,
      onchange: async (e) => { if (await save({ threshold_g: whole(e.target.value.trim()) })) own.forEach((i) => { i.placeholder = String(low.threshold_g); }); } }),
    t('notify.low_default_hint'))];
  const materials = ((stock && stock.materials) || []).filter((m) => m.key);
  if (!materials.length) { rows.push(h('p', { class: 'muted' }, t('notify.low_none'))); return rows; }
  rows.push(h('strong', {}, t('notify.low_materials')), h('p', { class: 'muted' }, t('notify.low_materials_hint')));
  for (const m of materials) {
    const input = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', value: low.materials[m.key] ?? '', placeholder: String(low.threshold_g),
      onchange: (e) => {
        const value = e.target.value.trim();
        const next = { ...low.materials };
        if (value === '') delete next[m.key]; else next[m.key] = whole(value);
        save({ materials: next });
      } });
    own.push(input);
    rows.push(field(m.material, input));
  }
  return rows;
}

// `ctx.prefs` is read when needed, never copied: a copy goes stale the moment a setting is saved.
function notificationsCards(ctx) {
  const { setPrefs } = ctx;
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  const quietBody = h('div', { class: 'stack' });
  const quietCard = h('div', { class: 'glass card stack', hidden: true }, h('h2', {}, t('notify.quiet')), quietBody);
  let lastResult = '';                                    // survives the redraw that refreshes the device list
  let lastCheck = null;                                   // ... and so does the answer of the connection check

  async function draw() {
    let cfg;
    try { cfg = await api('GET', '/api/push/config'); } catch (e) { body.replaceChildren(h('p', { class: 'error' }, e.message)); return; }
    const support = pushSupport();
    const notes = {
      'ios-install': t('notify.ios_install'),
      unsupported: t('notify.unsupported'),
      denied: t('notify.denied'),
    };
    if (!cfg.configured) { body.replaceChildren(h('p', { class: 'muted' }, t('notify.not_configured'))); return; }
    if (!support.ok) { body.replaceChildren(h('p', { class: 'muted' }, notes[support.reason])); return; }

    const sub = await currentSubscription().catch(() => null);
    const rows = [switchRow(t('notify.this_device'),
      t('notify.this_device_hint'), !!sub, async (on) => {
        try { if (on) await enablePush(cfg.public_key); else await disablePush(); } catch (e) { toast(e.message, 'error'); }
        draw();
      })];

    // Quiet hours are the account's, so they are there whether or not this device is signed up.
    const quiet = { ...DEFAULT_QUIET(), ...(ctx.prefs.quiet_hours || {}) };
    const saveQuiet = async (change) => {
      const saved = await setPrefs({ quiet_hours: { ...quiet, ...change } });
      if (saved) Object.assign(quiet, change);       // later edits build on what was really saved
      else draw();                                    // refused (e.g. unknown timezone): show the saved values again
    };
    quietBody.replaceChildren(
      switchRow(t('notify.quiet_on'), t('notify.quiet_hint'), !!quiet.enabled, (on) => saveQuiet({ enabled: on })),
      h('div', { class: 'time-row' },
        field(t('notify.from'), h('input', { type: 'time', value: quiet.start, onchange: (e) => saveQuiet({ start: e.target.value }) })),
        field(t('notify.to'), h('input', { type: 'time', value: quiet.end, onchange: (e) => saveQuiet({ end: e.target.value }) }))),
      field(t('notify.timezone'), h('input', { type: 'text', value: quiet.tz, autocomplete: 'off', spellcheck: 'false',
        onchange: (e) => saveQuiet({ tz: e.target.value.trim() }) }), t('notify.timezone_hint')));
    quietCard.hidden = false;

    if (sub) {
      const result = h('p', { class: 'status-line', role: 'status' }, lastResult);
      const stock = await api('GET', '/api/spools/stock').catch(() => null);      // the materials there are, for their own thresholds
      rows.push(
        switchRow(t('notify.release'), t('notify.release_hint'), ctx.prefs.notify_release !== false,
          (on) => setPrefs({ notify_release: on })),
        ...lowStockRows(ctx, stock, draw),
        h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: async () => {
          try {
            const r = await api('POST', '/api/push/test');
            if (r.deferred_until) lastResult = t('notify.test_deferred', { time: formatTime(r.deferred_until, { hour: '2-digit', minute: '2-digit' }) });
            else {
              const failures = (r.results || []).filter((x) => !x.ok).map((x) => `${x.device}: ${x.reason}`);
              lastResult = [r.sent > 0 ? t('notify.test_sent', { n: r.sent }) : t('notify.test_failed'), ...failures].join('\n');
            }
            draw();
          } catch (e) { lastResult = e.message; draw(); }
        } }, t('notify.test'))),
        result,
        h('p', { class: 'muted' }, t('notify.ttl', { hours: cfg.ttl_hours })));
    }
    rows.push(connectionCheck(), await devicesList(draw));
    fill(body, ...rows);
  }
  // Can the server reach the push services at all? Shows which step fails, so "notifications do not arrive" has an answer.
  function connectionCheck() {
    const list = h('ul', { class: 'plain-list', 'aria-live': 'polite' });
    const hint = h('p', { class: 'muted', hidden: true }, t('notify.check_hint'));
    const show = ({ vapid, hosts }) => {                    // the keys first: a bad key fails before the network is even tried
      const rows = [vapid, ...hosts];
      list.replaceChildren(...rows.map((x) => h('li', { class: x.ok ? 'muted' : 'error' }, `${x.ok ? '✓' : '✗'} ${x.message}`)));
      hint.hidden = rows.every((x) => x.ok);
    };
    if (lastCheck) show(lastCheck);
    const button = h('button', { class: 'btn', type: 'button', onclick: async () => {
      button.disabled = true;
      list.replaceChildren(h('li', { class: 'muted' }, t('common.loading')));
      try { lastCheck = await api('POST', '/api/push/check'); show(lastCheck); } catch (e) { list.replaceChildren(h('li', { class: 'error' }, e.message)); }
      button.disabled = false;
    } }, t('notify.check'));
    return h('div', { class: 'stack' }, h('div', { class: 'row' }, button), list, hint);
  }

  draw();
  return [h('div', { class: 'glass card stack' }, h('h2', {}, t('notify.title')), body), quietCard];
}

const when = (iso) => formatDateTime(iso, { dateStyle: 'short', timeStyle: 'short' });

/** Every device that receives notifications, with how the last one went. */
async function devicesList(redraw) {
  let devices;
  try { devices = (await api('GET', '/api/push/devices')).devices; } catch { return h('p', { class: 'muted' }, t('devices.load_failed')); }
  const mine = await thisDeviceFingerprint().catch(() => null);
  if (!devices.length) return h('p', { class: 'muted' }, t('devices.none'));
  return h('div', { class: 'stack' }, h('h3', {}, t('devices.title', { n: devices.length })),
    h('ul', { class: 'devices', 'aria-label': t('devices.label') }, devices.map((d) => h('li', {},
      h('div', {},
        h('strong', {}, d.name), d.fingerprint === mine ? h('span', { class: 'tag' }, t('devices.this')) : null,
        h('p', { class: 'muted' }, t('devices.added', { when: when(d.created_at) })),
        d.last_error ? h('p', { class: 'error' }, t('devices.last_failed', { when: when(d.last_error_at), reason: d.last_error }))
          : d.last_ok_at ? h('p', { class: 'muted' }, t('devices.last_ok', { when: when(d.last_ok_at) }))
            : h('p', { class: 'muted' }, t('devices.never'))),
      h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
        if (!(await confirmDialog(t('devices.remove_confirm', { name: d.name }), t('common.delete')))) return;
        try {
          await api('DELETE', `/api/push/devices/${d.id}`);
          if (d.fingerprint === mine) await disablePush().catch(() => {});
        } catch (e) { toast(e.message, 'error'); }
        redraw();
      } }, t('common.delete'))))));
}

const megabytes = (bytes) => `${fmt(bytes / 1048576, 1)} MB`;
const seconds = (ms) => fmt(ms / 1000, 1);
const TIMING_KEY = 'pp-restore-timing';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Backup and restore of everything entered (settings, printers, tariffs, packaging, parts, accessories, rolls, calculations).
 *  Both show what they are doing. A restore is a job on the server (`/api/backup/jobs`): once the file is up, leaving the page stops
 *  nothing, and the card picks the job up again when it is shown. */
function backupCard() {
  let withFiles = false;
  const status = h('p', { class: 'status-line', role: 'status' });
  const picker = h('input', { type: 'file', accept: '.zip,.json,application/zip,application/json', hidden: true, 'aria-label': t('backup.restore') });
  const label = h('strong');
  const note = h('p', { class: 'muted' });
  const bar = h('progress', { class: 'op-bar', max: 100 });
  const box = h('div', { class: 'op-progress', role: 'status', hidden: true }, h('div', { class: 'row' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), label), bar, note);
  const downloadButton = h('button', { class: 'btn primary', type: 'button', onclick: () => download() }, t('backup.download'));
  const restoreButton = h('button', { class: 'btn', type: 'button', onclick: () => picker.click() }, t('backup.restore'));

  /** `value` 0-100 fills the bar; null leaves it moving without a figure (the server is busy and cannot say how far it is). */
  function show(text, value = null, detail = '') {
    label.textContent = text;
    note.textContent = detail;
    if (value == null) bar.removeAttribute('value'); else bar.value = Math.max(0, Math.min(100, value));
    box.hidden = false;
  }
  function idle() {
    box.hidden = true;
    downloadButton.disabled = false;
    restoreButton.disabled = false;
  }
  function busy() {
    downloadButton.disabled = true;
    restoreButton.disabled = true;
    status.textContent = '';
  }

  async function download() {
    busy();
    show(withFiles ? t('backup.making_files') : t('backup.making'));                    // the server is putting it together: nothing to count yet
    const began = performance.now();
    let answered = null;
    try {
      const { blob, name } = await downloadFile(`/api/backup${withFiles ? '?files=1' : ''}`, {
        onProgress: (got, total) => {
          if (answered == null) answered = performance.now();                           // the first answer: the server is done, the file starts to arrive
          show(t('backup.receiving'), total ? (got / total) * 100 : null, total ? t('backup.of', { done: megabytes(got), total: megabytes(total) }) : megabytes(got));
        },
      });
      saveBlob(blob, name);
      status.textContent = `${t('backup.downloaded', { name })} ${t('backup.timing_download', { made: seconds(answered - began), got: seconds(performance.now() - answered), size: megabytes(blob.size) })}`;
    } catch (e) { toast(e.message, 'error'); }
    idle();
  }

  async function restore(file) {
    busy();
    let staged;
    const began = performance.now();
    let sentAt = began;
    try {
      show(t('backup.sending'), 0);
      staged = await sendFile('/api/backup/stage', file, {
        onProgress: (sent, total) => show(t('backup.sending'), (sent / total) * 100, t('backup.of', { done: megabytes(sent), total: megabytes(total) })),
        onSent: () => { sentAt = performance.now(); show(t('backup.checking')); },    // all of it is up; the server reads it through before anything is replaced
      });
    } catch (e) { idle(); toast(e.message, 'error'); return; }
    box.hidden = true;
    const uploadTimes = { up: seconds(sentAt - began), stage: seconds(performance.now() - sentAt), size: megabytes(file.size) };
    const s = staged.summary;
    const when = s.created_at ? formatDateTime(s.created_at, { dateStyle: 'medium', timeStyle: 'short' }) : '?';
    const files = s.files ? t('backup.with_files', { n: s.files }) : '';
    const ok = await confirmDialog(t('backup.confirm', { when, printers: s.printers, tariffs: s.tariffs, packaging: s.packaging, parts: s.parts || 0, accessories: s.accessories || 0, library: s.library || 0,
      spools: s.spools, projects: s.projects, orders: s.orders || 0, customers: s.customers || 0, files }), t('backup.restore_now'));
    if (!ok) { api('DELETE', `/api/backup/stage/${staged.token}`).catch(() => {}); idle(); return; }
    try {
      const { job } = await api('POST', '/api/backup/jobs', { token: staged.token });
      follow(job, uploadTimes);
    } catch (e) { idle(); toast(e.message, 'error'); }
  }

  /** Shows a restore job until it ends. Stops quietly when the card is gone: the job does not depend on it. */
  async function follow(job, uploadTimes) {
    busy();
    while (job.status === 'running') {
      if (!box.isConnected) return;
      const counting = job.steps > 0;
      show(job.phase === 'replacing' ? t('backup.replacing') : t('backup.verifying'), counting ? (job.step / job.steps) * 100 : null,
        [counting ? t('backup.step_files', { n: job.step, total: job.steps }) : '', t('backup.background')].filter(Boolean).join(' · '));
      await sleep(1000);
      try { job = (await api('GET', '/api/backup/jobs/latest')).job || { status: 'gone' }; } catch { /* a dropped connection does not stop the restore: ask again */ }
    }
    if (!box.isConnected) return;
    idle();
    if (job.status === 'gone') return;
    try { await api('DELETE', `/api/backup/jobs/${job.id}`); } catch { return; }           // seen: not shown again (and no reload loop if this fails)
    if (job.status === 'done') {
      toast(t('backup.restored'));
      try {                                                                             // where the time went, shown again after the reload
        const server = t('backup.timing_server', { check: seconds((job.checking_seconds || 0) * 1000), replace: seconds((job.replacing_seconds || 0) * 1000) });
        sessionStorage.setItem(TIMING_KEY, uploadTimes ? `${t('backup.timing_upload', uploadTimes)} ${server}` : server);
      } catch { /* no storage: the restore is done all the same */ }
      setTimeout(() => window.location.reload(), 600);                                  // settings and language may have changed
    } else {
      status.textContent = job.message || t('api.error_status', { status: 500 });
      toast(status.textContent, 'error');
    }
  }

  try {
    const timing = sessionStorage.getItem(TIMING_KEY);
    if (timing) { status.textContent = `${t('backup.restored')} ${timing}`; sessionStorage.removeItem(TIMING_KEY); }
  } catch { /* nothing to show */ }
  picker.addEventListener('change', () => { const file = picker.files[0]; picker.value = ''; if (file) restore(file); });
  api('GET', '/api/backup/jobs/latest').then(({ job }) => { if (job) follow(job); }).catch(() => {});      // a restore started before the page was left
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('backup.title')),
    h('p', { class: 'muted' }, t('backup.intro')),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', class: 'toggle', role: 'switch', onchange: (e) => { withFiles = e.target.checked; } }), t('backup.files')),
    h('p', { class: 'hint' }, t('backup.files_hint')),
    h('div', { class: 'row' }, downloadButton, restoreButton, picker),
    box,
    status,
    h('p', { class: 'muted' }, t('backup.not_included')));
}

/** Back to factory settings: everything is deleted, including the passkeys, and the app is set up again from the start. */
function resetCard() {
  async function reset() {
    const proof = await confirmIdentity({ action: 'factory-reset', title: t('reset.confirm_title'), message: t('reset.confirm_msg'), confirmLabel: t('reset.now') });
    if (!proof) return;
    try {
      await api('POST', '/api/system/reset', proof);
    } catch (e) { toast(e.message, 'error'); return; }
    try { localStorage.removeItem('pp-prefs'); } catch { /* private mode */ }               // the look of the old account must not be the look of the new one
    await forgetPush().catch(() => {});
    history.replaceState(null, '', window.location.pathname);                              // not back on the settings page afterwards
    window.location.reload();                                                               // the server now says "not set up": the welcome screen follows
  }
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('reset.title')),
    h('p', { class: 'muted' }, t('reset.intro')),
    h('div', { class: 'row' }, h('button', { class: 'btn danger', type: 'button', id: 'factory-reset', onclick: reset }, t('reset.button'))));
}

// The company details that go on an invoice. Each field is saved when it is left; `ctx.prefs` is read at that moment, never copied.
const COMPANY_TEXT = [['name', 'company.name'], ['address', 'company.address'], ['postal_code', 'company.postal_code'], ['city', 'company.city'],
  ['country', 'company.country'], ['email', 'company.email'], ['phone', 'company.phone'], ['website', 'company.website'], ['kvk', 'company.kvk'],
  ['vat_id', 'company.vat_id'], ['iban', 'company.iban'], ['bic', 'company.bic']];

function companyCard(ctx) {
  const current = () => ({ payment_days: 14, invoice_language: 'nl', ...(ctx.prefs.business || {}) });
  const save = async (key, el, value) => {
    if (!(await ctx.setPrefs({ business: { ...current(), [key]: value } }))) el.value = current()[key] ?? '';      // refused: show what is saved
  };
  const text = ([key, label], attrs = {}) => {
    const input = h('input', { type: 'text', value: current()[key] ?? '', autocomplete: 'off', ...attrs, onchange: () => save(key, input, input.value.trim()) });
    return field(t(label), input);
  };
  const days = h('input', { type: 'text', inputmode: 'numeric', value: current().payment_days, autocomplete: 'off',
    onchange: () => save('payment_days', days, /^\d+$/.test(days.value.trim()) ? Number(days.value.trim()) : days.value.trim()) });
  const language = h('select', { onchange: () => save('invoice_language', language, language.value) },
    [['nl', 'Nederlands'], ['en', 'English']].map(([v, l]) => h('option', { value: v, selected: current().invoice_language === v }, l)));
  const numberFormat = h('input', { type: 'text', maxlength: 40, value: current().invoice_number_format || '{JJJJ}-{NNNN}', autocomplete: 'off', spellcheck: false,
    onchange: () => save('invoice_number_format', numberFormat, numberFormat.value.trim()) });
  const note = h('textarea', { rows: 3, maxlength: 500, onchange: () => save('note', note, note.value.trim()) }, current().note || '');
  const by = Object.fromEntries(COMPANY_TEXT.map((f) => [f[0], f]));
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('company.title')), h('p', { class: 'muted' }, t('company.hint')),
    text(by.name), text(by.address),
    h('div', { class: 'two' }, text(by.postal_code), text(by.city)),
    text(by.country),
    h('div', { class: 'two even' }, text(by.email, { type: 'email', inputmode: 'email' }), text(by.phone, { type: 'tel', inputmode: 'tel' })),
    text(by.website, { inputmode: 'url' }),
    h('div', { class: 'two even' }, text(by.kvk), text(by.vat_id)),
    h('div', { class: 'two' }, text(by.iban), text(by.bic)),
    h('div', { class: 'two even' }, field(t('company.payment_days'), days), field(t('company.language'), language)),
    field(t('company.number_format'), numberFormat, t('company.number_format_hint')),
    field(t('company.note'), note, t('company.note_hint')));
}

// The QR code under the invoice: on or off, and what it holds: the SEPA transfer (the default) or an own payment link with the invoice filled in.
function qrCard(ctx) {
  const current = () => ({ payment_days: 14, invoice_language: 'nl', ...(ctx.prefs.business || {}) });
  const link = h('input', { type: 'url', maxlength: 500, inputmode: 'url', autocomplete: 'off', spellcheck: false, placeholder: t('company.qr_link_ph'),
    value: current().invoice_qr_link || '', disabled: current().invoice_qr === false,
    onchange: async () => {
      if (!(await ctx.setPrefs({ business: { ...current(), invoice_qr_link: link.value.trim() } }))) link.value = current().invoice_qr_link || '';      // refused: show what is saved
    } });
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('company.qr_title')),
    switchRow(t('company.qr'), t('company.qr_hint'), current().invoice_qr !== false, async (on) => {
      await ctx.setPrefs({ business: { ...current(), invoice_qr: on } });
      link.disabled = !on;
    }),
    field(t('company.qr_link'), link, t('company.qr_link_hint')));
}

// The logo at the top left of the invoice (and where a Word template says {{logo}}): one PNG or JPEG.
function invoiceLogoCard() {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  let lastError = '';
  async function draw() {
    let info;
    try { info = await api('GET', '/api/invoice-logo'); } catch (e) { body.replaceChildren(h('p', { class: 'error' }, e.message)); return; }
    const logo = info.logo;
    const file = h('input', { type: 'file', accept: 'image/png,image/jpeg', 'aria-label': t('logo.choose'), onchange: async () => {
      const chosen = file.files[0];
      if (!chosen) return;
      const form = new FormData();
      form.append('file', chosen);
      try { await upload('/api/invoice-logo', form); lastError = ''; toast(t('logo.saved')); } catch (e) { lastError = e.message; }
      draw();
    } });
    fill(body,
      h('p', { class: 'muted' }, t('logo.intro')),
      logo ? h('div', { class: 'list-row' },
        h('img', { class: 'logo-preview', src: `/api/invoice-logo/file?v=${encodeURIComponent(logo.uploaded_at)}`, alt: t('logo.alt') }),
        h('div', { class: 'row' }, h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
          if (!(await confirmDialog(t('logo.remove_confirm'), t('common.delete')))) return;
          try { await api('DELETE', '/api/invoice-logo'); lastError = ''; draw(); } catch (e) { toast(e.message, 'error'); }
        } }, t('common.delete'))))
        : h('p', { class: 'muted' }, t('logo.none')),
      field(logo ? t('logo.replace') : t('logo.choose'), file, t('logo.file_hint')),
      h('p', { class: 'error', role: 'alert', hidden: !lastError }, lastError));
  }
  draw();
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('logo.title')), body);
}

// The invoice template: a Word file with {{placeholders}} or a PDF used as letter paper. The invoice is made from it (or, without one,
// from the built-in layout) when an order asks for it.
function invoiceTemplateCard() {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  let lastError = '';

  async function draw() {
    let info;
    try { info = await api('GET', '/api/invoice-template'); } catch (e) { body.replaceChildren(h('p', { class: 'error' }, e.message)); return; }
    const tpl = info.template;
    const top = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', value: tpl ? tpl.margin_top_mm : info.defaults.margin_top_mm });
    const bottom = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', value: tpl ? tpl.margin_bottom_mm : info.defaults.margin_bottom_mm });
    const status = h('p', { class: 'error', role: 'alert', hidden: !lastError }, lastError);
    const file = h('input', { type: 'file', accept: '.docx,.pdf', 'aria-label': t('invoice_tpl.choose'), onchange: async () => {
      const chosen = file.files[0];
      if (!chosen) return;
      const form = new FormData();
      form.append('file', chosen);
      form.append('margin_top_mm', top.value.trim());
      form.append('margin_bottom_mm', bottom.value.trim());
      try { await upload('/api/invoice-template', form); lastError = ''; toast(t('invoice_tpl.saved')); } catch (e) { lastError = e.message; }
      draw();
    } });
    const margins = h('div', { class: 'two even' }, field(t('invoice_tpl.margin_top'), top), field(t('invoice_tpl.margin_bottom'), bottom));
    const download = async (path) => {
      try { const { blob, name } = await downloadFile(path); saveBlob(blob, name); } catch (e) { toast(e.message, 'error'); }
    };
    fill(body,
      tpl ? h('div', { class: 'list-row' },
        h('div', {}, h('strong', {}, tpl.filename), h('p', { class: 'muted' }, `${tpl.kind === 'docx' ? t('invoice_tpl.word') : t('invoice_tpl.pdf')} · ${formatDate(tpl.uploaded_at, { dateStyle: 'medium' })}`)),
        h('div', { class: 'row' },
          h('button', { class: 'btn small', type: 'button', onclick: () => download('/api/invoice-template/download') }, t('invoice_tpl.download')),
          h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
            if (!(await confirmDialog(t('invoice_tpl.remove_confirm'), t('common.delete')))) return;
            try { await api('DELETE', '/api/invoice-template'); lastError = ''; draw(); } catch (e) { toast(e.message, 'error'); }
          } }, t('common.delete'))))
        : h('p', { class: 'muted' }, t('invoice_tpl.none')),
      h('p', {}, t('invoice_tpl.intro_word')), h('p', {}, t('invoice_tpl.intro_pdf')),
      h('div', { class: 'row' }, h('button', { class: 'btn small', type: 'button', onclick: () => download('/api/invoice-template/sample') }, t('invoice_tpl.sample'))),
      field(tpl ? t('invoice_tpl.replace') : t('invoice_tpl.choose'), file, t('invoice_tpl.file_hint')),
      margins, h('p', { class: 'hint' }, t('invoice_tpl.margin_hint')),
      ...(tpl && tpl.kind === 'pdf' ? [h('div', { class: 'row' }, h('button', { class: 'btn small', type: 'button', onclick: async () => {
        try {
          await api('PATCH', '/api/invoice-template', { margin_top_mm: top.value.trim(), margin_bottom_mm: bottom.value.trim() });
          lastError = ''; toast(t('common.saved')); draw();
        } catch (e) { toast(e.message, 'error'); }
      } }, t('invoice_tpl.save_margins')))] : []),                       // not `null`: replaceChildren would write the word "null"
      status,
      h('details', {}, h('summary', {}, t('invoice_tpl.fields')),
        h('p', { class: 'muted' }, t('invoice_tpl.fields_hint')),
        h('p', {}, h('code', {}, info.placeholders.map((name) => `{{${name}}}`).join('  ')))));
  }
  draw();
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('invoice_tpl.title')), body);
}

// The parts of the settings, in the order of the sub menu: [route, label key]. "Zakelijk" is only there when it is switched on.
const SECTIONS = [['algemeen', 'settings.tab_general'], ['weergave', 'settings.tab_appearance'], ['beveiliging', 'settings.tab_security'],
  ['zakelijk', 'settings.tab_business'], ['filamenten', 'settings.tab_filaments'], ['notificaties', 'settings.tab_notifications'], ['ai', 'settings.tab_ai'], ['systeem', 'settings.tab_system']];

export function settingsView(ctx, requested) {
  const { setPrefs, user, highlightPasskey } = ctx;
  const businessOn = () => !!ctx.prefs.business_mode;
  const shown = () => SECTIONS.filter(([key]) => (key !== 'zakelijk' || businessOn()) && (key !== 'ai' || ctx.aiImages));   // "AI-afbeeldingen" only when .env switches it on
  const wanted = requested === 'backup' ? 'systeem' : requested;                          // the address this part had before it was renamed
  const section = shown().some(([key]) => key === wanted) ? wanted : 'algemeen';
  // The address says what is shown: a part that is not there (Business while it is off) must not stay in the URL, or clicking its tab later would change nothing.
  if (requested && requested !== section) history.replaceState(null, '', `#/instellingen/${section}`);
  let vatTimer = null;
  const security = h('div', { class: 'stack' });
  const codesBox = h('div');

  const themeButtons = h('div', { class: 'segmented', role: 'group', 'aria-label': t('appearance.title') });
  const accentButtons = h('div', { class: 'swatches', role: 'group', 'aria-label': t('appearance.accent') });
  const custom = h('input', { type: 'color', 'aria-label': t('appearance.custom_accent'), value: ctx.prefs.accent || '#6c5ce7',
    onchange: (e) => setPrefs({ accent: e.target.value }) });

  // The bar at the bottom of a phone: floating (iOS-like, with a glass slider) or the native Android one. The slider shows at once while it moves.
  const navBox = h('div', { class: 'stack' });
  function drawNav() {
    const chosen = ['ios', 'android'].includes(ctx.prefs.navbar_style) ? ctx.prefs.navbar_style : 'auto';
    const style = navStyle(ctx.prefs);                            // what is shown: the choice, or the bar of this device
    const glass = Number.isInteger(ctx.prefs.navbar_glass) ? ctx.prefs.navbar_glass : 60;
    const choice = h('div', { class: 'segmented', role: 'group', 'aria-label': t('appearance.nav') },
      [['auto', 'appearance.nav_auto'], ['ios', 'appearance.nav_ios'], ['android', 'appearance.nav_android']].map(([value, label]) => h('button', { type: 'button', class: 'seg', 'aria-pressed': String(chosen === value),
        onclick: async () => { await setPrefs({ navbar_style: value }); drawNav(); } }, t(label))));
    const shown = h('output', { for: 'nav-glass' }, t('appearance.glass_value', { n: glass }));
    const slider = h('input', { type: 'range', id: 'nav-glass', min: 0, max: 100, step: 1, value: glass, 'aria-labelledby': 'nav-glass-label',
      oninput: (e) => { shown.textContent = t('appearance.glass_value', { n: e.target.value }); applyNavGlass(Number(e.target.value)); },
      onchange: (e) => setPrefs({ navbar_glass: Number(e.target.value) }) });
    fill(navBox,
      h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, t('appearance.nav_style')), h('p', { class: 'muted' }, t('appearance.nav_hint')),
        h('p', { class: 'muted' }, chosen === 'auto' ? t('appearance.nav_auto_hint', { style: t(style === 'ios' ? 'appearance.nav_ios' : 'appearance.nav_android') }) : t(style === 'ios' ? 'appearance.nav_ios_hint' : 'appearance.nav_android_hint'))), choice),
      style === 'ios'
        ? h('div', { class: 'toggle-row' }, h('div', {}, h('strong', { id: 'nav-glass-label' }, t('appearance.glass')), h('p', { class: 'muted' }, t('appearance.glass_hint'))),
          h('div', { class: 'nav-glass' }, slider, shown))
        : null);
  }

  function drawAppearance() {
    themeButtons.replaceChildren(...THEMES.map(([value, label]) => h('button', {
      type: 'button', class: 'seg', 'aria-pressed': String((ctx.prefs.theme || 'system') === value),
      onclick: async () => { await setPrefs({ theme: value }); drawAppearance(); },
    }, t(label))));
    accentButtons.replaceChildren(...ACCENTS.map(([value, label]) => {
      const active = (ctx.prefs.accent || '#6c5ce7').toLowerCase() === value;
      const b = h('button', { type: 'button', class: 'swatch', 'aria-label': t(label), 'aria-pressed': String(active),
        onclick: async () => { await setPrefs({ accent: value }); drawAppearance(); } }, active ? '✓' : '');
      b.style.setProperty('--swatch', value);
      return b;
    }), custom);
  }

  async function addPasskey() {
    try {
      const options = await api('POST', '/api/auth/credentials/options');
      const credential = await createPasskey(options);
      const label = window.prompt(t('passkey.name_prompt'), t('passkey.default_name')) || t('passkey.default_name');
      await api('POST', '/api/auth/credentials/verify', { credential, label });
      toast(t('passkey.added'));
      loadSecurity();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function removePasskey(c) {
    if (!(await confirmDialog(t('passkey.remove_confirm', { label: c.label })))) return;
    try {
      const credential = await confirmWithPasskey('delete-credential', c.id);
      await api('DELETE', `/api/auth/credentials/${c.id}`, { credential });
      toast(t('passkey.removed'));
      loadSecurity();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function regenerate() {
    if (!(await confirmDialog(t('recovery.regen_confirm'), t('recovery.new_codes')))) return;
    try {
      const credential = await confirmWithPasskey('regenerate-recovery');
      const { recovery_codes: codes } = await api('POST', '/api/auth/recovery/regenerate', { credential });
      codesBox.replaceChildren(
        h('p', {}, h('strong', {}, t('recovery.save_now')), ' ', t('recovery.not_shown_again')),
        h('ul', { class: 'codes' }, codes.map((c) => h('li', {}, c))));
      loadSecurity(true);
    } catch (e) { toast(e.message, 'error'); }
  }

  async function loadSecurity(keepCodes = false) {
    try {
      const { credentials, recovery_codes_remaining: remaining } = await api('GET', '/api/auth/credentials');
      if (!keepCodes) codesBox.replaceChildren();
      fill(security,
        h('ul', { class: 'plain-list' }, credentials.map((c) => h('li', { class: 'list-row' },
          h('div', {}, h('strong', {}, c.label),
            h('p', { class: 'muted' }, t('passkey.added_on', { date: formatDate(c.created_at) }) +
              (c.last_used_at ? ` · ${t('passkey.last_used', { date: formatDate(c.last_used_at) })}` : ''))),
          credentials.length > 1
            ? h('button', { class: 'btn small danger', type: 'button', 'aria-label': t('common.delete_named', { name: c.label }), onclick: () => removePasskey(c) }, icon('trash'))
            : null))),
        h('div', { class: 'row' }, h('button', { class: `btn${highlightPasskey ? ' primary' : ''}`, type: 'button', onclick: addPasskey }, icon('key'), h('span', {}, t('passkey.add')))),
        h('div', { class: 'list-row' },
          h('div', {}, h('strong', {}, t('auth.recovery_codes')),
            h('p', { class: 'muted' }, t('recovery.remaining', { n: remaining }))),
          h('button', { class: 'btn small', type: 'button', onclick: regenerate }, t('recovery.new_codes'))),
        codesBox);
    } catch (e) { toast(e.message, 'error'); }
  }

  const subnav = h('nav', { class: 'subnav', 'aria-label': t('settings.sections') });
  const drawSubnav = () => subnav.replaceChildren(...shown().map(([key, label]) => h('a', { href: `#/instellingen/${key}`,
    'aria-current': key === section ? 'page' : null }, t(label))));
  drawSubnav();

  // Only the part that is open is built: the others would fetch things nobody looks at.
  const parts = {
    algemeen: () => [
      h('div', { class: 'glass card stack' }, h('h2', {}, t('settings.tab_general')),
        switchRow(t('appearance.blur'), t('appearance.blur_hint'), !!ctx.prefs.blur_costs, (on) => setPrefs({ blur_costs: on })),
        switchRow(t('general.business'), t('general.business_hint'), businessOn(), async (on) => { await setPrefs({ business_mode: on }); drawSubnav(); })),
      installCard(), updatesCard()],
    weergave: () => {
      drawAppearance();
      drawNav();
      return [h('div', { class: 'glass card stack' }, h('h2', {}, t('appearance.title')),
        h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, t('appearance.language')), h('p', { class: 'muted' }, t('appearance.language_hint'))), langSwitch(ctx.setLanguage)),
        h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, t('appearance.theme')), h('p', { class: 'muted' }, t('appearance.theme_hint'))), themeButtons),
        h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, t('appearance.accent')), h('p', { class: 'muted' }, t('appearance.accent_hint'))), accentButtons)),
      h('div', { class: 'glass card stack' }, h('h2', {}, t('appearance.nav')), navBox)];
    },
    beveiliging: () => {
      loadSecurity();
      return [h('div', { class: 'glass card stack' }, h('h2', {}, t('security.title')), h('p', { class: 'muted' }, t('security.hint')), security), passwordCard()];
    },
    zakelijk: () => [
      h('div', { class: 'glass card stack' }, h('h2', {}, t('business.title')),
        h('p', { class: 'muted' }, t('business.hint')),
        h('div', { class: 'two' },
          field(t('business.vat'), numberInput(ctx.prefs.vat_pct ?? '21', (v) => {
            clearTimeout(vatTimer);
            vatTimer = setTimeout(() => setPrefs({ vat_pct: v.replace(',', '.') }), 600);
          }, { list: 'vat-presets-settings' }), t('business.vat_hint')),
          field(t('business.rounding'), h('select', { onchange: (e) => setPrefs({ price_rounding: e.target.value }) },
            ROUNDINGS.map(([v, l]) => h('option', { value: v, selected: (ctx.prefs.price_rounding || 'none') === v }, t(l)))))),
        h('datalist', { id: 'vat-presets-settings' }, ['0', '9', '21'].map((v) => h('option', { value: v })))),
      companyCard(ctx), qrCard(ctx), invoiceLogoCard(), invoiceTemplateCard()],
    filamenten: () => filamentLibraryCards(),
    notificaties: () => notificationsCards(ctx),
    ai: () => [aiSettingsCard(), aiLogCard()],
    systeem: () => [backupCard(), resetCard()],
  };
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' }, h('div', {}, h('h1', {}, t('nav.settings')))),
    h('p', { class: 'muted page-intro' }, t('settings.signed_in_as', { name: user.display_name })),
    subnav,
    highlightPasskey && section === 'beveiliging' ? h('p', { class: 'notice', role: 'status' }, t('settings.recovered')) : null,
    ...parts[section]());
}
