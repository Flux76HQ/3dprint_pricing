import { api, confirmWithPasskey, createPasskey, downloadFile } from './api.js';
import { iosSteps, installState, onInstallChange, promptInstall } from './install.js';
import { formatDate, formatDateTime, formatTime, t } from './i18n.js';
import { langSwitch } from './langswitch.js';
import { passwordCard } from './password.js';
import { currentSubscription, disablePush, enablePush, pushSupport, thisDeviceFingerprint } from './push.js';
import { confirmDialog, field, h, icon, numberInput, switchRow, toast, versionLabel } from './ui.js';
import { checkForUpdate, loadedVersion } from './updates.js';

// [value, label key]: labels are looked up when drawn, so they follow the language.
export const ACCENTS = [
  ['#6c5ce7', 'accent.violet'], ['#0a84ff', 'accent.blue'], ['#5e5ce6', 'accent.indigo'], ['#bf5af2', 'accent.purple'],
  ['#e0457b', 'accent.pink'], ['#e5484d', 'accent.red'], ['#d9730d', 'accent.orange'], ['#2f9e44', 'accent.green'], ['#0c9aa6', 'accent.teal'],
];
const ROUNDINGS = [['none', 'rounding.none'], ['0.05', 'rounding.5c'], ['0.10', 'rounding.10c'], ['0.50', 'rounding.50c'],
  ['1.00', 'rounding.1e'], ['5.00', 'rounding.5e'], ['x.95', 'rounding.95'], ['x.99', 'rounding.99']];
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

// `ctx.prefs` is read when needed, never copied: a copy goes stale the moment a setting is saved.
function notificationsCard(ctx) {
  const { setPrefs } = ctx;
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  let lastResult = '';                                    // survives the redraw that refreshes the device list

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

    if (sub) {
      const quiet = { ...DEFAULT_QUIET(), ...(ctx.prefs.quiet_hours || {}) };
      const saveQuiet = async (change) => {
        const saved = await setPrefs({ quiet_hours: { ...quiet, ...change } });
        if (saved) Object.assign(quiet, change);       // later edits build on what was really saved
        else draw();                                    // refused (e.g. unknown timezone): show the saved values again
      };
      const result = h('p', { class: 'status-line', role: 'status' }, lastResult);
      rows.push(
        switchRow(t('notify.release'), t('notify.release_hint'), ctx.prefs.notify_release !== false,
          (on) => setPrefs({ notify_release: on })),
        switchRow(t('notify.quiet'), t('notify.quiet_hint'),
          !!quiet.enabled, (on) => saveQuiet({ enabled: on })),
        h('div', { class: 'time-row' },
          field(t('notify.from'), h('input', { type: 'time', value: quiet.start, onchange: (e) => saveQuiet({ start: e.target.value }) })),
          field(t('notify.to'), h('input', { type: 'time', value: quiet.end, onchange: (e) => saveQuiet({ end: e.target.value }) }))),
        field(t('notify.timezone'), h('input', { type: 'text', value: quiet.tz, autocomplete: 'off', spellcheck: 'false',
          onchange: (e) => saveQuiet({ tz: e.target.value.trim() }) }), t('notify.timezone_hint')),
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
    rows.push(await devicesList(draw));
    body.replaceChildren(...rows);
  }
  draw();
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('notify.title')), body);
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

/** Backup and restore of everything entered (settings, printers, tariffs, packaging, rolls, calculations). */
function backupCard() {
  let withFiles = false;
  const status = h('p', { class: 'status-line', role: 'status' });
  const picker = h('input', { type: 'file', accept: '.json,application/json', hidden: true, 'aria-label': t('backup.restore') });

  async function download() {
    try {
      const { blob, name } = await downloadFile(`/api/backup${withFiles ? '?files=1' : ''}`);
      const url = URL.createObjectURL(blob);
      const link = h('a', { href: url, download: name });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      status.textContent = t('backup.downloaded', { name });
    } catch (e) { toast(e.message, 'error'); }
  }

  async function restore(file) {
    let doc;
    try { doc = JSON.parse(await file.text()); } catch { toast(t('backup.not_json'), 'error'); return; }
    try {
      const { summary: s } = await api('POST', '/api/backup/restore?dry_run=1', doc);       // checked first, nothing changes yet
      const when = s.created_at ? formatDateTime(s.created_at, { dateStyle: 'medium', timeStyle: 'short' }) : '?';
      const files = s.files ? t('backup.with_files', { n: s.files }) : '';
      if (!(await confirmDialog(t('backup.confirm', { when, printers: s.printers, tariffs: s.tariffs, packaging: s.packaging,
        spools: s.spools, projects: s.projects, files }), t('backup.restore_now')))) return;
      await api('POST', '/api/backup/restore', doc);
      toast(t('backup.restored'));
      setTimeout(() => window.location.reload(), 600);                                      // settings and language may have changed
    } catch (e) { toast(e.message, 'error'); }
  }

  picker.addEventListener('change', () => { const file = picker.files[0]; picker.value = ''; if (file) restore(file); });
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('backup.title')),
    h('p', { class: 'muted' }, t('backup.intro')),
    h('label', { class: 'check' }, h('input', { type: 'checkbox', onchange: (e) => { withFiles = e.target.checked; } }), t('backup.files')),
    h('p', { class: 'hint' }, t('backup.files_hint')),
    h('div', { class: 'row' },
      h('button', { class: 'btn primary', type: 'button', onclick: download }, t('backup.download')),
      h('button', { class: 'btn', type: 'button', onclick: () => picker.click() }, t('backup.restore')), picker),
    status,
    h('p', { class: 'muted' }, t('backup.not_included')));
}

export function settingsView(ctx) {
  const { setPrefs, user, onLogout, highlightPasskey } = ctx;
  let vatTimer = null;
  const security = h('div', { class: 'stack' });
  const codesBox = h('div');

  const themeButtons = h('div', { class: 'segmented', role: 'group', 'aria-label': t('appearance.title') });
  const accentButtons = h('div', { class: 'swatches', role: 'group', 'aria-label': t('appearance.accent') });
  const custom = h('input', { type: 'color', 'aria-label': t('appearance.custom_accent'), value: ctx.prefs.accent || '#6c5ce7',
    onchange: (e) => setPrefs({ accent: e.target.value }) });

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
      security.replaceChildren(
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

  drawAppearance();
  loadSecurity();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' }, h('div', {}, h('h1', {}, t('nav.settings')), h('p', { class: 'muted' }, t('settings.signed_in_as', { name: user.display_name })))),
    highlightPasskey ? h('p', { class: 'notice', role: 'status' }, t('settings.recovered')) : null,
    h('div', { class: 'glass card stack' }, h('h2', {}, t('appearance.title')),
      h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, t('appearance.language')), h('p', { class: 'muted' }, t('appearance.language_hint'))), langSwitch(ctx.setLanguage)),
      h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, t('appearance.theme')), h('p', { class: 'muted' }, t('appearance.theme_hint'))), themeButtons),
      h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, t('appearance.accent')), h('p', { class: 'muted' }, t('appearance.accent_hint'))), accentButtons),
      switchRow(t('appearance.blur'),
        t('appearance.blur_hint'),
        !!ctx.prefs.blur_costs, (on) => setPrefs({ blur_costs: on }))),
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
    installCard(), notificationsCard(ctx), updatesCard(),
    h('div', { class: 'glass card stack' }, h('h2', {}, t('security.title')),
      h('p', { class: 'muted' }, t('security.hint')),
      security),
    passwordCard(),
    backupCard(),
    h('div', { class: 'glass card stack' }, h('h2', {}, t('session.title')),
      h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: onLogout }, t('session.logout')))));
}
