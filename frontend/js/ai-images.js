// AI product images (only built when the server says `ai_images`, i.e. AI_IMAGES_ENABLED=TRUE in .env):
// the OpenAI key and the log under Settings, and the "Productafbeeldingen" card in a calculation.
// The pictures are made by the server in the background: this page only asks for them and then polls how far they are, so leaving
// the page (or closing the browser) does not stop anything; the card picks the progress up again when it is shown.
import { api, downloadFile, upload } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { confirmDialog, field, fill, h, saveBlob, switchRow, toast } from './ui.js';

const VARIANT_LABEL = { square: 'ai.variant_square', landscape: 'ai.variant_landscape', portrait: 'ai.variant_portrait', studio: 'ai.variant_studio', detail: 'ai.variant_detail', context: 'ai.variant_context' };
// What the pictures are for; the server makes four per purpose and has a template with its own colours for each.
const PURPOSE_LABEL = { marktplaats: 'ai.purpose_marktplaats', social: 'ai.purpose_social', webshop: 'ai.purpose_webshop' };
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

/** The card with the photo of the object and the pictures made from it. `getDescription()` is what the form says now (saved or not);
 *  `businessOn()` says whether the business mode is on now (only then can the logo be put on a picture). */
export function productImagesCard(projectId, getDescription, businessOn = () => false) {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  // The purpose and the texts. Built once, when the first answer is in: the part below is redrawn while pictures are made, and a
  // field that is redrawn loses what is being typed in it.
  const options = h('div', { class: 'stack', hidden: true });
  let form = null;
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
      if (!form) buildForm(got);
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

  function buildForm(got) {
    const saved = got.text;
    const limits = got.limits;
    const purpose = h('select', { onchange: () => { store(); draw(); } },
      h('option', { value: '' }, t('ai.purpose_choose')),
      Object.keys(got.purposes).map((p) => h('option', { value: p, selected: saved.purpose === p }, t(PURPOSE_LABEL[p]))));
    const name = h('input', { type: 'text', maxlength: limits.product_name, value: saved.product_name, placeholder: t('ai.product_name_ph') });
    const specs = h('textarea', { rows: 4, placeholder: t('ai.specs_ph') }, saved.specs.join('\n'));
    const extra = h('input', { type: 'text', maxlength: limits.extra_text, value: saved.extra_text, placeholder: t('ai.extra_text_ph') });
    const status = h('p', { class: 'hint', role: 'status' });
    let logo = saved.logo;
    const specLines = () => specs.value.split('\n').map((line) => line.trim()).filter(Boolean);
    // The logo is the business's: without the business mode the switch is shown off and cannot be turned (the saved choice is kept).
    const business = businessOn();
    const logoRow = switchRow(t('ai.logo'), t(!business ? 'ai.logo_hint_off' : got.logo_available ? 'ai.logo_hint_on' : 'ai.logo_hint_none'),
      business && logo, (on) => { logo = on; store(); });
    logoRow.querySelector('.switch').disabled = !business;
    form = {
      values: () => ({ purpose: purpose.value || null, product_name: name.value.trim(), specs: specLines(), extra_text: extra.value.trim(), logo }),
      complete: () => !!(name.value.trim() && specLines().length && extra.value.trim()),
      logoShown: () => business && logo && got.logo_available,
    };
    const tell = () => { status.textContent = t(form.complete() ? 'ai.text_on' : 'ai.text_off'); };
    // Kept as soon as a field is left, so the texts are there the next time, also when no pictures are made now.
    async function store() {
      tell();
      try { await api('PUT', `/api/projects/${projectId}/images/settings`, form.values()); lastError = ''; } catch (e) { lastError = e.message; }
      draw();
    }
    for (const input of [name, specs, extra]) { input.addEventListener('input', tell); input.addEventListener('change', store); }
    tell();
    fill(options,
      field(t('ai.purpose'), purpose, t('ai.purpose_hint')),
      h('h3', {}, t('ai.text_title')),
      field(t('ai.product_name'), name),
      field(t('ai.specs'), specs, t('ai.specs_hint', { max: limits.specs, len: limits.spec })),
      field(t('ai.extra_text'), extra, t('ai.extra_text_hint')),
      logoRow, status);
    options.hidden = false;
  }

  async function generate() {
    const chosen = form.values();
    // The warning before anything is sent: what is about to be made, that it costs money, and a way out.
    const warning = [t('ai.generate_confirm', { purpose: t(PURPOSE_LABEL[chosen.purpose]) }),
      t(form.complete() ? 'ai.confirm_text_on' : 'ai.confirm_text_off'), form.logoShown() ? t('ai.confirm_logo') : null,
      t('ai.confirm_cost')].filter(Boolean).join(' ');
    if (!(await confirmDialog(warning, t('ai.generate')))) return;
    lastError = '';
    try { await api('POST', `/api/projects/${projectId}/images/generate`, { description: getDescription(), text: chosen }); } catch (e) { lastError = e.message; }
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
  const purposeBadge = (item) => (item.purpose ? h('span', { class: 'badge' }, t(`${PURPOSE_LABEL[item.purpose]}_short`)) : null);

  function tile(image) {
    return h('figure', { class: 'ai-tile' },
      h('img', { src: imageUrl(image.id), alt: label(image.variant), loading: 'lazy', width: image.width_px, height: image.height_px }),
      h('figcaption', {}, h('strong', {}, label(image.variant)), purposeBadge(image), image.is_cover ? h('span', { class: 'badge' }, t('ai.cover')) : null),
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
    const purposeChosen = !!(form && form.values().purpose);
    fill(body,
      source ? h('img', { class: 'ai-source', src: imageUrl(source.id), alt: t('ai.photo_alt') }) : h('p', { class: 'muted' }, t('ai.photo_none')),
      field(source ? t('ai.photo_replace') : t('ai.photo_choose'), file, t('ai.photo_hint')),
      uploading ? h('div', { class: 'ai-progress', role: 'status' }, spinner(), h('strong', {}, t('ai.uploading'))) : null,
      working
        ? h('div', { class: 'ai-progress', role: 'status' }, spinner(),
          h('div', {}, h('strong', {}, t('ai.generating', { done: finished, n: finished + coming.length })), h('p', { class: 'hint' }, t('ai.generating_hint'))))
        : h('div', { class: 'stack' },
          h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', disabled: !source || uploading || !purposeChosen, onclick: generate }, t('ai.generate'))),
          form && !purposeChosen ? h('p', { class: 'hint' }, t('ai.purpose_needed')) : null),
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
  return h('div', { class: 'glass card stack' }, h('h2', {}, t('ai.card_title')), h('p', { class: 'muted' }, t('ai.card_intro')), options, body);
}

/** The "busy" mark on a calculation in the list. */
export const busyBadge = () => h('span', { class: 'badge ai-busy', role: 'status' }, spinner(true), t('ai.busy_badge'));
