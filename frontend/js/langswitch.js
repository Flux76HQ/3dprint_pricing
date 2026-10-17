import { LANGUAGES, getLanguage, t } from './i18n.js';
import { h } from './ui.js';

// Flags are drawn here instead of using the emoji: Windows shows regional-indicator emoji as plain letters.
const FLAGS = {
  nl: '<rect width="30" height="6" y="0" fill="#AE1C28"/><rect width="30" height="6" y="6" fill="#fff"/><rect width="30" height="6" y="12" fill="#21468B"/>',
  en: '<rect width="30" height="18" fill="#012169"/><path d="M0 0l30 18M30 0L0 18" stroke="#fff" stroke-width="3.6"/>'
    + '<path d="M0 0l30 18M30 0L0 18" stroke="#C8102E" stroke-width="1.6"/><path d="M15 0v18M0 9h30" stroke="#fff" stroke-width="6"/>'
    + '<path d="M15 0v18M0 9h30" stroke="#C8102E" stroke-width="3.4"/>',
};

function flag(code) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 30 18');
  svg.setAttribute('class', 'flag');
  svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = FLAGS[code] || ''; // static strings above, never user data
  return svg;
}

/** One button per language: a flag, named for screen readers, the current one marked. */
export function langSwitch(onChoose) {
  return h('div', { class: 'lang-switch', role: 'group', 'aria-label': t('lang.label') },
    LANGUAGES.map((l) => h('button', { type: 'button', class: 'flag-btn', lang: l.code, title: l.name, 'aria-label': l.name,
      'aria-pressed': String(getLanguage() === l.code), onclick: () => onChoose(l.code) }, flag(l.code))));
}
