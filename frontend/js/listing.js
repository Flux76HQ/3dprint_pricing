// The card "Verkoopitem" in the editor of a 3D model: what the model is offered for sale as. The title and text of the advertisement, a
// price that is typed (the calculation only advises one), an EAN for a channel that wants one, and the photos in their order: own uploads
// and product pictures of the model taken over. Under it, everything put ready to place an advertisement by hand.
import { api, upload } from './api.js';
import { t } from './i18n.js';
import { confirmDialog, enhanceDialog, eur, field, fill, foldHead, fmt, h, icon, numberInput, parseNum, toast } from './ui.js';

// Where Marktplaats itself starts a new advertisement (the link behind its own "Plaats advertentie").
const MARKTPLAATS_PLACE = 'https://link.marktplaats.nl/link/placead/start';

async function copy(value, done) {
  try { await navigator.clipboard.writeText(value); toast(done); } catch { toast(t('common.copy_failed'), 'error'); }
}

/**
 * `source` says what the editor knows: `name()` the model's name, `texts()` its product texts ({ product_name, specs, extra_text }),
 * `advice()` what the calculation makes of it now ({ price, cost } incl. VAT, or null while it is not worked out), `aiImages` whether
 * the model can have product pictures, and `changed()` to call when something here needs saving.
 * Returns the card, `dirty()`, `save()` (resolves to whether the editor can go on) and `refresh()` for when the advice changed.
 */
export function listingCard(projectId, source) {
  const state = { exists: false, title: '', description: '', price: '', ean: '', photos: [], max: 12 };
  let dirty = false;
  const touch = () => { dirty = true; source.changed(); };

  const title = h('input', { type: 'text', maxlength: 80, placeholder: t('listing.title_ph'), oninput: (e) => { state.title = e.target.value; touch(); } });
  const description = h('textarea', { rows: 6, maxlength: 4000, placeholder: t('listing.description_ph'), oninput: (e) => { state.description = e.target.value; touch(); } });
  const price = numberInput('', (v) => { state.price = v; touch(); drawAdvice(); });
  const ean = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', maxlength: 20, oninput: (e) => { state.ean = e.target.value; touch(); } });
  const advice = h('p', { class: 'hint', role: 'status' });
  const takeOver = h('button', { class: 'btn tool', type: 'button', hidden: true, onclick: () => {
    const texts = source.texts() || {};
    state.title = (texts.product_name || source.name() || '').slice(0, 80);
    state.description = [texts.extra_text, ...(texts.specs || []).map((line) => `- ${line}`)].filter(Boolean).join('\n');
    title.value = state.title;
    description.value = state.description;
    touch(); drawTakeOver();
  } }, icon('copy'), h('span', {}, t('listing.take_over')));
  const photos = h('div', { class: 'photo-grid' });
  const place = h('div', { class: 'stack' });
  const remove = h('button', { class: 'btn tool danger', type: 'button', hidden: true, onclick: async () => {
    if (!(await confirmDialog(t('listing.remove_confirm'), t('listing.remove')))) return;
    try { await api('DELETE', `/api/projects/${projectId}/listing`); toast(t('listing.removed')); dirty = false; await load(); } catch (e) { toast(e.message, 'error'); }
  } }, icon('trash'), h('span', {}, t('listing.remove')));

  function drawTakeOver() {
    const texts = source.texts() || {};
    takeOver.hidden = !!(state.title || state.description) || !(texts.product_name || texts.extra_text || (texts.specs || []).length || source.name());
  }

  // What the calculation advises, next to what was typed: a price under the advice is said, one under the cost price is a warning.
  function drawAdvice() {
    const now = source.advice();
    if (!now) { advice.textContent = t('listing.price_hint'); advice.className = 'hint'; return; }
    const typed = state.price === '' ? null : parseNum(state.price);
    const under = typed !== null && typed < Number(now.cost);         // the cost price is without VAT and the typed price with: under it is under it either way
    advice.className = `hint${under ? ' error' : ''}`;
    advice.textContent = [t('listing.advice', { price: eur(now.price) }),
      under ? t('listing.under_cost', { price: eur(now.cost) }) : (typed !== null && typed < Number(now.price) ? t('listing.under_advice') : null)].filter(Boolean).join(' ');
  }

  function move(index, by) {
    const to = index + by;
    if (to < 0 || to >= state.photos.length) return;
    state.photos.splice(to, 0, state.photos.splice(index, 1)[0]);
    touch(); drawPhotos();
  }

  function drawPhotos() {
    fill(photos, state.photos.map((photo, i) => h('figure', { class: 'photo' },
      h('img', { src: photo.url, alt: t('listing.photo_n', { n: i + 1 }), loading: 'lazy' }),
      i === 0 ? h('span', { class: 'badge photo-first' }, t('listing.photo_first')) : null,
      h('figcaption', { class: 'row-actions' },
        h('button', { class: 'btn tool icon-only', type: 'button', disabled: i === 0, title: t('listing.photo_earlier'), 'aria-label': t('listing.photo_earlier'), onclick: () => move(i, -1) }, icon('collapse')),
        h('button', { class: 'btn tool icon-only', type: 'button', disabled: i === state.photos.length - 1, title: t('listing.photo_later'), 'aria-label': t('listing.photo_later'), onclick: () => move(i, 1) }, icon('expand')),
        h('button', { class: 'btn tool icon-only danger', type: 'button', title: t('listing.photo_remove'), 'aria-label': t('listing.photo_remove'),
          onclick: () => { state.photos.splice(i, 1); touch(); drawPhotos(); } }, icon('trash'))))),
    state.photos.length ? null : h('p', { class: 'muted line-none' }, t('listing.no_photos')));
    add.disabled = state.photos.length >= state.max;
    if (fromModel) fromModel.disabled = state.photos.length >= state.max;
    drawPlace();
  }

  // An own photo is sent at once (it is a file, not a field); where it stands in the order is saved with the rest.
  const file = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', multiple: true, hidden: true, onchange: async () => {
    for (const chosen of [...file.files].slice(0, state.max - state.photos.length)) {
      const form = new FormData();
      form.append('file', chosen);
      try { state.photos.push(await upload(`/api/projects/${projectId}/listing/photos`, form)); } catch (e) { toast(e.message, 'error'); break; }
    }
    file.value = '';
    drawPhotos();
  } });
  const add = h('button', { class: 'btn tool', type: 'button', onclick: () => file.click() }, icon('plus'), h('span', {}, t('listing.photo_add')));
  const fromModel = source.aiImages ? h('button', { class: 'btn tool', type: 'button', onclick: pickFromModel }, icon('copy'), h('span', {}, t('listing.photo_from_model'))) : null;

  /** The model's product pictures, to take one or more over as photos of the listing (each a copy). */
  async function pickFromModel() {
    let images = [];
    try { images = (await api('GET', `/api/projects/${projectId}/images`)).images.filter((image) => image.kind === 'generated'); } catch (e) { toast(e.message, 'error'); return; }
    const grid = h('div', { class: 'photo-grid' }, images.length ? images.map((image) => {
      const button = h('button', { class: 'photo pick', type: 'button', onclick: async () => {
        try {
          state.photos.push(await api('POST', `/api/projects/${projectId}/listing/photos`, { image_id: image.id }));
          button.disabled = true;
          button.classList.add('picked');
          drawPhotos();
        } catch (e) { toast(e.message, 'error'); }
      } }, h('img', { src: `/api/project-images/${image.id}/thumb`, alt: t('listing.photo_take', { name: image.variant || '' }), loading: 'lazy' }));
      return button;
    }) : h('p', { class: 'muted' }, t('listing.no_product_pictures')));
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, h('div', { class: 'stack' },
      h('h2', {}, t('listing.photo_from_model')), h('p', { class: 'muted' }, t('listing.photo_from_model_hint')), grid,
      h('div', { class: 'row end' }, h('button', { class: 'btn primary', type: 'button', onclick: () => dialog.close() }, t('common.done'))))));
    dialog.addEventListener('close', () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
  }

  // Everything put ready to place an advertisement by hand: the texts to copy, the photos in one file, and where to start.
  function drawPlace() {
    fill(place, state.exists && !dirty ? [
      h('div', { class: 'row' },
        h('button', { class: 'btn tool', type: 'button', onclick: () => copy(state.title, t('listing.copied_title')) }, icon('copy'), h('span', {}, t('listing.copy_title'))),
        h('button', { class: 'btn tool', type: 'button', onclick: () => copy(state.description, t('listing.copied_text')) }, icon('copy'), h('span', {}, t('listing.copy_text'))),
        state.photos.length ? h('a', { class: 'btn tool', href: `/api/projects/${projectId}/listing/photos.zip` }, icon('download'), h('span', {}, t('listing.download_photos', { n: state.photos.length }))) : null,
        h('a', { class: 'btn tool', href: MARKTPLAATS_PLACE, target: '_blank', rel: 'noopener noreferrer' }, icon('external'), h('span', {}, t('listing.open_marktplaats')))),
      h('p', { class: 'hint' }, t('listing.place_hint'))] : h('p', { class: 'hint' }, t('listing.place_after_save')));
  }

  function show(data) {
    const listing = data.listing;
    Object.assign(state, { exists: !!listing, title: listing?.title || '', description: listing?.description || '', price: listing?.price ?? '', ean: listing?.ean || '',
      photos: data.photos, max: data.max_photos });
    title.value = state.title;
    description.value = state.description;
    price.value = state.price === '' ? '' : fmt(state.price);
    ean.value = state.ean;
    remove.hidden = !state.exists;
    drawTakeOver(); drawAdvice(); drawPhotos();
  }

  async function load() {
    try { show(await api('GET', `/api/projects/${projectId}/listing`)); } catch (e) { toast(e.message, 'error'); }
  }

  /** Saves what was typed and the order of the photos. Nothing typed and no listing yet: nothing to save. */
  async function save() {
    if (!dirty) return true;
    if (!state.exists && !state.title.trim() && !state.description.trim() && state.price === '' && !state.ean.trim() && !state.photos.length) { dirty = false; return true; }
    if (!state.title.trim()) { toast(t('listing.title_needed'), 'error'); title.focus(); return false; }
    try {
      const body = { title: state.title.trim(), description: state.description, price: state.price === '' ? '' : parseNum(state.price), ean: state.ean.trim(),
        photos: state.photos.map((photo) => photo.id) };
      dirty = false;
      show(await api('PUT', `/api/projects/${projectId}/listing`, body));
      return true;
    } catch (e) { dirty = true; toast(e.message, 'error'); return false; }
  }

  load();
  const el = h('div', { class: 'glass card stack listing' },
    foldHead('listing', t('listing.card_title')),
    h('p', { class: 'muted' }, t('listing.intro')),
    h('div', { class: 'row' }, takeOver),
    field(t('listing.title'), title, t('listing.title_hint')),
    field(t('listing.description'), description),
    h('div', { class: 'two even' },
      h('div', { class: 'field' }, field(t('listing.price'), price), advice),
      field(t('listing.ean'), ean, t('listing.ean_hint'))),
    h('div', { class: 'line-group' },
      h('div', { class: 'sub-head' }, h('h3', {}, t('listing.photos')), h('div', { class: 'row' }, fromModel, add, file)),
      photos),
    h('div', { class: 'line-group' }, h('div', { class: 'sub-head' }, h('h3', {}, t('listing.place')), remove), place));
  return { el, dirty: () => dirty, save, refresh: drawAdvice };
}
