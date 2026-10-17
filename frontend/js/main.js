import { api } from './api.js';
import { loginView, onboardingView } from './auth-views.js';
import { projectEditorView, projectListView } from './projects.js';
import { resourceView } from './resources.js';
import { ACCENTS, settingsView } from './settings.js';
import { initUpdates, setDirty } from './updates.js';
import { maybeShowInstallBanner } from './install.js';
import { goTo, installNativeBehaviour } from './pwa.js';
import { BUILD } from './build.js';
import { h, icon, toast, versionLabel } from './ui.js';

const root = document.getElementById('root');
const NAV = [
  ['berekeningen', 'Berekeningen', 'calculator'],
  ['filament', 'Filament', 'spool'],
  ['verpakking', 'Verpakking', 'box'],
  ['printers', 'Printers', 'printer'],
  ['energie', 'Energie', 'bolt'],
  ['instellingen', 'Instellingen', 'settings'],
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
      if (id) return projectEditorView(id === 'nieuw' ? null : id, navigate, { get prefs() { return prefs; }, setPrefs });
      return projectListView({ get prefs() { return prefs; }, setPrefs });
    case 'filament': case 'verpakking': case 'printers': case 'energie': return resourceView(page);
    case 'meer':
      return h('section', { class: 'page' },
        h('header', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Meer'))),
        h('div', { class: 'cards' }, OVERFLOW.map(([key, label, ic]) => h('a', { class: 'glass card item link-card', href: `#/${key}` },
          h('h3', {}, icon(ic), label)))));
    case 'instellingen':
      return settingsView({ get prefs() { return prefs; }, setPrefs, user: session.user, highlightPasskey: flags.recovered,
        onLogout: async () => { await api('POST', '/api/auth/logout'); start(); } });
    default: return h('p', {}, 'Pagina niet gevonden.');
  }
}

function navLink([page, label, ic], active) {
  return h('a', { href: `#/${page}`, 'aria-current': active ? 'page' : null, title: label },
    icon(ic), h('span', { class: 'nav-label' }, label));
}

function route() {
  if (!session.user) return;
  setDirty(false);                       // a new screen starts clean; the editor raises it again on edits
  const r = currentRoute();
  const main = h('main', { id: 'main', tabindex: '-1' }, pageContent(r));
  const sidebar = h('nav', { class: 'sidebar glass', 'aria-label': 'Hoofdnavigatie' },
    h('div', { class: 'sidebar-brand' }, h('img', { src: '/icons/icon.svg', alt: '', width: 32, height: 32 }),
      h('span', { class: 'nav-label brand-text' }, '3D Print Pricing',
        appVersion ? h('small', { class: 'version', id: 'sidebar-version' }, versionLabel(appVersion)) : null)),
    ...NAV.map((n) => navLink(n, n[0] === r.page)),
    h('button', { class: 'collapse', type: 'button', 'aria-label': prefs.sidebar_collapsed ? 'Zijbalk uitklappen' : 'Zijbalk inklappen',
      onclick: () => { setPrefs({ sidebar_collapsed: !prefs.sidebar_collapsed }).then(route); } },
    icon(prefs.sidebar_collapsed ? 'expand' : 'collapse'), h('span', { class: 'nav-label' }, 'Inklappen')));
  // One primary navigator at a time: CSS shows the tab bar on compact widths, the sidebar otherwise.
  const inOverflow = r.page === 'meer' || OVERFLOW.some((n) => n[0] === r.page);
  const tabbar = h('nav', { class: 'tabbar glass', 'aria-label': 'Hoofdnavigatie (mobiel)' },
    ...COMPACT.map((n) => navLink(n, n[0] === r.page)), navLink(['meer', 'Meer', 'more'], inOverflow));
  root.replaceChildren(h('div', { class: 'app' }, sidebar, main, tabbar));
  window.scrollTo(0, 0);
}

// --- boot ----------------------------------------------------------------------

async function start() {
  let status;
  try {
    status = await api('GET', '/api/auth/status');
  } catch (e) {
    root.replaceChildren(h('main', { id: 'main', class: 'auth-wrap' }, h('div', { class: 'glass card' },
      h('h1', {}, 'Server niet bereikbaar'), h('p', { class: 'error' }, e.message),
      h('button', { class: 'btn primary', type: 'button', onclick: start }, 'Opnieuw proberen'))));
    return;
  }
  if (!status.onboarded) { session = { user: null }; root.replaceChildren(onboardingView(start)); return; }
  if (!status.authenticated) {
    session = { user: null };
    root.replaceChildren(loginView((result) => { flags = result; if (result.recovered) goTo('#/instellingen'); start(); }, { passwordLogin: status.password_login }));
    return;
  }
  session = { user: status.user };
  appVersion = BUILD;
  if (!updatesStarted) { updatesStarted = true; initUpdates(BUILD); }
  try { prefs = await api('GET', '/api/preferences'); applyPrefs(); } catch { /* defaults */ }
  route();
  maybeShowInstallBanner();
}

installNativeBehaviour();
window.addEventListener('hashchange', route);
window.addEventListener('auth:expired', () => { if (session.user) { toast('Je sessie is verlopen. Log opnieuw in.', 'error'); start(); } });

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => { /* offline shell is optional */ });
}
start();
