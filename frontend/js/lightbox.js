// A pop-up to look at pictures one after the other, large: the chevrons (and the arrow keys) go to the previous or the next one, a swipe does on
// a touch screen, and every picture can be saved from here. The pictures lie side by side in one row that the browser scrolls and snaps
// (`scroll-snap`, css), so the swipe, its momentum and the stop on exactly one picture are the browser's own; this only works out which one is
// in view and moves it when a button or a key asks. It is a normal pop-up (`enhanceDialog`): the X, Escape and the Android back gesture close it.
import { t } from './i18n.js';
import { enhanceDialog, fill, h, icon } from './ui.js';

const smooth = () => !window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Opens the pictures of `items` ({ src, alt, title, badges: [text] }) with `start` in view. `save(item)` is what *Opslaan* does for the one in view:
 *  the button waits for it, and what it throws is shown in the pop-up (a toast would be behind it). The pop-up removes itself when it is closed. Returns the dialog. */
export function openLightbox(items, start = 0, { save } = {}) {
  if (!items.length) return null;
  const many = items.length > 1;
  let index = Math.min(Math.max(start, 0), items.length - 1);

  const slides = items.map((item, i) => h('figure', { class: 'lightbox-slide', role: 'group', 'aria-label': t('lightbox.position', { n: i + 1, total: items.length }) },
    h('img', { src: item.src, alt: item.alt || item.title || '', draggable: 'false', decoding: 'async' })));
  const track = h('div', { class: 'lightbox-track', tabindex: '0', role: 'region', 'aria-label': t('lightbox.title') }, slides);

  /** Brings picture `to` into view (a swipe does the same by itself). */
  const go = (to) => {
    const target = Math.min(Math.max(to, 0), items.length - 1);
    track.scrollTo({ left: target * track.clientWidth, behavior: smooth() ? 'smooth' : 'auto' });
  };
  const nav = (side, label, step) => h('button', { class: `lightbox-nav ${side}`, type: 'button', 'aria-label': label, title: label, onclick: () => go(index + step) },
    icon(`chevron-${side === 'prev' ? 'left' : 'right'}`));
  const prev = many ? nav('prev', t('lightbox.previous'), -1) : null;
  const next = many ? nav('next', t('lightbox.next'), 1) : null;

  const title = h('strong', { class: 'lightbox-title' });
  const badges = h('span', { class: 'row lightbox-badges' });
  const count = h('span', { class: 'lightbox-count', 'aria-live': 'polite' });
  const error = h('p', { class: 'error lightbox-error', role: 'alert', hidden: true });
  const saveButton = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    saveButton.disabled = true;
    error.hidden = true;
    try { await save(items[index]); } catch (e) { error.textContent = e.message; error.hidden = false; }
    saveButton.disabled = false;
  } }, icon('download'), t('lightbox.save'));

  /** What the header and the buttons say about the picture in view. */
  function update() {
    const item = items[index];
    title.textContent = item.title || '';
    fill(badges, (item.badges || []).map((text) => h('span', { class: 'badge' }, text)));
    count.textContent = many ? t('lightbox.position', { n: index + 1, total: items.length }) : '';
    if (prev) prev.disabled = index === 0;
    if (next) next.disabled = index === items.length - 1;
  }
  // The picture in view follows the scroll position (a swipe, a click on a chevron, the arrow keys all move it).
  track.addEventListener('scroll', () => {
    const width = track.clientWidth;
    const at = width ? Math.round(track.scrollLeft / width) : index;
    if (at === index || at < 0 || at >= items.length) return;
    index = at;
    error.hidden = true;                                        // what went wrong with the picture before is not about this one
    update();
    for (const button of [prev, next]) if (button && button.disabled && document.activeElement === button) track.focus({ preventScroll: true });   // a disabled button cannot keep the focus
  }, { passive: true });

  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet lightbox', 'aria-label': t('lightbox.title') },
    h('div', { class: 'lightbox-head' }, h('div', { class: 'lightbox-what' }, title, badges), count),
    h('div', { class: 'lightbox-stage' }, track, prev, next),
    save ? h('div', { class: 'lightbox-foot' }, error, saveButton) : null));

  // Arrow keys, while this is the pop-up on top (a confirmation opened over it keeps them to itself).
  const onKey = (event) => {
    const open = document.querySelectorAll('dialog[open]');
    if (!dialog.open || open[open.length - 1] !== dialog || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const step = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
    if (!step) return;
    event.preventDefault();
    go(index + step);
  };
  document.addEventListener('keydown', onKey, true);
  // A click beside the picture closes it, unless it began inside and was dragged out (selecting, swiping).
  let pressedOutside = false;
  dialog.addEventListener('pointerdown', (event) => { pressedOutside = event.target === dialog; });
  dialog.addEventListener('click', (event) => { if (pressedOutside && event.target === dialog) dialog.requestClose(); });
  // A turned phone or a resized window changes the width of a picture: stay on the one in view instead of between two.
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(() => track.scrollTo({ left: index * track.clientWidth, behavior: 'auto' })) : null;
  dialog.addEventListener('close', () => {
    document.removeEventListener('keydown', onKey, true);
    if (observer) observer.disconnect();
    dialog.remove();
  });

  update();
  document.body.append(dialog);
  dialog.showModal();
  track.scrollTo({ left: index * track.clientWidth, behavior: 'auto' });   // the one that was clicked, before anything is seen to move
  if (observer) observer.observe(track);
  return dialog;
}
