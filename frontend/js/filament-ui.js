import { t } from './i18n.js';
import { fmt, h, icon, spoolName } from './ui.js';

// The colour of a roll: its own colour code when it has one, else a guess from the name ("Black", "zwart", "Jet Black", ...), else none.
const NAMES = {
  black: '#222222', zwart: '#222222', white: '#f2f2f2', wit: '#f2f2f2', grey: '#9e9e9e', gray: '#9e9e9e', grijs: '#9e9e9e', silver: '#c0c0c0', zilver: '#c0c0c0',
  red: '#e53935', rood: '#e53935', orange: '#fb8c00', oranje: '#fb8c00', yellow: '#fdd835', geel: '#fdd835', green: '#43a047', groen: '#43a047',
  blue: '#1e88e5', blauw: '#1e88e5', purple: '#8e24aa', paars: '#8e24aa', violet: '#8e24aa', pink: '#ec407a', roze: '#ec407a', brown: '#6d4c41', bruin: '#6d4c41',
  gold: '#d4af37', goud: '#d4af37', beige: '#d7c4a3', natural: '#e8dcc2', naturel: '#e8dcc2', cream: '#f3e9cf', creme: '#f3e9cf', ivory: '#f6f0dc', ivoor: '#f6f0dc',
  transparent: '#cfe3ea', transparant: '#cfe3ea', clear: '#cfe3ea', cyan: '#00bcd4', magenta: '#d81b60', lime: '#cddc39', turquoise: '#1abc9c', teal: '#009688',
  navy: '#1a237e', marine: '#1a237e', bronze: '#a1662f', brons: '#a1662f', copper: '#b87333', koper: '#b87333', skin: '#e0b99a', huid: '#e0b99a',
};
const HEX = /^#[0-9a-f]{6}$/;

export function colourOf(item) {
  const own = String(item.colour_hex || '').toLowerCase();
  if (HEX.test(own)) return own;
  for (const word of String(item.colour || '').toLowerCase().split(/[^a-zà-ÿ]+/)) if (NAMES[word]) return NAMES[word];
  return null;
}

const NS = 'http://www.w3.org/2000/svg';
const part = (name, attrs) => { const el = document.createElementNS(NS, name); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };

/** A filament spool seen from the front, in the colour of the roll (the wound filament); a roll without a colour gets a neutral one.
    Drawn on the 24 x 24 grid of the Material Design icons (which have no filament spool of their own), with the same keylines. */
export function spoolIcon(colour, size = 36) {
  const svg = part('svg', { viewBox: '0 0 24 24', width: size, height: size, class: 'spool-icon', 'aria-hidden': 'true', focusable: 'false' });
  if (colour && HEX.test(colour)) svg.style.setProperty('--spool-colour', colour);
  const hole = (angle) => part('circle', { cx: (12 + 2.7 * Math.cos(angle)).toFixed(2), cy: (12 + 2.7 * Math.sin(angle)).toFixed(2), r: 0.95, class: 'spool-hole' });
  svg.append(
    part('circle', { cx: 12, cy: 12, r: 10.4, class: 'spool-flange' }),
    part('circle', { cx: 12, cy: 12, r: 8.7, class: 'spool-wound' }),
    part('circle', { cx: 12, cy: 12, r: 7, class: 'spool-turn' }),
    part('circle', { cx: 12, cy: 12, r: 5.2, class: 'spool-hub' }),
    hole(-Math.PI / 2), hole(-Math.PI / 2 + 2 * Math.PI / 3), hole(-Math.PI / 2 + 4 * Math.PI / 3));
  return svg;
}

/** The kinds of filament in stock as tiles: two side by side on a phone, more when there is room, and at most three rows with a
    chevron to show the rest. */
export function stockTiles(groups, { rows = 3 } = {}) {
  const plural = (n) => t('stock.rolls', { n });
  const list = h('ul', { class: 'stock-grid', 'aria-label': t('stock.title') }, groups.map((g) => h('li', { class: ['tile', g.roll_count ? '' : 'out', g.low ? 'low' : ''].join(' ').trim() },
    h('div', { class: 'tile-top' }, spoolIcon(colourOf(g), 40), h('strong', { class: 'tile-grams' }, `${fmt(g.remaining_g, 0)} g`)),
    h('strong', { class: 'tile-name' }, spoolName(g, ' · ')),
    h('p', { class: 'muted tile-meta' }, [g.material, g.roll_count ? plural(g.roll_count) : t('stock.sold_out')].filter(Boolean).join(' · ')),
    g.roll_count ? h('p', { class: 'muted tile-weights' }, t('stock.per_roll', { weights: g.rolls.map((r) => `${fmt(r.remaining_g, 0)} g`).join(', ') })) : null,
    g.notify_low && g.low ? h('p', { class: 'stock-low' }, t('stock.low_badge')) : null)));
  let expanded = false;
  const toggle = h('button', { class: 'btn small more-tiles', type: 'button', hidden: true, 'aria-expanded': 'false', onclick: () => { expanded = !expanded; layout(); } });
  const el = h('div', { class: 'stack' }, list, toggle);

  function layout() {
    const tiles = [...list.children];
    const columns = getComputedStyle(list).gridTemplateColumns.split(' ').filter(Boolean).length || 2;
    const max = columns * rows;
    const over = tiles.length > max;
    tiles.forEach((tile, i) => { tile.hidden = over && !expanded && i >= max; });
    toggle.hidden = !over;
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.replaceChildren(icon(expanded ? 'chevron-up' : 'chevron-down'), h('span', {}, expanded ? t('stock.show_less') : t('stock.show_all', { n: tiles.length })));
  }
  if ('ResizeObserver' in window) new ResizeObserver(layout).observe(list);       // also runs once the list is on the page
  else { window.addEventListener('resize', layout); requestAnimationFrame(layout); }
  return el;
}
