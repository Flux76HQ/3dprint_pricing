// Translations live in /lang/<code>.json (flat keys, {name} placeholders), never in the code.
// `t('key', { n: 3 })` also picks `key_one` / `key_other` when a count `n` is given and those exist.
// The language is the browser's by default; a choice made with the flags is kept in localStorage (for
// the screens before sign-in) and saved with the user's preferences, so every device shows the same.
export const LANGUAGES = [
  { code: 'nl', name: 'Nederlands', locale: 'nl-NL' },
  { code: 'en', name: 'English', locale: 'en-GB' },
];
const DEFAULT_LANGUAGE = 'en';                                  // when the browser speaks neither
const STORAGE_KEY = 'pp-lang';

const catalogs = {};
let current = DEFAULT_LANGUAGE;

const supported = (code) => LANGUAGES.some((l) => l.code === code);

/** The first browser language we have a translation for, else English. */
export function browserLanguage(languages = navigator.languages || [navigator.language]) {
  for (const tag of languages || []) {
    const code = String(tag || '').toLowerCase().split('-')[0];
    if (supported(code)) return code;
  }
  return DEFAULT_LANGUAGE;
}

export function storedLanguage() {
  try { const code = localStorage.getItem(STORAGE_KEY); return supported(code) ? code : null; } catch { return null; }
}

export const getLanguage = () => current;
export const getLocale = () => LANGUAGES.find((l) => l.code === current).locale;

async function load(code) {
  if (catalogs[code]) return;
  const res = await fetch(`/lang/${code}.json`, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`language ${code}`);
  catalogs[code] = await res.json();
}

/** Loads the catalogs (all of them: they are small and a switch must be instant) and selects one. */
export async function initLanguage(preferred) {
  await Promise.all(LANGUAGES.map((l) => load(l.code).catch(() => {})));
  return setLanguage(preferred && supported(preferred) ? preferred : (storedLanguage() || browserLanguage()), { remember: false });
}

export function setLanguage(code, { remember = true } = {}) {
  current = supported(code) && catalogs[code] ? code : DEFAULT_LANGUAGE;
  document.documentElement.lang = current;
  if (remember) { try { localStorage.setItem(STORAGE_KEY, current); } catch { /* private mode */ } }
  return current;
}

const fill = (text, params) => text.replace(/\{(\w+)\}/g, (m, name) => (params && name in params ? String(params[name]) : m));

export function t(key, params) {
  const pick = (lang) => {
    const catalog = catalogs[lang];
    if (!catalog) return undefined;
    if (params && typeof params.n === 'number') {
      const plural = catalog[`${key}_${params.n === 1 ? 'one' : 'other'}`];
      if (plural !== undefined) return plural;
    }
    return catalog[key];
  };
  const text = pick(current) ?? pick(DEFAULT_LANGUAGE) ?? pick('nl');
  return text === undefined ? key : fill(text, params);   // a missing key shows itself: visible, never blank
}

// Dates and times in the language of the screen.
export const formatDate = (value, options) => new Date(value).toLocaleDateString(getLocale(), options);
export const formatTime = (value, options) => new Date(value).toLocaleTimeString(getLocale(), options);
export const formatDateTime = (value, options) => new Date(value).toLocaleString(getLocale(), options);
