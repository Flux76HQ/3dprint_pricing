// AI product images (only built when the server says `ai_images`, i.e. AI_IMAGES_ENABLED=TRUE in .env):
// the OpenAI key and the log under Settings, and the "Productafbeeldingen" card in a calculation.
// The pictures are made by the server in the background: this page only asks for them and then polls how far they are, so leaving
// the page (or closing the browser) does not stop anything; the card picks the progress up again when it is shown.
import { api, downloadFile, upload } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { confirmDialog, field, fill, h, saveBlob, toast } from './ui.js';

const VARIANT_LABEL = { square: 'ai.variant_square', landscape: 'ai.variant_landscape', portrait: 'ai.variant_portrait', studio: 'ai.variant_studio' };
const QUALITIES = [['low', 'ai.quality_low'], ['medium', 'ai.quality_medium'], ['high', 'ai.quality_high']];
const POLL_MS = 3000;
const LOG_POLL_MS = 5000;
const imageUrl = (id) => `/api/project-images/${id}/file`;

export const coverUrl = imageUrl;

/** Runs `load` now and again every `ms` while `watch()` says so, until the element has been taken off the page (the user went elsewhere). */
function keepFresh(element, load, ms, watch = () => true) {
  let timer = null;
  let seen = false;
  const tick = async () => {
    clearTimeout(timer);
    if (element.isConnected) seen = true;
    else if (seen) return;                                         // it was on the page and is gone: stop asking
    await load();
    if (watch()) timer = setTimeout(tick, ms);
  };
  return tick;
}

const spinner = (small = false) => h('span', { class: `spinner${small ? ' small' : ''}`, 'aria-hidden': 'true' });

// --- Settings ---------------------------------------------------------------------

export function aiSettingsCard() {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  let lastError = '';
  async function draw() {
    let info;
    try { info = await api('GET', '/api/ai-images/settings'); } catch (e) { fill(body, h('p', { class: 'error', role: 'alert' }, e.message)); return; }
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
    fill(body,
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

// --- The log ----------------------------------------------------------------------

/** What happened when pictures were made (and what went wrong), newest first. It refreshes itself while it is on the page. */
export function aiLogCard() {
  const list = h('ul', { class: 'ai-log' }, h('li', { class: 'muted' }, t('common.loading')));
  let lastError = '';
  const row = (e) => h('li', { class: `ai-log-row ${e.level}` },
    h('time', { datetime: e.created_at }, formatDateTime(e.created_at, { dateStyle: 'short', timeStyle: 'medium' })),
    h('span', { class: `log-level ${e.level}` }, t(e.level === 'error' ? 'ai.log_error' : 'ai.log_info')),
    h('div', { class: 'ai-log-text' },
      h('span', { class: e.level === 'error' ? 'error' : '' }, e.message),
      e.project_id || e.variant ? h('span', { class: 'muted' }, ' · ', e.project_id
        ? h('a', { href: `#/berekeningen/${e.project_id}` }, `#${e.project_number ?? ''} ${e.project_name ?? ''}`.trim()) : null,
        e.project_id && e.variant ? ' · ' : null, e.variant ? t(VARIANT_LABEL[e.variant]) : null) : null,
      e.detail ? h('code', { class: 'ai-log-detail' }, e.detail) : null));
  async function load() {
    try {
      const entries = await api('GET', '/api/ai-images/log');
      lastError = '';
      fill(list, entries.length ? entries.map(row) : h('li', { class: 'muted' }, t('ai.log_empty')));
    } catch (e) { lastError = e.message; }
    error.textContent = lastError;
    error.hidden = !lastError;
  }
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const card = h('div', { class: 'glass card stack' }, h('h2', {}, t('ai.log_title')), h('p', { class: 'muted' }, t('ai.log_intro')),
    h('div', { class: 'row' },
      h('button', { class: 'btn small', type: 'button', onclick: load }, t('ai.log_refresh')),
      h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
        if (!(await confirmDialog(t('ai.log_clear_confirm'), t('ai.log_clear')))) return;
        try { await api('DELETE', '/api/ai-images/log'); toast(t('ai.log_emptied')); } catch (e) { toast(e.message, 'error'); }
        load();
      } }, t('ai.log_clear'))),
    error, list);
  setTimeout(keepFresh(card, load, LOG_POLL_MS), 0);
  return card;
}

// --- In a calculation -------------------------------------------------------------

/** The card with the photo of the object and the pictures made from it. `getDescription()` is what the form says now (saved or not). */
export function productImagesCard(projectId, getDescription) {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  let images = [];
  let jobs = [];
  let uploading = false;
  let wasBusy = false;
  let lastError = '';
  const busy = () => jobs.some((j) => j.status === 'queued' || j.status === 'running');

  async function load() {
    try {
      const got = await api('GET', `/api/projects/${projectId}/images`);
      images = got.images;
      jobs = got.jobs;
      lastError = '';
    } catch (e) { lastError = e.message; }
    if (wasBusy && !busy()) {                                      // it finished while this page was watching
      if (jobs.some((j) => j.status === 'failed')) toast(t('ai.done_errors'), 'error'); else toast(t('ai.done'));
    }
    wasBusy = busy();
    draw();
  }
  const refresh = keepFresh(body, load, POLL_MS, busy);

  async function addPhoto(file) {
    const form = new FormData();
    form.append('file', file);
    uploading = true;
    draw();
    try { await upload(`/api/projects/${projectId}/images/source`, form); lastError = ''; } catch (e) { lastError = e.message; }
    uploading = false;
    await refresh();
  }

  async function generate() {
    if (!(await confirmDialog(t('ai.generate_confirm'), t('ai.generate')))) return;
    lastError = '';
    try { await api('POST', `/api/projects/${projectId}/images/generate`, { description: getDescription() }); } catch (e) { lastError = e.message; }
    await refresh();                                               // shows what was queued and keeps asking while it runs
  }

  async function act(work) {
    try { await work(); lastError = ''; } catch (e) { lastError = e.message; }
    await refresh();
  }

  async function download(image) {
    try {
      const { blob, name } = await downloadFile(`${imageUrl(image.id)}?download=1`);
      saveBlob(blob, name);
    } catch (e) { toast(e.message, 'error'); }
  }

  const label = (variant) => t(VARIANT_LABEL[variant]);

  function tile(image) {
    return h('figure', { class: 'ai-tile' },
      h('img', { src: imageUrl(image.id), alt: label(image.variant), loading: 'lazy', width: image.width_px, height: image.height_px }),
      h('figcaption', {}, h('strong', {}, label(image.variant)), image.is_cover ? h('span', { class: 'badge' }, t('ai.cover')) : null),
      h('div', { class: 'row wrap' },
        h('button', { class: 'btn small', type: 'button', onclick: () => download(image) }, t('ai.download')),
        image.is_cover ? null : h('button', { class: 'btn small', type: 'button', onclick: () => act(() => api('PUT', `/api/project-images/${image.id}/cover`)) }, t('ai.make_cover')),
        h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
          if (await confirmDialog(t('ai.delete_confirm'), t('common.delete'))) act(() => api('DELETE', `/api/project-images/${image.id}`));
        } }, t('common.delete'))));
  }

  // A picture that is still to come: a pulsing frame of its own shape with a spinner.
  function pending(job) {
    return h('figure', { class: 'ai-tile pending', 'aria-busy': 'true' },
      h('div', { class: `ai-skeleton v-${job.variant}` }, spinner()),
      h('figcaption', {}, h('strong', {}, label(job.variant)),
        h('span', { class: 'muted' }, t(job.status === 'running' ? 'ai.pending_running' : 'ai.pending_queued'))));
  }

  function draw() {
    const source = images.find((i) => i.kind === 'source');
    const made = images.filter((i) => i.kind === 'generated');
    const coming = jobs.filter((j) => j.status === 'queued' || j.status === 'running');
    const failed = jobs.filter((j) => j.status === 'failed');
    const finished = jobs.filter((j) => j.status === 'done').length;
    const working = coming.length > 0;
    const file = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', disabled: uploading || working, 'aria-label': t('ai.photo_choose'),
      onchange: () => { const chosen = file.files[0]; if (chosen) addPhoto(chosen); } });
    fill(body,
      h('p', { class: 'muted' }, t('ai.card_intro')),
      source ? h('img', { class: 'ai-source', src: imageUrl(source.id), alt: t('ai.photo_alt') }) : h('p', { class: 'muted' }, t('ai.photo_none')),
      field(source ? t('ai.photo_replace') : t('ai.photo_choose'), file, t('ai.photo_hint')),
      uploading ? h('div', { class: 'ai-progress', role: 'status' }, spinner(), h('strong', {}, t('ai.uploading'))) : null,
      working
        ? h('div', { class: 'ai-progress', role: 'status' }, spinner(),
          h('div', {}, h('strong', {}, t('ai.generating', { done: finished, n: finished + coming.length })), h('p', { class: 'hint' }, t('ai.generating_hint'))))
        : h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', disabled: !source || uploading, onclick: generate }, t('ai.generate'))),
      h('p', { class: 'error', role: 'alert', hidden: !lastError }, lastError),
      failed.length && !working ? h('div', { class: 'stack ai-failed', role: 'alert' },
        h('strong', { class: 'error' }, t('ai.failed_title')),
        h('ul', {}, failed.map((j) => h('li', {}, h('strong', {}, label(j.variant)), ': ', j.message))),
        h('div', { class: 'row' },
          h('a', { class: 'btn small', href: '#/instellingen/ai' }, t('ai.view_log')),
          h('button', { class: 'btn small', type: 'button', onclick: () => act(() => api('DELETE', `/api/projects/${projectId}/images/jobs`)) }, t('ai.failed_dismiss')))) : null,
      made.length || coming.length ? h('div', { class: 'ai-grid' }, made.map(tile), coming.map(pending)) : null);
  }

  setTimeout(refresh, 0);
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('ai.card_title')), body);
}

/** The "busy" mark on a calculation in the list. */
export const busyBadge = () => h('span', { class: 'badge ai-busy', role: 'status' }, spinner(true), t('ai.busy_badge'));
