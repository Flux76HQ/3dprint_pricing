import { api, confirmWithPasskey, createPasskey } from './api.js';
import { IOS_STEPS, installState, onInstallChange, promptInstall } from './install.js';
import { passwordCard } from './password.js';
import { currentSubscription, disablePush, enablePush, pushSupport } from './push.js';
import { confirmDialog, field, h, icon, numberInput, switchRow, toast, versionLabel } from './ui.js';
import { checkForUpdate, loadedVersion } from './updates.js';

export const ACCENTS = [
  ['#6c5ce7', 'Violet'], ['#0a84ff', 'Blauw'], ['#5e5ce6', 'Indigo'], ['#bf5af2', 'Paars'],
  ['#e0457b', 'Roze'], ['#e5484d', 'Rood'], ['#d9730d', 'Oranje'], ['#2f9e44', 'Groen'], ['#0c9aa6', 'Teal'],
];
const ROUNDINGS = [['none', 'Niet afronden'], ['0.05', 'Op 5 cent'], ['0.10', 'Op 10 cent'], ['0.50', 'Op 50 cent'],
  ['1.00', 'Op hele euro'], ['5.00', 'Op 5 euro'], ['x.95', 'Eindigend op ,95'], ['x.99', 'Eindigend op ,99']];
const THEMES = [['system', 'Systeem'], ['light', 'Licht'], ['dark', 'Donker']];

function installCard() {
  const body = h('div', { class: 'stack' });
  const draw = () => {
    const state = installState();
    if (state === 'installed') body.replaceChildren(h('p', { class: 'status-line' }, '✓ De app is geïnstalleerd op dit apparaat.'));
    else if (state === 'prompt') {
      body.replaceChildren(h('p', {}, 'Installeer de app voor een schermvullende, snelle start.'),
        h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: async () => { await promptInstall(); draw(); } }, 'App installeren')));
    } else if (state === 'ios') {
      body.replaceChildren(h('p', {}, IOS_STEPS), h('p', { class: 'muted' }, 'Meldingen werken op iPhone en iPad alleen voor een geïnstalleerde app (iOS 16.4 of nieuwer).'));
    } else {
      body.replaceChildren(h('p', { class: 'muted' }, 'Deze browser biedt geen installatie aan. Gebruik Chrome of Edge (Android en computer) of Safari (iPhone en iPad), via https.'));
    }
  };
  draw();
  let seen = false;
  const off = onInstallChange(() => {            // stop listening once this screen has been replaced
    if (body.isConnected) seen = true; else if (seen) { off(); return; }
    draw();
  });
  return h('div', { class: 'glass card stack' }, h('h2', {}, 'App installeren'), body);
}

function updatesCard() {
  const v = loadedVersion();
  return h('div', { class: 'glass card stack' }, h('h2', {}, 'Updates'),
    h('p', { class: 'status-line' }, 'Draaiende versie: ', h('strong', { id: 'app-version' }, v ? versionLabel(v) : 'onbekend')),
    h('p', { class: 'muted' }, 'De app controleert zelf op een nieuwe versie wanneer je hem opent en daarna elk kwartier.'),
    h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: () => checkForUpdate({ manual: true }) }, 'Controleer op updates')));
}

const DEFAULT_QUIET = () => ({ enabled: false, start: '22:00', end: '07:00', tz: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Amsterdam' });

// `ctx.prefs` is read when needed, never copied: a copy goes stale the moment a setting is saved.
function notificationsCard(ctx) {
  const { setPrefs } = ctx;
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'Laden…'));

  async function draw() {
    let cfg;
    try { cfg = await api('GET', '/api/push/config'); } catch (e) { body.replaceChildren(h('p', { class: 'error' }, e.message)); return; }
    const support = pushSupport();
    const notes = {
      'ios-install': 'Meldingen werken op iPhone en iPad alleen voor een geïnstalleerde app (iOS 16.4 of nieuwer): zet de app eerst op je beginscherm.',
      unsupported: 'Deze browser ondersteunt geen meldingen.',
      denied: 'Meldingen zijn geblokkeerd voor deze site. Sta ze toe in de instellingen van je browser of toestel en kom dan terug.',
    };
    if (!cfg.configured) { body.replaceChildren(h('p', { class: 'muted' }, 'Meldingen zijn nog niet ingesteld op de server (VAPID-sleutels ontbreken; zie de README).')); return; }
    if (!support.ok) { body.replaceChildren(h('p', { class: 'muted' }, notes[support.reason])); return; }

    const sub = await currentSubscription().catch(() => null);
    const rows = [switchRow('Meldingen op dit apparaat',
      'Je geeft per apparaat toestemming. Meldingen komen stil binnen: ze zijn nooit dringend.', !!sub, async (on) => {
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
      const result = h('p', { class: 'status-line', role: 'status' });
      rows.push(
        switchRow('Melding bij nieuwe versie', 'Een melding zodra de server is bijgewerkt.', ctx.prefs.notify_release !== false,
          (on) => setPrefs({ notify_release: on })),
        switchRow('Stille uren',
          'Meldingen binnen deze tijden worden vastgehouden en daarna alsnog afgeleverd. De app ziet de Focus-stand van je toestel niet, ' +
          'dus zet hier hetzelfde rooster als je slaap-Focus. Focus of Niet storen doorbreken stel je zelf in op je toestel; de app probeert dat niet.',
          !!quiet.enabled, (on) => saveQuiet({ enabled: on })),
        h('div', { class: 'time-row' },
          field('Van', h('input', { type: 'time', value: quiet.start, onchange: (e) => saveQuiet({ start: e.target.value }) })),
          field('Tot', h('input', { type: 'time', value: quiet.end, onchange: (e) => saveQuiet({ end: e.target.value }) }))),
        field('Tijdzone', h('input', { type: 'text', value: quiet.tz, autocomplete: 'off', spellcheck: 'false',
          onchange: (e) => saveQuiet({ tz: e.target.value.trim() }) }), 'Bijvoorbeeld Europe/Amsterdam; de tijden volgen de zomer- en wintertijd.'),
        h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: async () => {
          try {
            const r = await api('POST', '/api/push/test');
            if (r.deferred_until) result.textContent = `Stille uren actief: de testmelding komt om ${new Date(r.deferred_until).toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })}.`;
            else if (r.sent > 0) result.textContent = `Testmelding verstuurd naar ${r.sent} apparaat${r.sent === 1 ? '' : 'en'}.`;
            else result.textContent = 'Versturen mislukt: het pushadres van dit apparaat reageerde niet of is verlopen. Zet meldingen uit en weer aan.';
          } catch (e) { result.textContent = e.message; }
        } }, 'Stuur testmelding')),
        result,
        h('p', { class: 'muted' }, `${cfg.devices} apparaat${cfg.devices === 1 ? '' : 'en'} aangemeld. Een melding blijft maximaal ${cfg.ttl_hours} uur wachten als je toestel uit staat.`));
    }
    body.replaceChildren(...rows);
  }
  draw();
  return h('div', { class: 'glass card stack' }, h('h2', {}, 'Meldingen'), body);
}

export function settingsView(ctx) {
  const { setPrefs, user, onLogout, highlightPasskey } = ctx;
  let vatTimer = null;
  const security = h('div', { class: 'stack' });
  const codesBox = h('div');

  const themeButtons = h('div', { class: 'segmented', role: 'group', 'aria-label': 'Weergave' });
  const accentButtons = h('div', { class: 'swatches', role: 'group', 'aria-label': 'Accentkleur' });
  const custom = h('input', { type: 'color', 'aria-label': 'Eigen accentkleur', value: ctx.prefs.accent || '#6c5ce7',
    onchange: (e) => setPrefs({ accent: e.target.value }) });

  function drawAppearance() {
    themeButtons.replaceChildren(...THEMES.map(([value, label]) => h('button', {
      type: 'button', class: 'seg', 'aria-pressed': String((ctx.prefs.theme || 'system') === value),
      onclick: async () => { await setPrefs({ theme: value }); drawAppearance(); },
    }, label)));
    accentButtons.replaceChildren(...ACCENTS.map(([value, label]) => {
      const active = (ctx.prefs.accent || '#6c5ce7').toLowerCase() === value;
      const b = h('button', { type: 'button', class: 'swatch', 'aria-label': label, 'aria-pressed': String(active),
        onclick: async () => { await setPrefs({ accent: value }); drawAppearance(); } }, active ? '✓' : '');
      b.style.setProperty('--swatch', value);
      return b;
    }), custom);
  }

  async function addPasskey() {
    try {
      const options = await api('POST', '/api/auth/credentials/options');
      const credential = await createPasskey(options);
      const label = window.prompt('Naam voor deze passkey (bijv. “iPhone” of “Laptop”)', 'Passkey') || 'Passkey';
      await api('POST', '/api/auth/credentials/verify', { credential, label });
      toast('Passkey toegevoegd');
      loadSecurity();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function removePasskey(c) {
    if (!(await confirmDialog(`Passkey “${c.label}” verwijderen? Je bevestigt dit met een passkey.`))) return;
    try {
      const credential = await confirmWithPasskey('delete-credential', c.id);
      await api('DELETE', `/api/auth/credentials/${c.id}`, { credential });
      toast('Passkey verwijderd');
      loadSecurity();
    } catch (e) { toast(e.message, 'error'); }
  }

  async function regenerate() {
    if (!(await confirmDialog('Nieuwe herstelcodes maken? De oude werken daarna niet meer.', 'Nieuwe codes'))) return;
    try {
      const credential = await confirmWithPasskey('regenerate-recovery');
      const { recovery_codes: codes } = await api('POST', '/api/auth/recovery/regenerate', { credential });
      codesBox.replaceChildren(
        h('p', {}, h('strong', {}, 'Bewaar deze codes nu'), ' — ze worden niet opnieuw getoond.'),
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
            h('p', { class: 'muted' }, `Toegevoegd ${new Date(c.created_at).toLocaleDateString('nl-NL')}` +
              (c.last_used_at ? ` · laatst gebruikt ${new Date(c.last_used_at).toLocaleDateString('nl-NL')}` : ''))),
          credentials.length > 1
            ? h('button', { class: 'btn small danger', type: 'button', 'aria-label': `Verwijder ${c.label}`, onclick: () => removePasskey(c) }, icon('trash'))
            : null))),
        h('div', { class: 'row' }, h('button', { class: `btn${highlightPasskey ? ' primary' : ''}`, type: 'button', onclick: addPasskey }, icon('key'), h('span', {}, 'Passkey toevoegen'))),
        h('div', { class: 'list-row' },
          h('div', {}, h('strong', {}, 'Herstelcodes'),
            h('p', { class: 'muted' }, `${remaining} van 8 ongebruikt`)),
          h('button', { class: 'btn small', type: 'button', onclick: regenerate }, 'Nieuwe codes')),
        codesBox);
    } catch (e) { toast(e.message, 'error'); }
  }

  drawAppearance();
  loadSecurity();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Instellingen'), h('p', { class: 'muted' }, `Ingelogd als ${user.display_name}`))),
    highlightPasskey ? h('p', { class: 'notice', role: 'status' }, 'Je bent ingelogd met een herstelcode. Voeg nu een nieuwe passkey toe aan dit apparaat.') : null,
    h('div', { class: 'glass card stack' }, h('h2', {}, 'Weergave'),
      h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, 'Thema'), h('p', { class: 'muted' }, 'Systeem volgt de instelling van je apparaat.')), themeButtons),
      h('div', { class: 'toggle-row' }, h('div', {}, h('strong', {}, 'Accentkleur'), h('p', { class: 'muted' }, 'Voor knoppen, links en selecties.')), accentButtons),
      switchRow('Kostprijs en marge blurren',
        'Maakt kostprijs, subtotalen, kosten per regel en marge onscherp op de pagina Berekeningen, handig als een klant meekijkt. Verkoopprijs en btw blijven leesbaar.',
        !!ctx.prefs.blur_costs, (on) => setPrefs({ blur_costs: on }))),
    h('div', { class: 'glass card stack' }, h('h2', {}, 'Zakelijk'),
      h('p', { class: 'muted' }, 'Standaardwaarden voor nieuwe berekeningen; per berekening aan te passen.'),
      h('div', { class: 'two' },
        field('Standaard btw-tarief (%)', numberInput(ctx.prefs.vat_pct ?? '21', (v) => {
          clearTimeout(vatTimer);
          vatTimer = setTimeout(() => setPrefs({ vat_pct: v.replace(',', '.') }), 600);
        }, { list: 'vat-presets-settings' }), '21 hoog tarief, 9 laag tarief, 0 = geen btw (bijv. kleineondernemersregeling).'),
        field('Standaard afronding prijs incl. btw', h('select', { onchange: (e) => setPrefs({ price_rounding: e.target.value }) },
          ROUNDINGS.map(([v, l]) => h('option', { value: v, selected: (ctx.prefs.price_rounding || 'none') === v }, l))))),
      h('datalist', { id: 'vat-presets-settings' }, ['0', '9', '21'].map((v) => h('option', { value: v })))),
    installCard(), notificationsCard(ctx), updatesCard(),
    h('div', { class: 'glass card stack' }, h('h2', {}, 'Beveiliging'),
      h('p', { class: 'muted' }, 'Je logt in met passkeys; er is geen wachtwoord. Verwijderen of nieuwe herstelcodes vraagt een verse passkey-bevestiging.'),
      security),
    passwordCard(),
    h('div', { class: 'glass card stack' }, h('h2', {}, 'Sessie'),
      h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: onLogout }, 'Uitloggen'))));
}
