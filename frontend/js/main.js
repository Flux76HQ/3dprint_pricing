import { api } from './api.js';
import { inviteToken, inviteView, loginView, onboardingView } from './auth-views.js';
import { customerEditorView, customerListView } from './customers.js';
import { orderEditorView, orderListView } from './orders.js';
import { projectEditorView, projectListView } from './projects.js';
import { resourceView } from './resources.js';
import { ACCENTS, settingsMenu, settingsSection, settingsView } from './settings.js';
import { initRelease, redrawRelease, releaseAvailable, stopRelease } from './release.js';
import { initUpdates, setDirty } from './updates.js';
import { maybeShowInstallBanner } from './install.js';
import { maybeOfferPush } from './push.js';
import { goTo, installNativeBehaviour } from './pwa.js';
import { BUILD } from './build.js';
import { getLanguage, initLanguage, setLanguage, t } from './i18n.js';
import { langSwitch } from './langswitch.js';
import { applyNavGlass, h, icon, navIcon, navStyle, betaBadge, themeToggle, toast, versionLabel } from './ui.js';

const root = document.getElementById('root');
// [route, label key, icon]: the route is the URL part and stays as it is in every language.
const NAV = [
  ['berekeningen', 'nav.calculations', 'calculator-variant'],
  ['bestellingen', 'nav.orders', 'clipboard-text'],
  ['klanten', 'nav.customers', 'account-group'],
  ['filament', 'nav.filament', 'printer-3d-nozzle'],
  ['verpakking', 'nav.packaging', 'package-variant-closed'],
  ['onderdelen', 'nav.parts', 'chip'],
  ['printers', 'nav.printers', 'printer-3d'],
  ['energie', 'nav.energy', 'lightning-bolt'],
  ['instellingen', 'nav.settings', 'cog'],
];
// The sidebar shows them in groups, by what they are for: [label key, routes]. Settings stand apart, at the bottom.
const NAV_GROUPS = [
  ['nav.group_sales', ['berekeningen', 'bestellingen', 'klanten']],
  ['nav.group_stock', ['filament', 'verpakking', 'onderdelen']],
  ['nav.group_production', ['printers', 'energie']],
];
// On compact widths the bottom bar holds five destinations: the first four, then "Meer",
// which lists the rest. The sidebar shows all of them in the same order.
const COMPACT = NAV.slice(0, 4);
const OVERFLOW = NAV.slice(4);

let session = { user: null };
let prefs = {};
let flags = { recovered: false };
let appVersion = null;
let updatesStarted = false;
let redrawMenu = () => {};                 // draws the parts of the settings in the menu again (a part appeared or went: Business switched on or off)

// --- theme & preferences ------------------------------------------------------

function luminance(hex) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

function applyPrefs() {
  const el = document.documentElement;
  if (prefs.theme === 'light' || prefs.theme === 'dark') el.setAttribute('data-theme', prefs.theme);
  else el.removeAttribute('data-theme');
  const accent = prefs.accent || ACCENTS[0][0];
  el.style.setProperty('--accent', accent);
  // Text on the accent flips with its luminance, so any chosen colour stays legible.
  el.style.setProperty('--on-accent', luminance(accent) > 0.4 ? '#14131f' : '#ffffff');
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', accent);
  el.classList.toggle('sidebar-collapsed', !!prefs.sidebar_collapsed);
  el.classList.toggle('blur-costs', !!prefs.blur_costs);
  el.setAttribute('data-nav', navStyle(prefs));                                                  // the bar at the bottom of a phone
  applyNavGlass(prefs.navbar_glass);
  try { localStorage.setItem('pp-prefs', JSON.stringify(prefs)); } catch { /* private mode */ }
}

// Optimistic: shown at once, kept if the server accepts it, rolled back (with its message) if not.
// Returns whether the change was saved.
async function setPrefs(change) {
  const before = prefs;
  prefs = { ...prefs, ...change };
  applyPrefs();
  try {
    prefs = await api('PUT', '/api/preferences', change);
    applyPrefs();
    return true;
  } catch (e) {
    prefs = before;
    applyPrefs();
    toast(e.message, 'error');
    return false;
  }
}

// --- routing -------------------------------------------------------------------

function navigate(hash, force = false) {
  if (location.hash === hash && force) route();
  else goTo(hash);
}

function currentRoute() {
  const parts = location.hash.replace(/^#\/?/, '').split('/');
  return { page: parts[0] || 'berekeningen', id: parts[1] };
}

function pageContent({ page, id }) {
  switch (page) {
    case 'berekeningen':
      if (id) return projectEditorView(id === 'nieuw' ? null : id, navigate, { get prefs() { return prefs; }, setPrefs, get aiImages() { return session.aiImages; } });
      return projectListView({ get prefs() { return prefs; }, setPrefs, get aiImages() { return session.aiImages; } });
    case 'bestellingen':
      if (id) return orderEditorView(id === 'nieuw' ? null : id, navigate, { get prefs() { return prefs; } });
      return orderListView();
    case 'klanten':
      if (id) return customerEditorView(id === 'nieuw' ? null : id, navigate);
      return customerListView();
    case 'filament': case 'verpakking': case 'printers': case 'energie': return resourceView(page, id);
    case 'onderdelen': return resourceView(id === 'accessoires' ? 'accessoires' : 'onderdelen', id);
    case 'meer':
      return h('section', { class: 'page' },
        h('header', { class: 'page-head' }, h('div', {}, h('h1', {}, t('nav.more'))),
          h('div', { class: 'row tools' }, themeToggle({ get prefs() { return prefs; }, setPrefs }, route), langSwitch(chooseLanguage))),
        h('div', { class: 'cards' }, OVERFLOW.map(([key, label, ic]) => h('a', { class: 'glass card item link-card', href: `#/${key}` },
          h('h3', {}, navIcon(ic, false), t(label))))),
        h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: logout }, icon('logout'), h('span', {}, t('session.logout')))));
    case 'instellingen':
      return settingsView({ get prefs() { return prefs; }, setPrefs, setLanguage: chooseLanguage, user: session.user, highlightPasskey: flags.recovered, get aiImages() { return session.aiImages; },
        redrawMenu: () => redrawMenu() }, id);
    default: return h('p', {}, t('nav.not_found'));
  }
}

async function logout() {
  await api('POST', '/api/auth/logout').catch(() => {});
  start();
}

function navLink([page, labelKey, ic], active, current) {
  const label = t(labelKey);
  // A dot on the entries that lead to Settings while a newer release exists (release.js shows and hides it).
  const dot = page === 'instellingen' || page === 'meer' ? h('span', { class: 'nav-dot', 'aria-hidden': 'true', hidden: !releaseAvailable() }) : null;
  return h('a', { href: `#/${page}`, 'aria-current': active ? (current || 'page') : null, title: label },
    h('span', { class: 'nav-icon' }, navIcon(ic, active), dot), h('span', { class: 'nav-label' }, label));
}

// A language was picked with a flag: show it now, and keep it with the account so every device agrees.
async function chooseLanguage(code) {
  if (code === getLanguage()) return;
  setLanguage(code);
  if (session.user) { await setPrefs({ language: code }); route(); redrawRelease(); } else start();
}

function route() {
  if (!session.user) return;
  setDirty(false);                       // a new screen starts clean; the editor raises it again on edits
  const r = currentRoute();
  const main = h('main', { id: 'main', tabindex: '-1' }, pageContent(r));
  const entry = (page, current) => { const n = NAV.find((x) => x[0] === page); return navLink(n, n[0] === r.page, current); };
  const collapsed = !!prefs.sidebar_collapsed;
  // Settings is one menu with the rest: on its pages its parts stand under it, grouped as they are on the page itself.
  const inSettings = r.page === 'instellingen';
  const who = { get prefs() { return prefs; }, user: session.user, get aiImages() { return session.aiImages; } };
  const settingsParts = h('div', { class: 'nav-sub', hidden: !inSettings });
  redrawMenu = () => {
    const open = settingsSection(who, r.id);
    settingsParts.replaceChildren(...settingsMenu(who).map(([title, items]) => h('div', { class: 'nav-sub-group', role: 'group', 'aria-label': t(title) },
      h('span', { class: 'nav-group-title', 'aria-hidden': 'true' }, t(title)),
      items.map(([key, label, name]) => h('a', { href: `#/instellingen/${key}`, 'aria-current': key === open ? 'page' : null, title: t(label) },
        h('span', { class: 'nav-icon' }, icon(name)), h('span', { class: 'nav-label' }, t(label)))))));
  };
  if (inSettings) redrawMenu();
  const sidebar = h('nav', { class: 'sidebar glass', 'aria-label': t('nav.main') },
    h('div', { class: 'sidebar-brand' }, h('img', { src: '/icons/icon.svg', alt: '', width: 32, height: 32 }),
      h('span', { class: 'nav-label brand-text' }, h('span', { class: 'brand-name' }, '3D Print Pricing', betaBadge()),
        appVersion ? h('small', { class: 'version', id: 'sidebar-version' }, versionLabel(appVersion)) : null),
      // Folding the menu away is done where the menu starts, not next to signing out.
      h('button', { class: 'tool-btn sidebar-toggle', type: 'button', 'aria-expanded': String(!collapsed), title: collapsed ? t('nav.expand') : t('nav.collapse'),
        'aria-label': collapsed ? t('nav.expand') : t('nav.collapse'), onclick: () => { setPrefs({ sidebar_collapsed: !prefs.sidebar_collapsed }).then(route); } }, icon('sidebar'))),
    h('div', { class: 'sidebar-nav' }, NAV_GROUPS.map(([label, pages]) => h('div', { class: 'nav-group', role: 'group', 'aria-label': t(label) },
      h('span', { class: 'nav-group-title', 'aria-hidden': 'true' }, t(label)), pages.map((page) => entry(page)))),
      // While its parts are listed, Settings itself is only where you are in the menu, not the page: the part is. Folded away, it is the page again.
      h('div', { class: 'nav-group nav-settings' }, entry('instellingen', inSettings && !collapsed ? 'true' : undefined), settingsParts)),
    h('div', { class: 'sidebar-foot' },
      h('div', { class: 'sidebar-tools' }, themeToggle({ get prefs() { return prefs; }, setPrefs }, route), langSwitch(chooseLanguage)),
      h('button', { class: 'logout', type: 'button', title: t('session.logout'), onclick: logout }, icon('logout'), h('span', { class: 'nav-label' }, t('session.logout')))));
  // One primary navigator at a time: CSS shows the tab bar on compact widths, the sidebar otherwise.
  const inOverflow = r.page === 'meer' || OVERFLOW.some((n) => n[0] === r.page);
  const tabbar = h('nav', { class: 'tabbar glass', 'aria-label': t('nav.main_mobile') },
    ...COMPACT.map((n) => navLink(n, n[0] === r.page)), navLink(['meer', 'nav.more', 'dots-horizontal'], inOverflow));
  root.replaceChildren(h('div', { class: 'app' }, sidebar, main, tabbar));
  window.scrollTo(0, 0);
  // The menu is long with the parts of the settings open: on those pages it starts at Settings, so all its parts are in sight without scrolling.
  if (inSettings && !collapsed) { const list = sidebar.querySelector('.sidebar-nav'); list.scrollTop = settingsParts.parentElement.offsetTop - list.offsetTop; }
}

// --- boot ----------------------------------------------------------------------

async function start() {
  const invitation = inviteToken();                  // an administrator's link: the page is for the guest, whoever else may be signed in here
  if (invitation) {
    stopRelease();
    session = { user: null };
    let passkeyProblem = null;
    try { passkeyProblem = (await api('GET', '/api/auth/status')).passkey_problem; } catch { /* the page says what is wrong when the link is used */ }
    root.replaceChildren(inviteView(invitation, start, chooseLanguage, { passkeyProblem }));
    return;
  }
  let status;
  try {
    status = await api('GET', '/api/auth/status');
  } catch (e) {
    root.replaceChildren(h('main', { id: 'main', class: 'auth-wrap' }, h('div', { class: 'glass card' },
      h('h1', {}, t('app.unreachable')), h('p', { class: 'error' }, e.message),
      h('button', { class: 'btn primary', type: 'button', onclick: start }, t('app.retry')))));
    return;
  }
  if (!status.onboarded || !status.authenticated) stopRelease();
  if (!status.onboarded) { session = { user: null }; root.replaceChildren(onboardingView(start, chooseLanguage, { passkeyProblem: status.passkey_problem })); return; }
  if (!status.authenticated) {
    session = { user: null };
    root.replaceChildren(loginView((result) => { flags = result; if (result.recovered) goTo('#/instellingen/beveiliging'); start(); }, { passwordLogin: status.password_login, nameRequired: status.login_name_required, passkeyLogin: status.passkey_login, passkeyProblem: status.passkey_problem, onLanguage: chooseLanguage }));
    return;
  }
  session = { user: status.user, aiImages: !!status.ai_images };
  appVersion = BUILD;
  if (!updatesStarted) { updatesStarted = true; initUpdates(BUILD); }
  try { prefs = await api('GET', '/api/preferences'); applyPrefs(); } catch { /* defaults */ }
  // The account's language wins on every device; with none saved yet the browser's is kept, and saved
  // once so the server (notifications, messages) speaks the same language.
  if (prefs.language) setLanguage(prefs.language);
  else setPrefs({ language: getLanguage() });
  route();
  if (session.user.role === 'admin') initRelease();   // only an administrator can act on a new version, and only they may ask the server for it
  maybeShowInstallBanner();
  maybeOfferPush();
}

installNativeBehaviour();
window.addEventListener('hashchange', () => { if (inviteToken()) start(); else route(); });
// A 401 is also the answer to a wrong password in a confirmation (deleting a backup, the factory reset, promoting someone): the server is asked
// whether the session is really gone before the person is told so and sent to the login.
window.addEventListener('auth:expired', async () => {
  if (!session.user) return;
  try { if ((await api('GET', '/api/auth/status')).authenticated) return; } catch { /* no answer: treat it as gone */ }
  toast(t('app.session_expired'), 'error');
  start();
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => { /* offline shell is optional */ });
}
initLanguage().then(start);
