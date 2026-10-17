import { getLocale, t } from './i18n.js';

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

const ICONS = {
  calculator: '<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M8.5 7.5h7M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01"/>',
  spool: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3"/><path d="M12 3.5v5.5M12 15v5.5"/>',
  printer: '<path d="M7 9V4h10v5M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/><rect x="7" y="14" width="10" height="6" rx="1"/>',
  bolt: '<path d="M13 3 5 13.5h6L10 21l8-10.5h-6z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 14a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  collapse: '<path d="m15 6-6 6 6 6"/>',
  expand: '<path d="m9 6 6 6-6 6"/>',
  box: '<path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5z"/><path d="M3.5 7.5 12 12l8.5-4.5M12 12v9"/>',
  more: '<circle cx="6" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18" cy="12" r="1.2"/>',
  scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M16 7l3 3"/>',
};

export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = ICONS[name] || ''; // static strings above, never user data
  return svg;
}

export const eur = (value) => new Intl.NumberFormat(getLocale(), { style: 'currency', currency: 'EUR' }).format(Number(value) || 0);

export function fmt(value, digits = 2) {
  return new Intl.NumberFormat(getLocale(), { maximumFractionDigits: digits }).format(Number(value) || 0);
}

// Accept both "26,99" and "26.99": people type what their keyboard has.
export function parseNum(value) {
  if (typeof value === 'number') return value;
  const n = parseFloat(String(value ?? '').trim().replace(',', '.'));
  return Number.isFinite(n) ? n : 0;
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

export function confirmDialog(message, confirmLabel = t('common.delete')) {
  return new Promise((resolve) => {
    const dialog = h('dialog', { class: 'glass sheet' },
      h('p', {}, message),
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.close('no') }, t('common.cancel')),
        h('button', { class: 'btn danger', type: 'button', onclick: () => dialog.close('yes') }, confirmLabel)));
    dialog.addEventListener('close', () => { resolve(dialog.returnValue === 'yes'); dialog.remove(); });
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
