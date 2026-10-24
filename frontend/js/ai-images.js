// AI product images (only built when the server says `ai_images`, i.e. AI_IMAGES_ENABLED=TRUE in .env):
// the OpenAI key under Settings, and the "Productafbeeldingen" card in a calculation.
import { api, downloadFile, upload } from './api.js';
import { t } from './i18n.js';
import { confirmDialog, field, h, saveBlob, toast } from './ui.js';

// The server makes one picture per request (each takes a while); these are asked for one after the other.
const VARIANTS = ['square', 'landscape', 'portrait', 'studio'];
const VARIANT_LABEL = { square: 'ai.variant_square', landscape: 'ai.variant_landscape', portrait: 'ai.variant_portrait', studio: 'ai.variant_studio' };
const QUALITIES = [['low', 'ai.quality_low'], ['medium', 'ai.quality_medium'], ['high', 'ai.quality_high']];
const imageUrl = (id) => `/api/project-images/${id}/file`;

export const coverUrl = imageUrl;

// --- Settings ---------------------------------------------------------------------

export function aiSettingsCard() {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  let lastError = '';
  async function draw() {
    let info;
    try { info = await api('GET', '/api/ai-images/settings'); } catch (e) { body.replaceChildren(h('p', { class: 'error', role: 'alert' }, e.message)); return; }
    const key = h('input', { type: 'password', autocomplete: 'off', spellcheck: 'false', autocapitalize: 'off',
      placeholder: info.configured && info.readable ? `••••••••${info.last4}` : 'sk-…' });
    const model = h('input', { type: 'text', autocomplete: 'off', spellcheck: 'false', value: info.model, maxlength: 60 });
    const quality = h('select', {}, QUALITIES.map(([q, label]) => h('option', { value: q, selected: info.quality === q }, t(label))));
    const run = async (work) => {
      try { await work(); lastError = ''; } catch (e) { lastError = e.message; }
      draw();
    };
    const save = () => run(async () => {
      const change = { model: model.value.trim(), quality: quality.value };
      if (key.value.trim()) change.api_key = key.value.trim();
      await api('PUT', '/api/ai-images/settings', change);
      toast(t('ai.saved'));
    });
    const test = () => run(async () => { await api('POST', '/api/ai-images/test'); toast(t('ai.test_ok')); });
    const forget = async () => {
      if (!(await confirmDialog(t('ai.key_remove_confirm'), t('common.delete')))) return;
      run(() => api('DELETE', '/api/ai-images/key'));
    };
    body.replaceChildren(
      h('p', { class: 'muted' }, t('ai.intro')),
      info.configured
        ? h('p', { class: info.readable ? 'status-line' : 'error', role: 'status' }, info.readable ? t('ai.key_set', { last4: info.last4 }) : t('ai.key_unreadable'))
        : h('p', { class: 'muted' }, t('ai.key_none')),
      field(info.configured ? t('ai.key_replace') : t('ai.key'), key, t('ai.key_hint')),
      h('div', { class: 'two' },
        field(t('ai.model'), model, t('ai.model_hint')),
        field(t('ai.quality'), quality, t('ai.quality_hint'))),
      h('div', { class: 'row' },
        h('button', { class: 'btn primary', type: 'button', onclick: save }, t('common.save')),
        info.configured ? h('button', { class: 'btn', type: 'button', onclick: test }, t('ai.test')) : null,
        info.configured ? h('button', { class: 'btn danger', type: 'button', onclick: forget }, t('ai.key_remove')) : null),
      h('p', { class: 'error', role: 'alert', hidden: !lastError }, lastError));
  }
  draw();
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('ai.title')), body);
}

// --- In a calculation -------------------------------------------------------------

/** The card with the photo of the object and the pictures made from it. `getDescription()` is what the form says now (saved or not). */
export function productImagesCard(projectId, getDescription) {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  let images = [];
  let busy = '';                                                      // what is being made right now, shown instead of the button
  let lastError = '';

  async function load() {
    try { images = await api('GET', `/api/projects/${projectId}/images`); lastError = ''; } catch (e) { lastError = e.message; }
    draw();
  }

  async function addPhoto(file) {
    const form = new FormData();
    form.append('file', file);
    busy = t('ai.uploading');
    draw();
    try { await upload(`/api/projects/${projectId}/images/source`, form); lastError = ''; } catch (e) { lastError = e.message; }
    busy = '';
    await load();
  }

  async function generate() {
    if (!(await confirmDialog(t('ai.generate_confirm', { n: VARIANTS.length }), t('ai.generate')))) return;
    lastError = '';
    for (let i = 0; i < VARIANTS.length; i += 1) {
      busy = t('ai.generating', { done: i + 1, n: VARIANTS.length });
      draw();
      try {
        await api('POST', `/api/projects/${projectId}/images/generate`, { variant: VARIANTS[i], description: getDescription() });
        images = await api('GET', `/api/projects/${projectId}/images`);
      } catch (e) { lastError = e.message; break; }                 // a key or credit problem would fail every other one as well
    }
    busy = '';
    draw();
  }

  async function act(work) {
    try { await work(); lastError = ''; } catch (e) { lastError = e.message; }
    await load();
  }

  async function download(image) {
    try {
      const { blob, name } = await downloadFile(`${imageUrl(image.id)}?download=1`);
      saveBlob(blob, name);
    } catch (e) { toast(e.message, 'error'); }
  }

  function tile(image) {
    return h('figure', { class: 'ai-tile' },
      h('img', { src: imageUrl(image.id), alt: t(VARIANT_LABEL[image.variant]), loading: 'lazy', width: image.width_px, height: image.height_px }),
      h('figcaption', {}, h('strong', {}, t(VARIANT_LABEL[image.variant])), image.is_cover ? h('span', { class: 'badge' }, t('ai.cover')) : null),
      h('div', { class: 'row wrap' },
        h('button', { class: 'btn small', type: 'button', onclick: () => download(image) }, t('ai.download')),
        image.is_cover ? null : h('button', { class: 'btn small', type: 'button', onclick: () => act(() => api('PUT', `/api/project-images/${image.id}/cover`)) }, t('ai.make_cover')),
        h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
          if (await confirmDialog(t('ai.delete_confirm'), t('common.delete'))) act(() => api('DELETE', `/api/project-images/${image.id}`));
        } }, t('common.delete'))));
  }

  function draw() {
    const source = images.find((i) => i.kind === 'source');
    const made = images.filter((i) => i.kind === 'generated');
    const file = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', disabled: !!busy, 'aria-label': t('ai.photo_choose'),
      onchange: () => { const chosen = file.files[0]; if (chosen) addPhoto(chosen); } });
    body.replaceChildren(
      h('p', { class: 'muted' }, t('ai.card_intro')),
      source ? h('img', { class: 'ai-source', src: imageUrl(source.id), alt: t('ai.photo_alt') }) : h('p', { class: 'muted' }, t('ai.photo_none')),
      field(source ? t('ai.photo_replace') : t('ai.photo_choose'), file, t('ai.photo_hint')),
      busy
        ? h('p', { class: 'status-line', role: 'status' }, busy)
        : h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', disabled: !source, onclick: generate }, t('ai.generate'))),
      h('p', { class: 'error', role: 'alert', hidden: !lastError }, lastError),
      made.length ? h('div', { class: 'ai-grid' }, made.map(tile)) : null);
  }

  load();
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('ai.card_title')), body);
}
