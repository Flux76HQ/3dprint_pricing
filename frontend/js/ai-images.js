// AI product images (only built when the server says `ai_images`, i.e. AI_IMAGES_ENABLED=TRUE in .env):
// the OpenAI key and the log under Settings, and the "Productafbeeldingen" card in a calculation.
// The pictures are made by the server in the background: this page only asks for them and then polls how far they are, so leaving
// the page (or closing the browser) does not stop anything; the card picks the progress up again when it is shown.
import { api, downloadFile, upload } from './api.js';
import { formatDateTime, t } from './i18n.js';
import { loadMesh, modelViewer } from './model-viewer.js';
import { confirmDialog, field, fill, foldHead, h, saveBlob, switchRow, toast } from './ui.js';

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
 *  `businessOn()` says whether the business mode is on now (only then can the logo be put on a picture); `getModel()` gives the print
 *  file linked to the calculation now and the colour of its first roll ({ fileId, colour }), for the 3D view. */
export function productImagesCard(projectId, getDescription, businessOn = () => false, getModel = () => ({ fileId: null, colour: '' })) {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  // The purpose and the texts. Built once, when the first answer is in: the part below is redrawn while pictures are made, and a
  // field that is redrawn loses what is being typed in it.
  const options = h('div', { class: 'stack', hidden: true });
  let form = null;
  // The 3D model of the print file, to turn and take a picture of. It keeps its own box, for the same reason: redrawing it would
  // throw the loaded model away.
  const modelBox = h('div', { class: 'stack' });
  let viewer = null;                                               // the model on screen, once it is loaded
  let shownFile;                                                   // the file the box was last built for (undefined: not built yet)
  let images = [];
  let jobs = [];
  let warnings = [];
  let uploading = false;
  let wasBusy = false;
  let lastError = '';
  const busy = () => jobs.some((j) => j.status === 'queued' || j.status === 'running');

  async function load() {
    try {
      const got = await api('GET', `/api/projects/${projectId}/images`);
      images = got.images;
      jobs = got.jobs;
      warnings = got.warnings || [];
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

  // A file without a model to turn (a sliced 3MF holds only the print job) often has the slicer's own picture of the build plate,
  // in colour. It is offered instead: not to turn, but it can be kept as the view of the model all the same.
  function offerPlate(fileId, status) {
    const url = `/api/print-files/${fileId}/preview`;
    const picture = h('img', { class: 'ai-source model-plate', alt: t('ai.plate_alt') });
    picture.addEventListener('load', () => {
      if (shownFile !== fileId) return;
      const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        save.disabled = true;
        try {
          const { blob } = await downloadFile(url);
          const data = new FormData();
          data.append('file', blob, 'printplaat.jpg');
          data.append('origin', 'model');
          await upload(`/api/projects/${projectId}/images/source`, data);
          lastError = '';
          toast(t('ai.view3d_saved'));
        } catch (e) { lastError = e.message; }
        save.disabled = false;
        await refresh();
      } }, t('ai.plate_save'));
      modelBox.querySelector('.plate-offer')?.remove();           // asked again: one offer, not two
      status.after(h('div', { class: 'stack plate-offer' }, h('p', { class: 'muted' }, t('ai.plate_intro')), picture, h('div', { class: 'row' }, save)));
    });
    picture.src = url;                                             // no picture in the file: nothing is added
  }

  function drawModel() {
    const { fileId, colour } = getModel();
    if (fileId === shownFile) return;                              // another file was linked (or none): start again
    shownFile = fileId;
    viewer = null;
    const status = h('p', { class: 'hint', role: 'status' });
    if (!fileId) { fill(modelBox, h('h3', {}, t('ai.view3d_title')), h('p', { class: 'muted' }, t('ai.view3d_none'))); return; }
    const open = h('button', { class: 'btn', type: 'button', 'data-load-model': '', onclick: async () => {
      open.disabled = true;
      status.textContent = t('ai.view3d_loading');
      let made = null;
      let mesh = null;
      try {
        const chosen = form ? form.values().colour : '';
        mesh = await loadMesh(fileId);
        made = modelViewer(mesh, chosen || colour, !!chosen);      // the file's colours; a chosen colour is the whole item's, the roll's fills in
      } catch (e) { status.textContent = e.message; open.disabled = false; offerPlate(fileId, status); return; }
      if (shownFile !== fileId) return;                            // the file changed while this one was loading
      if (!made) { status.textContent = t('ai.view3d_no_webgl'); return; }
      viewer = made;
      status.textContent = t(mesh.colours ? 'ai.view3d_file_colours' : 'ai.view3d_no_colours');
      const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        save.disabled = true;
        try {
          const data = new FormData();
          data.append('file', await viewer.snapshot(), '3d-model.png');
          data.append('origin', 'model');
          await upload(`/api/projects/${projectId}/images/source`, data);
          lastError = '';
          toast(t('ai.view3d_saved'));
        } catch (e) { lastError = e.message; }
        save.disabled = false;
        await refresh();
      } }, t('ai.view3d_save'));
      fill(modelBox, h('h3', {}, t('ai.view3d_title')), h('p', { class: 'muted' }, t('ai.view3d_intro')),
        viewer.element, h('p', { class: 'hint' }, t('ai.view3d_hint')),
        h('div', { class: 'model-controls' }, field(t('ai.view3d_zoom'), viewer.controls[0]), viewer.controls[1]),
        h('div', { class: 'row' }, save), status);
    } }, t('ai.view3d_load'));
    fill(modelBox, h('h3', {}, t('ai.view3d_title')), h('p', { class: 'muted' }, t('ai.view3d_intro')), h('div', { class: 'row' }, open), status);
  }

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
    // The item's own colour: as it is in the photo, or one that is picked (then it also colours the 3D view).
    const tint = h('input', { type: 'color', value: saved.colour || getModel().colour || '#8c96a3', 'aria-label': t('ai.colour_pick') });
    const tintMode = h('select', {}, h('option', { value: '' }, t('ai.colour_as_is')), h('option', { value: 'own', selected: !!saved.colour }, t('ai.colour_own')));
    const chosenColour = () => (tintMode.value ? tint.value.toLowerCase() : '');
    const showColour = () => {
      tint.hidden = !tintMode.value;
      if (viewer) viewer.setColour(chosenColour() || getModel().colour, !!chosenColour());
    };
    tintMode.addEventListener('change', () => { showColour(); store(); });
    tint.addEventListener('input', showColour);
    tint.addEventListener('change', () => store());
    tint.hidden = !saved.colour;
    const scene = h('textarea', { rows: 2, maxlength: limits.scene, placeholder: t('ai.scene_ph') }, saved.scene || '');
    scene.addEventListener('change', () => store());
    let logo = saved.logo;
    const specLines = () => specs.value.split('\n').map((line) => line.trim()).filter(Boolean);
    // The logo is the business's: without the business mode the switch is shown off and cannot be turned (the saved choice is kept).
    const business = businessOn();
    const logoRow = switchRow(t('ai.logo'), t(!business ? 'ai.logo_hint_off' : got.logo_available ? 'ai.logo_hint_on' : 'ai.logo_hint_none'),
      business && logo, (on) => { logo = on; store(); });
    logoRow.querySelector('.switch').disabled = !business;
    form = {
      values: () => ({ purpose: purpose.value || null, colour: chosenColour(), scene: scene.value.trim(), product_name: name.value.trim(), specs: specLines(), extra_text: extra.value.trim(), logo }),
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
      h('div', { class: 'model-controls' }, field(t('ai.colour'), tintMode), tint),
      h('p', { class: 'hint' }, t('ai.colour_hint')),
      field(t('ai.scene'), scene, t('ai.scene_hint')),
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
    drawModel();
    const source = images.find((i) => i.kind === 'source' && i.origin !== 'model');
    const view = images.find((i) => i.kind === 'source' && i.origin === 'model');
    const made = images.filter((i) => i.kind === 'generated');
    const coming = jobs.filter((j) => j.status === 'queued' || j.status === 'running');
    const failed = jobs.filter((j) => j.status === 'failed');
    const finished = jobs.filter((j) => j.status === 'done').length;
    const working = coming.length > 0;
    // What the pictures are made from: the photo, the saved view of the 3D model, or both.
    const kept = (image, caption, alt) => h('figure', { class: 'ai-tile ai-kept' },
      h('img', { class: 'ai-source', src: imageUrl(image.id), alt }),
      h('figcaption', {}, h('strong', {}, caption)),
      h('div', { class: 'row' }, h('button', { class: 'btn small danger', type: 'button', disabled: working, onclick: async () => {
        if (await confirmDialog(t('ai.delete_confirm'), t('common.delete'))) act(() => api('DELETE', `/api/project-images/${image.id}`));
      } }, t('common.delete'))));
    const file = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', disabled: uploading || working, 'aria-label': t('ai.photo_choose'),
      onchange: () => { const chosen = file.files[0]; if (chosen) addPhoto(chosen); } });
    const purposeChosen = !!(form && form.values().purpose);
    fill(body,
      source || view ? h('div', { class: 'ai-sources' },
        source ? kept(source, t('ai.photo_caption'), t('ai.photo_alt')) : null,
        view ? kept(view, t('ai.view_caption'), t('ai.view_alt')) : null) : h('p', { class: 'muted' }, t('ai.photo_none')),
      field(source ? t('ai.photo_replace') : t('ai.photo_choose'), file, t('ai.photo_hint')),
      uploading ? h('div', { class: 'ai-progress', role: 'status' }, spinner(), h('strong', {}, t('ai.uploading'))) : null,
      working
        ? h('div', { class: 'ai-progress', role: 'status' }, spinner(),
          h('div', {}, h('strong', {}, t('ai.generating', { done: finished, n: finished + coming.length })), h('p', { class: 'hint' }, t('ai.generating_hint'))))
        : h('div', { class: 'stack' },
          h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', disabled: !(source || view) || uploading || !purposeChosen, onclick: generate }, t('ai.generate'))),
          form && !purposeChosen ? h('p', { class: 'hint' }, t('ai.purpose_needed')) : null),
      h('p', { class: 'error', role: 'alert', hidden: !lastError }, lastError),
      // Everything that went wrong or was left out, here on the page and as soon as it is known (also while the rest is still being made).
      warnings.length ? h('div', { class: 'notice warn stack', role: 'status' },
        h('strong', {}, t('ai.warnings_title')),
        h('ul', {}, warnings.map((w) => h('li', {}, w)))) : null,
      failed.length ? h('div', { class: 'stack ai-failed', role: 'alert' },
        h('strong', { class: 'error' }, t('ai.failed_title')),
        h('ul', {}, failed.map((j) => h('li', {}, h('strong', {}, label(j.variant)), ': ', j.message,
          j.detail ? h('code', { class: 'ai-log-detail' }, j.detail) : null)))) : null,
      failed.length || warnings.length ? h('div', { class: 'row' },
        h('a', { class: 'btn small', href: '#/instellingen/ai' }, t('ai.view_log')),
        working ? null : h('button', { class: 'btn small', type: 'button', onclick: () => act(() => api('DELETE', `/api/projects/${projectId}/images/jobs`)) }, t('ai.failed_dismiss'))) : null,
      made.length || coming.length ? h('div', { class: 'ai-grid' }, made.map(tile), coming.map(pending)) : null);
  }

  setTimeout(refresh, 0);
  // Folded away until it is wanted: the pictures are not what a calculation is opened for. The choice is remembered in this browser.
  const card = h('div', { class: 'glass card stack' }, foldHead('product-images', t('ai.card_title'), { open: false }), h('p', { class: 'muted' }, t('ai.card_intro')), options, modelBox, body);
  // The way in from the print file: the card is folded away by default, and the model is what the file is looked at for. Unfolds
  // the card, starts loading the model when that has not been done, and brings it into view.
  card.showModel = () => {
    const fold = card.querySelector('.fold-toggle');
    if (fold && fold.getAttribute('aria-expanded') !== 'true') fold.click();
    drawModel();
    const load = modelBox.querySelector('[data-load-model]');
    if (load && !load.disabled) load.click();
    modelBox.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };
  return card;
}

/** The "busy" mark on a calculation in the list. */
export const busyBadge = () => h('span', { class: 'badge ai-busy', role: 'status' }, spinner(true), t('ai.busy_badge'));
