import { BUILD } from './build.js';
import { getLocale, t } from './i18n.js';
import { MDI } from './mdi.js';

// Tiny DOM helpers. Everything goes through textContent/attributes, never innerHTML with data.
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'value' || key === 'checked' || key === 'disabled' || key === 'hidden') el[key] = value;
    else if (value === true) el.setAttribute(key, '');
    else el.setAttribute(key, value);
  }
  el.append(...children.flat(Infinity).filter((c) => c != null && c !== false));
  return el;
}

// Replaces what is in `el`. Unlike a bare `el.replaceChildren(...)`, a null/undefined/false child (the unused branch of a
// condition) is dropped: the DOM would turn it into the text "null".
export function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c != null && c !== false));
}

const ICONS = {
  calculator: '<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M8.5 7.5h7M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01"/>',
  spool: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3"/><path d="M12 3.5v5.5M12 15v5.5"/>',
  printer: '<path d="M7 9V4h10v5M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/><rect x="7" y="14" width="10" height="6" rx="1"/>',
  bolt: '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 14a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  restore: '<path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4"/><path d="M12 8v4l3 2"/>',
  collapse: '<path d="m15 6-6 6 6 6"/>',
  expand: '<path d="m9 6 6 6-6 6"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  'chevron-up': '<path d="m6 15 6-6 6 6"/>',
  box: '<path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5z"/><path d="M3.5 7.5 12 12l8.5-4.5M12 12v9"/>',
  more: '<circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/>',
  scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M16 7l3 3"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 8l-4 4 4 4M6 12h11"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.2a6.5 6.5 0 0 1 3.5 5.8"/>',
  sync: '<path d="M20 11a8 8 0 0 0-14.5-4M4 4v4h4M4 13a8 8 0 0 0 14.5 4M20 20v-4h-4"/>',
  clipboard: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4h6v3H9zM9 12h6M9 16h4"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
  'sort-up': '<path d="M12 19V5M6 11l6-6 6 6"/>',
  'sort-down': '<path d="M12 5v14M6 13l6 6 6-6"/>',
  'view-tiles': '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  'view-list': '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4"/>',
  archive: '<rect x="3.5" y="4.5" width="17" height="4" rx="1"/><path d="M5.5 8.5v10a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-10M10 12.5h4"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5z"/>',
  sidebar: '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M9.5 4.5v15"/>',
  star: '<path d="m12 3.5 2.6 5.4 5.9.8-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8-4.3-4.1 5.9-.8z"/>',
  save: '<path d="M5 4h11l4 4v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
};

export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  if (MDI[name]) {                                   // a Material Design icon: filled, in the colour of the text
    svg.setAttribute('class', 'icon mdi');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', MDI[name]);
    svg.append(path);
    return svg;
  }
  svg.setAttribute('class', 'icon');
  svg.innerHTML = ICONS[name] || ''; // static strings above, never user data
  return svg;
}

/** The bottom bar to show: what the account chose, else the one of the device (data-platform is set before the first paint by
    theme-boot.js: an Android phone gets the Android bar, anything else the iOS-like one). */
export function navStyle(prefs) {
  if (prefs.navbar_style === 'ios' || prefs.navbar_style === 'android') return prefs.navbar_style;
  return document.documentElement.getAttribute('data-platform') === 'android' ? 'android' : 'ios';
}

/** The glass of the floating bar (0 = solid ... 100 = the clearest) as plain CSS values: the tint's opacity and the blur. */
export function applyNavGlass(glass, el = document.documentElement) {
  const g = Number.isInteger(glass) ? Math.min(100, Math.max(0, glass)) : 60;
  el.style.setProperty('--nav-alpha', (1 - g * 0.0085).toFixed(3));
  el.style.setProperty('--nav-blur', `${(10 + g * 0.3).toFixed(1)}px`);
}

/** The icon of a destination in the navigation: filled while it is the page you are on, as an outline otherwise (when there is one). */
export const navIcon = (name, active) => icon(!active && MDI[`${name}-outline`] ? `${name}-outline` : name);

/** The heading of a card that can be folded away: a button with the title and a chevron. While it is not expanded the card shows only this
    heading (css: `.card:has(> .fold-head [aria-expanded="false"])`). The choice is remembered in this browser under `key`; `open` is
    what a first visit gets. `extra` (an element, e.g. a `connectionBadge`) stands next to the title, so it can be read while the card is folded. */
export function foldHead(key, title, { open = true, extra = null } = {}) {
  const store = `pp-fold-${key}`;
  let isOpen = open;
  try { const saved = localStorage.getItem(store); if (saved === '1' || saved === '0') isOpen = saved === '1'; } catch { /* storage blocked: the default */ }
  const button = h('button', { type: 'button', class: 'fold-toggle', 'aria-expanded': String(isOpen), onclick: () => {
    const now = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(now));
    try { localStorage.setItem(store, now ? '1' : '0'); } catch { /* not remembered */ }
  } }, h('span', { class: 'fold-title' }, title, extra), icon('chevron-down'));
  return h('h2', { class: 'fold-head' }, button);
}

// How a connection to another application can stand: working, set up but not answering, or not set up (or still being looked at).
const CONNECTION = { active: ['badge ok', 'connection.active'], offline: ['badge danger', 'connection.offline'], off: ['badge muted', 'connection.off'],
  checking: ['badge muted', 'connection.checking'] };

/** The state of a connection as it stands in the heading of its card (`foldHead`'s `extra`): **active**, **not connected** (there is a setup and the other side does not answer)
    or **not configured**, with a short `detail` (a count, a host) and, for a connection that does not answer, the reason as a tooltip. It starts as "checking"; `set(state, { detail, message })` changes it. */
export function connectionBadge() {
  const el = h('span', { class: 'connection-state' });
  const set = (state, { detail = null, message = null } = {}) => {
    const [cls, key] = CONNECTION[state];
    el.dataset.state = state;
    fill(el, h('span', { class: cls, title: message || null }, t(key)), detail ? h('span', { class: 'muted connection-detail' }, detail) : null);
  };
  set('checking');
  return { el, set };
}

export const eur = (value) => new Intl.NumberFormat(getLocale(), { style: 'currency', currency: 'EUR' }).format(Number(value) || 0);

export function fmt(value, digits = 2) {
  return new Intl.NumberFormat(getLocale(), { maximumFractionDigits: digits }).format(Number(value) || 0);
}

// Accept both "26,99" and "26.99": people type what their keyboard has.
// Rounding of a price incl. VAT: [value sent to the server, label key]. Chosen per order; the settings hold the default for new orders.
export const ROUNDINGS = [['none', 'rounding.none'], ['0.05', 'rounding.5c'], ['0.10', 'rounding.10c'], ['0.50', 'rounding.50c'],
  ['1.00', 'rounding.1e'], ['5.00', 'rounding.5e'], ['x.95', 'rounding.95'], ['x.99', 'rounding.99']];

export function parseNum(value) {
  if (typeof value === 'number') return value;
  const n = parseFloat(String(value ?? '').trim().replace(',', '.'));
  return Number.isFinite(n) ? n : 0;
}

/** Hands a downloaded file to the user, as a link click on a temporary address. */
export function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = h('a', { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function toast(message, kind = 'info') {
  const el = h('div', { class: `toast ${kind}` }, message);
  document.getElementById('toasts').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 7000 : 3500);
}

export function field(label, input, hint) {
  const id = `f${Math.random().toString(36).slice(2, 9)}`;
  input.id = id;
  return h('div', { class: 'field' },
    h('label', { for: id }, label), input, hint ? h('p', { class: 'hint' }, hint) : null);
}

export function numberInput(value, onInput, attrs = {}) {
  return h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', value: value ?? '', ...attrs,
    oninput: (e) => onInput(e.target.value) });
}

/**
 * Every pop-up goes through here: it fits the screen (the content scrolls, the close button does not),
 * gets an X at the top right, and Escape / X / Cancel ask first when something would be lost.
 * `dirty()` says whether closing would lose work; `message` (text or a function) is what to warn with. Call `dialog.requestClose()`
 * from a Cancel button instead of `dialog.close()` so that it is guarded too.
 */
export function enhanceDialog(dialog, options = {}) {
  const { dirty } = options;
  dialog.replaceChildren(h('div', { class: 'sheet-body' }, ...dialog.childNodes));
  let asking = false;
  const requestClose = async () => {
    if (asking) return;
    if (dirty && dirty()) {
      asking = true;
      const said = typeof options.message === 'function' ? options.message() : options.message;
      const leave = await confirmDialog(said || t('dialog.unsaved'), t('dialog.close_anyway'));
      asking = false;
      if (!leave) return;
    }
    dialog.close('no');
  };
  dialog.requestClose = requestClose;
  // Escape: handled on the key itself, because Chrome closes a dialog straight away (no `cancel` event to stop) when
  // Escape is pressed twice without a click in between. `cancel` still covers the Android back gesture.
  const onKey = (event) => {
    const open = document.querySelectorAll('dialog[open]');
    if (event.key === 'Escape' && dialog.open && open[open.length - 1] === dialog) { event.preventDefault(); requestClose(); }   // the top one only
  };
  document.addEventListener('keydown', onKey, true);
  dialog.addEventListener('close', () => document.removeEventListener('keydown', onKey, true));
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); requestClose(); });
  // After the content in the DOM, so the first field (not the X) takes the focus; CSS puts it top right.
  dialog.append(h('button', { type: 'button', class: 'dialog-x', 'aria-label': t('common.close'), onclick: requestClose }, icon('close')));
  return dialog;
}

export function confirmDialog(message, confirmLabel = t('common.delete')) {
  return new Promise((resolve) => {
    // The answer is given the moment a button is pressed, not when the `close` event arrives a tick later.
    const answer = (yes) => { resolve(yes); dialog.close(yes ? 'yes' : 'no'); };
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
      h('p', {}, message),
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: () => answer(false) }, t('common.cancel')),
        h('button', { class: 'btn danger', type: 'button', onclick: () => answer(true) }, confirmLabel))));
    dialog.addEventListener('close', () => { resolve(dialog.returnValue === 'yes'); dialog.remove(); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

/** A question with more than two answers: `choices` are { value, label, primary }. Resolves with the value, or null when closed. */
export function askChoice(message, choices) {
  return new Promise((resolve) => {
    let picked = null;
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
      h('p', {}, message),
      h('div', { class: 'row end wrap' }, choices.map((c) => h('button', { class: `btn${c.primary ? ' primary' : ''}`, type: 'button',
        onclick: () => { picked = c.value; resolve(picked); dialog.close(); } }, c.label)))));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(picked); });
    document.body.append(dialog);
    dialog.showModal();
  });
}

// A real <button role="switch">: the accessibility tree is right by construction, and
// space/enter/focus order come for free. The label points at the title instead of repeating it.
export function switchRow(title, description, checked, onChange) {
  const titleId = `sw${Math.random().toString(36).slice(2, 9)}`;
  const button = h('button', { type: 'button', class: 'switch', role: 'switch', 'aria-checked': String(checked),
    'aria-labelledby': titleId, onclick: () => {
      const next = button.getAttribute('aria-checked') !== 'true';
      button.setAttribute('aria-checked', String(next));
      onChange(next);
    } }, h('span', { class: 'thumb' }));
  return h('div', { class: 'toggle-row' },
    h('div', {}, h('strong', { id: titleId }, title), h('p', { class: 'muted' }, description)), button);
}

/** Is the screen dark right now: what the account chose, else what the device asks for. */
export const isDark = (prefs) => (prefs.theme === 'dark' || prefs.theme === 'light' ? prefs.theme === 'dark'
  : window.matchMedia('(prefers-color-scheme: dark)').matches);

/** Light or dark in one click, from the menu: the button shows what a click gives (a moon while it is light). The choice between light, dark
    and "as the device" stays under Settings > Appearance. */
export function themeToggle(ctx, onChange = () => {}) {
  const dark = isDark(ctx.prefs);
  const label = t(dark ? 'theme.to_light' : 'theme.to_dark');
  return h('button', { type: 'button', class: 'tool-btn theme-toggle', title: label, 'aria-label': label,
    onclick: async () => { await ctx.setPrefs({ theme: dark ? 'light' : 'dark' }); onChange(); } }, icon(dark ? 'sun' : 'moon'));
}

/** The way back from an editor to its overview, in the title bar: an arrow and the name of the overview (just the arrow on a phone). */
export const backLink = (href, name) => h('a', { class: 'back', href, title: t('common.back_to', { name }), 'aria-label': t('common.back_to', { name }) },
  icon('collapse'), h('span', {}, name));

/** A button in the title bar of an editor: an icon and a word. Where there is little room the ones in a group show just the icon, and say what
    they are when pointed at. */
export const headAction = (name, label, onclick, cls = '', attrs = {}) => h('button', { class: `btn${cls}`, type: 'button', title: label, onclick, ...attrs },
  icon(name), h('span', {}, label));

// Small eye button that flips the "hide costs" display preference from the page itself.
export function blurToggle(ctx) {
  const button = h('button', { type: 'button', class: 'btn small', 'aria-pressed': String(!!ctx.prefs.blur_costs),
    onclick: async () => {
      await ctx.setPrefs({ blur_costs: !ctx.prefs.blur_costs });
      button.setAttribute('aria-pressed', String(!!ctx.prefs.blur_costs));
      button.querySelector('span').textContent = ctx.prefs.blur_costs ? t('blur.show') : t('blur.hide');
    } }, icon('eye'), h('span', {}, ctx.prefs.blur_costs ? t('blur.show') : t('blur.hide')));
  return button;
}

// "v0.3.1 (abc1234)": the running release and the commit it was built from.
/** "Bambu Lab Matte Black": brand, type and colour of a filament roll. */
export const spoolName = (s, sep = ' ') => [s.brand, s.product_type, s.colour].filter(Boolean).join(sep);
// The marker of a beta build, next to the app name; nothing on a stable one. The channel is stamped into build.js by the server.
export const betaBadge = () => (BUILD.channel === 'beta' ? h('span', { class: 'beta-badge', title: t('brand.beta_title') }, 'beta') : null);
export const versionLabel = (v) => (v ? `v${v.version} (${v.commit || 'dev'})` : '');

// Banners (install hint, "new version available") stack at the top; one per id.
export function showBanner(id, { text, actions = [] }) {
  const host = document.getElementById('banners');
  host.querySelector(`[data-banner="${id}"]`)?.remove();
  const el = h('div', { class: 'banner glass', role: 'status', 'data-banner': id },
    h('p', {}, text), h('div', { class: 'row' }, actions.filter(Boolean)));
  host.append(el);
  return { close: () => el.remove() };
}
