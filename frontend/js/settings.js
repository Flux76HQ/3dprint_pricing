import { api, confirmWithPasskey, createPasskey } from './api.js';
import { confirmDialog, field, h, icon, numberInput, switchRow, toast, versionLabel } from './ui.js';

export const ACCENTS = [
  ['#6c5ce7', 'Violet'], ['#0a84ff', 'Blauw'], ['#5e5ce6', 'Indigo'], ['#bf5af2', 'Paars'],
  ['#e0457b', 'Roze'], ['#e5484d', 'Rood'], ['#d9730d', 'Oranje'], ['#2f9e44', 'Groen'], ['#0c9aa6', 'Teal'],
];
const ROUNDINGS = [['none', 'Niet afronden'], ['0.05', 'Op 5 cent'], ['0.10', 'Op 10 cent'], ['0.50', 'Op 50 cent'],
  ['1.00', 'Op hele euro'], ['5.00', 'Op 5 euro'], ['x.95', 'Eindigend op ,95'], ['x.99', 'Eindigend op ,99']];
const THEMES = [['system', 'Systeem'], ['light', 'Licht'], ['dark', 'Donker']];

export function settingsView({ prefs, setPrefs, user, onLogout, highlightPasskey }) {
  let vatTimer = null;
  const versionEl = h('span', { id: 'app-version' }, '…');
  api('GET', '/api/version').then((v) => { versionEl.textContent = versionLabel(v); }).catch(() => { versionEl.textContent = 'onbekend'; });
  const security = h('div', { class: 'stack' });
  const codesBox = h('div');

  const themeButtons = h('div', { class: 'segmented', role: 'group', 'aria-label': 'Weergave' });
  const accentButtons = h('div', { class: 'swatches', role: 'group', 'aria-label': 'Accentkleur' });
  const custom = h('input', { type: 'color', 'aria-label': 'Eigen accentkleur', value: prefs.accent || '#6c5ce7',
    onchange: (e) => setPrefs({ accent: e.target.value }) });

  function drawAppearance() {
    themeButtons.replaceChildren(...THEMES.map(([value, label]) => h('button', {
      type: 'button', class: 'seg', 'aria-pressed': String((prefs.theme || 'system') === value),
      onclick: async () => { await setPrefs({ theme: value }); drawAppearance(); },
    }, label)));
    accentButtons.replaceChildren(...ACCENTS.map(([value, label]) => {
      const active = (prefs.accent || '#6c5ce7').toLowerCase() === value;
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
        !!prefs.blur_costs, (on) => setPrefs({ blur_costs: on }))),
    h('div', { class: 'glass card stack' }, h('h2', {}, 'Zakelijk'),
      h('p', { class: 'muted' }, 'Standaardwaarden voor nieuwe berekeningen; per berekening aan te passen.'),
      h('div', { class: 'two' },
        field('Standaard btw-tarief (%)', numberInput(prefs.vat_pct ?? '21', (v) => {
          clearTimeout(vatTimer);
          vatTimer = setTimeout(() => setPrefs({ vat_pct: v.replace(',', '.') }), 600);
        }, { list: 'vat-presets-settings' }), '21 hoog tarief, 9 laag tarief, 0 = geen btw (bijv. kleineondernemersregeling).'),
        field('Standaard afronding prijs incl. btw', h('select', { onchange: (e) => setPrefs({ price_rounding: e.target.value }) },
          ROUNDINGS.map(([v, l]) => h('option', { value: v, selected: (prefs.price_rounding || 'none') === v }, l))))),
      h('datalist', { id: 'vat-presets-settings' }, ['0', '9', '21'].map((v) => h('option', { value: v })))),
    h('div', { class: 'glass card stack' }, h('h2', {}, 'Beveiliging'),
      h('p', { class: 'muted' }, 'Je logt in met passkeys; er is geen wachtwoord. Verwijderen of nieuwe herstelcodes vraagt een verse passkey-bevestiging.'),
      security),
    h('div', { class: 'glass card stack' }, h('h2', {}, 'Sessie'),
      h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: onLogout }, 'Uitloggen'))),
    h('p', { class: 'muted' }, 'Draaiende versie: ', versionEl));
}
