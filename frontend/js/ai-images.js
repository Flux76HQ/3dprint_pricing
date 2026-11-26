// AI product images (only built when the server says `ai_images`, i.e. AI_IMAGES_ENABLED=TRUE in .env):
// the OpenAI key and the log under Settings, and the "Productafbeeldingen" card in a calculation.
// The pictures are made by the server in the background: this page only asks for them and then polls how far they are, so leaving
// the page (or closing the browser) does not stop anything; the card picks the progress up again when it is shown.
import { api, downloadFile, upload } from './api.js';
import { formatDateTime, getLocale, t } from './i18n.js';
import { openLightbox } from './lightbox.js';
import { loadMesh, modelViewer } from './model-viewer.js';
import { confirmDialog, enhanceDialog, eur, field, fill, fmt, foldHead, foldSection, h, icon, saveBlob, switchRow, toast } from './ui.js';

const VARIANT_LABEL = { square: 'ai.variant_square', landscape: 'ai.variant_landscape', portrait: 'ai.variant_portrait', studio: 'ai.variant_studio', detail: 'ai.variant_detail', context: 'ai.variant_context' };
// What each picture is, in a sentence, for the pop-up that asks which to make.
const VARIANT_DESC = { square: 'ai.variant_desc_square', landscape: 'ai.variant_desc_landscape', portrait: 'ai.variant_desc_portrait', studio: 'ai.variant_desc_studio',
  detail: 'ai.variant_desc_detail', context: 'ai.variant_desc_context' };
// The shapes the extra text can stand on (image_overlay.LABEL_STYLES).
const LABEL_STYLE = { tilted: 'ai.label_tilted', pill: 'ai.label_pill', ribbon: 'ai.label_ribbon', burst: 'ai.label_burst', block: 'ai.label_block' };
// What the pictures are for; the server makes four per purpose and has a template with its own colours for each.
const PURPOSE_LABEL = { marktplaats: 'ai.purpose_marktplaats', social: 'ai.purpose_social', webshop: 'ai.purpose_webshop' };
const QUALITIES = [['low', 'ai.quality_low'], ['medium', 'ai.quality_medium'], ['high', 'ai.quality_high']];
const POLL_MS = 3000;
const LOG_POLL_MS = 5000;
const USAGE_POLL_MS = 15000;
const imageUrl = (id) => `/api/project-images/${id}/file`;

/** The small version for a list (the stored picture is up to 2048 pixels a side). */
export const coverUrl = (id) => `/api/project-images/${id}/thumb`;
/** The picture itself, large (what a pop-up shows when a cover in a list is tapped). */
export const coverFileUrl = imageUrl;

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

// --- Examples of the pictures -------------------------------------------------------
// Drawn, not made: a frame in the shape of the picture with the item in it, and on the poster the texts as bars in the colours the poster
// will have. The colours are worked out as image_overlay._paint does (the server sends its templates, `poster` in GET .../images), so the
// example tells the truth about the choice; only the server draws the real poster.

const HEX = /^#[0-9a-f]{6}$/;
const channel = (v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const luminance = (hex) => [1, 3, 5].map((at) => channel(parseInt(hex.slice(at, at + 2), 16))).reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);
const contrast = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
const readableOn = (hex) => (contrast(hex, '#ffffff') >= contrast(hex, '#111114') ? '#ffffff' : '#111114');

/** The colours of a poster: `palette` is the server's, `purpose` the template, `light` whether the photo is light where the texts come,
 *  `look` the owner's choice ({ text_colour, accent_colour, label_style }; empty colours are the template's). */
function posterColours(palette, purpose, light, look = {}) {
  let tone = light ? 'light' : 'dark';
  const text = HEX.test(look.text_colour || '') ? look.text_colour : '';
  if (text) tone = contrast(text, palette.ink.dark.shade) >= contrast(text, palette.ink.light.shade) ? 'dark' : 'light';
  const template = (palette.accents[purpose] || Object.values(palette.accents)[0])[tone];
  const accent = HEX.test(look.accent_colour || '') ? look.accent_colour : '';
  return { ink: text || palette.ink[tone].ink, shade: palette.ink[tone].shade, accent: accent || template.accent,
    label: accent ? readableOn(accent) : template.label, style: palette.label_styles.includes(look.label_style) ? look.label_style : palette.label_styles[0] };
}

/** An example of one picture. `options`: { palette, purpose, poster (with the texts), logo, item (the item's colour), look }. */
function mockup(variant, options) {
  const { palette, purpose, poster, logo, item, look } = options;
  const layout = (palette.layouts || {})[variant] || 'bottom';
  const light = variant === 'studio';                                // the only picture with a light background
  const frame = h('div', { class: `ai-mock v-${variant} lay-${layout}${poster ? ' poster' : ''}`, 'aria-hidden': 'true' },
    variant === 'context' ? h('span', { class: 'ai-mock-table' }) : null,
    h('span', { class: 'ai-mock-object' }));
  frame.style.setProperty('--mock-item', HEX.test(item || '') ? item : '#8c96a3');
  if (poster) {
    const c = posterColours(palette, purpose, light, look);
    for (const [name, value] of Object.entries({ ink: c.ink, shade: c.shade, accent: c.accent, 'label-ink': c.label })) frame.style.setProperty(`--mock-${name}`, value);
    frame.append(h('span', { class: 'ai-mock-shade' }),
      h('span', { class: 'ai-mock-text' }, h('span', { class: 'm-bar' }), h('span', { class: 'm-head' }), h('span', { class: 'm-head short' }),
        h('span', { class: 'm-rule' }), h('span', { class: 'm-spec' }), h('span', { class: 'm-spec short' }),
        h('span', { class: `m-label l-${c.style}` }, h('span', {}))));
  }
  if (logo) frame.append(h('span', { class: 'ai-mock-logo' }));
  return frame;
}

/** The pop-up before pictures are made: which of the four of this purpose, each with an example and a box to tick. Resolves with the
 *  variants that are ticked, or null when it is closed. `room` is how many pictures the calculation can still take. */
function pickVariants({ palette, purpose, variants, text, logo, item, look, room }) {
  return new Promise((resolve) => {
    let answer = null;
    const count = h('p', { class: 'hint', role: 'status' });
    const go = h('button', { class: 'btn primary', type: 'button', onclick: () => { answer = boxes.filter((b) => b.checked).map((b) => b.value); dialog.close(); } });
    const update = () => {
      const n = boxes.filter((b) => b.checked).length;
      go.disabled = !n || n > room;
      go.textContent = t('ai.pick_go', { n });
      count.textContent = n > room ? t('ai.pick_room', { n: room }) : !n ? t('ai.pick_none') : t('ai.pick_count', { n, total: variants.length });
      count.className = n > room ? 'error' : 'hint';
    };
    const boxes = variants.map((variant) => h('input', { type: 'checkbox', value: variant, checked: true, onchange: update }));
    const tiles = variants.map((variant, i) => {
      const poster = i === 0 && text;                                // only the first of the four gets the texts
      return h('label', { class: 'ai-pick' },
        h('span', { class: 'ai-pick-frame' }, mockup(variant, { palette, purpose, poster, logo, item, look })),
        h('span', { class: 'ai-pick-head' }, boxes[i], h('strong', {}, t(VARIANT_LABEL[variant]))),
        poster ? h('span', { class: 'badge' }, t('ai.pick_poster')) : null,
        h('span', { class: 'muted' }, t(VARIANT_DESC[variant])));
    });
    const notes = [t(text ? 'ai.confirm_text_on' : 'ai.confirm_text_off'), logo ? t('ai.confirm_logo') : null, t('ai.confirm_cost')].filter(Boolean);
    const dialog = enhanceDialog(h('dialog', { class: 'glass sheet ai-pick-sheet' }, h('div', { class: 'stack' },
      h('h2', {}, t('ai.pick_title')),
      h('p', { class: 'muted' }, t('ai.pick_intro', { purpose: t(PURPOSE_LABEL[purpose]) })),
      h('div', { class: 'ai-pick-grid' }, tiles),
      h('ul', { class: 'ai-pick-notes' }, notes.map((note) => h('li', { class: 'hint' }, note))),
      count,
      h('div', { class: 'row end' }, h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, t('common.cancel')), go))));
    dialog.addEventListener('close', () => { dialog.remove(); resolve(answer); });
    update();
    document.body.append(dialog);
    dialog.showModal();
  });
}

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

// --- What the pictures cost -------------------------------------------------------

const DOLLAR_FORMATS = new Map();
const dollars = (value) => {
  const key = getLocale();
  if (!DOLLAR_FORMATS.has(key)) DOLLAR_FORMATS.set(key, new Intl.NumberFormat(key, { style: 'currency', currency: 'USD' }));
  return DOLLAR_FORMATS.get(key).format(Number(value) || 0);
};

/** What the pictures cost, set by set, with the totals of this month and of everything, and the prices and the rate they are worked out with. The server does all the
 *  counting (tokens times a price per million, in euros with the rate, a set rounded to cents before sets are added); this only shows it. The list refreshes itself while the
 *  page is open, so a set that is still being made counts as it goes; the form of the prices is built once, so what is being typed in it stays. */
export function aiUsageCard() {
  const chips = h('ul', { class: 'stat-chips' });
  const notice = h('p', { class: 'notice', role: 'status', hidden: true });
  const list = h('ul', { class: 'plain-list ai-usage' }, h('li', { class: 'muted' }, t('common.loading')));
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const form = h('div', { class: 'stack' });
  let drawn = false;                                              // the form is built once, and again after it is saved

  /** [what to show first, what to show beside it] for something that has `cost_eur` and `cost_usd`: euros when there are any, else dollars, else a dash. */
  const money = (cost) => (cost.cost_eur != null ? [eur(cost.cost_eur), cost.cost_usd != null ? dollars(cost.cost_usd) : null]
    : cost.cost_usd != null ? [dollars(cost.cost_usd), null] : ['—', null]);

  const setRow = (s) => {
    const [main, side] = money(s);
    const tokens = s.reported ? `${t('ai.usage_tokens', { n: fmt(s.tokens.total, 0) })} (${t('ai.usage_split', { input: fmt(s.tokens.input_text + s.tokens.input_image, 0), output: fmt(s.tokens.output, 0) })})`
      : t('ai.usage_unreported');
    const calc = s.project_number == null && !s.project_name ? null : `#${s.project_number ?? ''} ${s.project_name ?? ''}`.trim();
    return h('li', { class: 'list-row' },
      h('div', {}, h('strong', {}, s.purpose && PURPOSE_LABEL[s.purpose] ? t(`${PURPOSE_LABEL[s.purpose]}_short`) : t('ai.usage_set')),
        h('p', { class: 'muted' }, [formatDateTime(s.at, { dateStyle: 'short', timeStyle: 'short' }), t('ai.usage_pictures', { n: s.pictures }), tokens].join(' · ')),
        calc ? h('p', { class: 'muted' }, s.project_id ? h('a', { href: `#/berekeningen/${s.project_id}` }, calc) : [calc, ` (${t('ai.usage_deleted')})`]) : null),
      h('div', { class: 'ai-usage-cost', title: main === '—' && s.reported ? t('ai.usage_unpriced') : null }, h('strong', {}, main), side ? h('span', { class: 'muted' }, side) : null));
  };

  const chip = (label, totals, eurs) => {
    const [main] = money(totals);
    const without = eurs ? totals.without_eur : totals.without_usd;
    return h('li', {}, h('strong', {}, label), h('span', {}, [t('ai.usage_sets', { n: totals.sets }), t('ai.usage_tokens', { n: fmt(totals.tokens, 0) }), main].join(' · ')),
      without && totals.sets ? h('span', { class: 'muted' }, t('ai.usage_without', { n: without })) : null);
  };

  function drawForm(info) {
    const input = (value, placeholder) => h('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', spellcheck: 'false', value: value ?? '', placeholder: placeholder ?? '' });
    const fields = { text_in: input(info.prices.text_in, info.price_defaults.text_in), image_in: input(info.prices.image_in, info.price_defaults.image_in),
      image_out: input(info.prices.image_out, info.price_defaults.image_out) };
    const rate = input(info.usd_eur, '0,92');
    const hint = (key) => (info.price_defaults[key] ? t('ai.price_default', { price: `$ ${info.price_defaults[key]}` }) : t('ai.price_nodefault'));
    const save = async () => {
      try {
        await api('PUT', '/api/ai-images/settings', { prices: { text_in: fields.text_in.value, image_in: fields.image_in.value, image_out: fields.image_out.value }, usd_eur: rate.value });
        toast(t('ai.prices_saved'));
        drawn = false;
      } catch (e) { toast(e.message, 'error'); }
      load();
    };
    fill(form, h('p', { class: 'muted' }, t('ai.prices_intro', { model: info.model })),
      h('div', { class: 'two' }, field(t('ai.price_text_in'), fields.text_in, hint('text_in')), field(t('ai.price_image_in'), fields.image_in, hint('image_in'))),
      h('div', { class: 'two' }, field(t('ai.price_image_out'), fields.image_out, hint('image_out')), field(t('ai.rate'), rate, t('ai.rate_hint'))),
      Object.keys(info.price_defaults).length ? h('p', { class: 'hint' }, t('ai.prices_source', { model: info.model })) : null,
      h('p', { class: 'hint' }, t('ai.prices_note')),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: save }, t('common.save'))));
    drawn = true;
  }

  async function load() {
    try {
      const [report, info] = await Promise.all([api('GET', '/api/ai-images/usage'), drawn ? null : api('GET', '/api/ai-images/settings')]);
      const eurs = report.totals.all.cost_eur != null;
      fill(chips, chip(t('ai.usage_month'), report.totals.month, eurs), chip(t('ai.usage_all'), report.totals.all, eurs));
      notice.textContent = t('ai.usage_no_rate');
      notice.hidden = !(report.rate == null && report.totals.all.cost_usd != null);
      fill(list, report.sets.length ? report.sets.map(setRow) : h('li', { class: 'muted' }, t('ai.usage_none')));
      if (info) drawForm(info);
      error.hidden = true;
    } catch (e) { error.textContent = e.message; error.hidden = false; }
  }

  const card = h('div', { class: 'glass card stack' }, h('h2', {}, t('ai.usage_title')), h('p', { class: 'muted' }, t('ai.usage_intro')),
    chips, notice, error, list, h('details', {}, h('summary', {}, t('ai.prices_title')), form));
  setTimeout(keepFresh(card, load, USAGE_POLL_MS), 0);
  return card;
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

// --- Standard texts and the colours of the print --------------------------------------------------

/** A text as the server keeps it as a standard text (`ai_images.preset_text`): whitespace tidied, and for the specs one per line without a typed bullet.
 *  Compared with this, a field "holds" a standard text when it says the same, whatever the spacing. */
const tidy = (field, value) => {
  const one = (text) => text.split(/\s+/).filter(Boolean).join(' ');
  return field === 'specs'
    ? String(value || '').split('\n').map((line) => one(line).replace(/^[-*•·]+/, '').trim()).filter(Boolean).join('\n')
    : one(String(value || ''));
};

const presetButton = (name, text, onclick) => h('button', { class: 'btn small icon-only', type: 'button', 'aria-label': text, title: text, onclick }, icon(name));

/** The row under a text field with standard texts: a list to pick one from, a button to keep what stands in the field as one, and a button to remove
 *  the one that is picked. The list follows the field: it shows the standard text the field holds now, when it holds one. `list` is the field's
 *  standard texts ([{ id, text }], shared with nothing else: a text kept or removed here is changed in it). */
function presetBar(field, input, list, label) {
  const pick = h('select', { 'aria-label': t('ai.preset_for', { field: label }) });
  const now = () => tidy(field, input.value);
  const short = (text) => { const one = text.split('\n').join(' · '); return one.length > 70 ? `${one.slice(0, 69)}…` : one; };
  const keep = presetButton('bookmark-plus-outline', t('ai.preset_keep'), async () => {
    keep.disabled = true;
    try {
      const made = await api('POST', '/api/image-text-presets', { field, text: input.value });
      if (!list.some((p) => p.id === made.id)) list.push({ id: made.id, text: made.text });
      toast(t('ai.preset_kept'));
    } catch (e) { toast(e.message, 'error'); }
    sync();
  });
  const drop = presetButton('trash', t('ai.preset_remove'), async () => {
    const found = list.find((p) => p.text === now());
    if (!found || !(await confirmDialog(t('ai.preset_remove_confirm'), t('common.delete')))) return;
    try {
      await api('DELETE', `/api/image-text-presets/${found.id}`);
      list.splice(list.indexOf(found), 1);
      toast(t('ai.preset_removed'));
    } catch (e) { toast(e.message, 'error'); }
    sync();
  });
  function sync() {
    const found = list.find((p) => p.text === now());
    fill(pick, h('option', { value: '' }, t(list.length ? 'ai.preset_pick' : 'ai.preset_none')),
      list.map((p) => h('option', { value: String(p.id), title: p.text }, short(p.text))));
    pick.value = found ? String(found.id) : '';
    pick.disabled = !list.length;
    keep.disabled = !now() || !!found;                             // nothing to keep, or it is kept already
    drop.disabled = !found;
  }
  pick.addEventListener('change', () => {
    const chosen = list.find((p) => String(p.id) === pick.value);
    if (!chosen) { sync(); return; }
    input.value = chosen.text;                                     // the field is changed as if it was typed in: whatever listens to it keeps the text
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    sync();
  });
  input.addEventListener('input', sync);
  sync();
  return h('div', { class: 'ai-presets' }, pick, keep, drop);
}

/** The colours of the print as round buttons under a colour field: one click puts that colour in the field (`choose`). `colours()` says which there are
 *  now ([{ hex, name }]); `show()` reads them again, and builds the row anew only when they changed, so a click is never lost to a redraw. */
function printColours(input, colours, choose) {
  const row = h('div', { class: 'ai-swatches', role: 'group', 'aria-label': t('ai.print_colours') });
  let shown = null;
  const mark = () => { for (const b of row.querySelectorAll('.ai-swatch')) b.setAttribute('aria-pressed', String(b.dataset.hex === input.value.toLowerCase())); };
  row.show = () => {
    const list = colours();
    const key = list.map((c) => c.hex).join(',');
    if (key !== shown) {
      shown = key;
      fill(row, h('span', { class: 'hint' }, t('ai.print_colours')), list.map((c) => {
        const button = h('button', { class: 'ai-swatch', type: 'button', 'data-hex': c.hex, title: [c.name, c.hex].filter(Boolean).join(' · '),
          'aria-label': t('ai.print_colour_pick', { name: c.name || c.hex }), onclick: () => { choose(c.hex); mark(); } });
        button.style.setProperty('--swatch', c.hex);
        return button;
      }));
    }
    row.classList.toggle('empty', !list.length);
    mark();
  };
  input.addEventListener('input', mark);
  row.show();
  return row;
}

/** Puts a colour in a colour field as if it was picked there, so whatever listens to the field (the example, the 3D view, the saving) follows. */
function setColour(input, hex) {
  input.value = hex;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

// --- In a calculation -------------------------------------------------------------

/** The card with the photo of the object and the pictures made from it. `getDescription()` is what the form says now (saved or not);
 *  `businessOn()` says whether the business mode is on now (only then can the logo be put on a picture); `getModel()` gives the 3D
 *  models of the calculation now, the colour of its first filament line and every colour the print has ({ models: [{ fileId, label }], colour,
 *  colours: [{ hex, name }] }), for the 3D view and for the colour buttons. */
export function productImagesCard(projectId, getDescription, businessOn = () => false, getModel = () => ({ models: [], colour: '', colours: [] })) {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('common.loading')));
  // The purpose and the texts. Built once, when the first answer is in: the part below is redrawn while pictures are made, and a
  // field that is redrawn loses what is being typed in it.
  const options = h('div', { class: 'stack', hidden: true });
  let form = null;
  // The 3D model of the print file, to turn and take a picture of. It keeps its own box, for the same reason: redrawing it would
  // throw the loaded model away.
  const modelBox = h('div', { class: 'stack' });
  let viewer = null;                                               // the model on screen, once it is loaded
  let shownKey;                                                    // the models the box was last built for (undefined: not built yet)
  let wantedModel = '';                                            // the model to show first, when one was asked for
  let modelNames = new Map();                                      // file id -> the name of that model, for the saved views
  let images = [];
  let jobs = [];
  let warnings = [];
  let sent = [];                                                   // the pictures that go to the image model now (ids)
  let maxSent = 6;
  let palette = null;                                              // the poster templates, for the examples (see `mockup`)
  let purposes = {};                                               // purpose -> its four pictures
  let presets = { scene: [], product_name: [], specs: [], extra_text: [] };   // the standard texts of the fields (the business's, shared by every calculation)
  let maxGenerated = 12;
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
      sent = got.sent || [];
      maxSent = (got.limits || {}).selected || 6;
      maxGenerated = (got.limits || {}).generated || 12;
      palette = got.poster;
      purposes = got.purposes;
      lastError = '';
      if (!form) {
        try { presets = { ...presets, ...(await api('GET', '/api/image-text-presets')) }; } catch { /* without the list the fields work as before */ }
        buildForm(got);
      }
    } catch (e) { lastError = e.message; }
    if (wasBusy && !busy()) {                                      // it finished while this page was watching
      if (jobs.some((j) => j.status === 'failed')) toast(t('ai.done_errors'), 'error'); else toast(t('ai.done'));
    }
    wasBusy = busy();
    draw();
  }
  const refresh = keepFresh(body, load, POLL_MS, busy);

  // Keeps a picture as the view of a model. `ref` says which model (and which build plate) it is of.
  async function keepView(blob, name, ref, button) {
    button.disabled = true;
    try {
      const data = new FormData();
      data.append('file', blob, name);
      data.append('origin', 'model');
      data.append('model', ref);
      await upload(`/api/projects/${projectId}/images/source`, data);
      lastError = '';
      toast(t('ai.view3d_saved'));
    } catch (e) { lastError = e.message; }
    button.disabled = false;
    await refresh();
  }

  function drawModel() {
    const { models, colour } = getModel();
    const key = models.map((m) => `${m.fileId}|${m.label}`).join(',');
    if (key === shownKey) return;                                  // other models were linked (or none): start again
    shownKey = key;
    viewer = null;
    modelNames = new Map(models.map((m) => [m.fileId, m.label]));
    if (!models.length) { fill(modelBox, h('h3', {}, t('ai.view3d_title')), h('p', { class: 'muted' }, t('ai.view3d_none'))); return; }
    let current = models.find((m) => m.fileId === wantedModel) || models[0];
    let plate = '';                                                // '' is the whole file; a number is one build plate of it
    let token = 0;                                                 // what is being loaded now; an answer for something older is dropped
    const status = h('p', { class: 'hint', role: 'status' });
    const stage = h('div', { class: 'stack' });
    const ref = () => `${current.fileId}${plate ? `:${plate}` : ''}`;
    const plateField = h('div', { hidden: true });
    const plates = h('select', { onchange: () => { plate = plates.value; load(); } });
    plateField.append(field(t('file.plate'), plates));
    const picker = h('select', { onchange: () => { current = models.find((m) => m.fileId === picker.value) || models[0]; plate = ''; choosePlates(); load(); } },
      models.map((m) => h('option', { value: m.fileId, selected: m === current }, m.label)));

    // A slicer project can have several build plates; each can be looked at on its own.
    async function choosePlates() {
      plateField.hidden = true;
      const asked = current.fileId;
      let found = { plates: [] };
      try { found = await api('GET', `/api/print-files/${asked}/parts`); } catch { /* no list: the whole file */ }
      if (shownKey !== key || current.fileId !== asked || found.plates.length < 2) return;
      fill(plates, h('option', { value: '' }, t('file.all_plates')), found.plates.map((n) => h('option', { value: String(n) }, `${t('file.plate')} ${n}`)));
      plateField.hidden = false;
    }

    // A file without a model to turn (a sliced 3MF holds only the print job) often has the slicer's own picture of the build
    // plate, in colour. It is offered instead: not to turn, but it can be kept as the view of the model all the same.
    function offerPlate(mine) {
      const url = `/api/print-files/${current.fileId}/preview${plate ? `?plate=${plate}` : ''}`;
      const name = ref();
      const picture = h('img', { class: 'ai-source model-plate', alt: t('ai.plate_alt') });
      picture.addEventListener('load', () => {
        if (shownKey !== key || mine !== token) return;
        const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
          try { keepView((await downloadFile(url)).blob, 'printplaat.jpg', name, save); } catch (e) { lastError = e.message; draw(); }
        } }, t('ai.plate_save'));
        fill(stage, h('p', { class: 'muted' }, t('ai.plate_intro')), picture, h('div', { class: 'row' }, save));
      });
      picture.src = url;                                           // no picture in the file: nothing is added
    }

    async function load() {
      const mine = ++token;
      viewer = null;
      fill(stage);
      open.hidden = true;
      status.textContent = t('ai.view3d_loading');
      let made = null;
      let mesh = null;
      try {
        const chosen = form ? form.values().colour : '';
        mesh = await loadMesh(current.fileId, plate);
        if (shownKey !== key || mine !== token) return;            // something else was asked for while this was loading
        made = modelViewer(mesh, chosen || colour, !!chosen);      // the file's colours; a chosen colour is the whole item's, the roll's fills in
      } catch (e) {
        if (shownKey !== key || mine !== token) return;
        status.textContent = e.message;
        open.hidden = false;
        offerPlate(mine);
        return;
      }
      if (!made) { status.textContent = t('ai.view3d_no_webgl'); return; }
      viewer = made;
      status.textContent = t(mesh.colours ? 'ai.view3d_file_colours' : 'ai.view3d_no_colours');
      const name = ref();
      const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        try { keepView(await made.snapshot(), '3d-model.png', name, save); } catch (e) { lastError = e.message; draw(); }
      } }, t('ai.view3d_save'));
      fill(stage, made.element, h('p', { class: 'hint' }, t('ai.view3d_hint')),
        h('div', { class: 'model-controls' }, field(t('ai.view3d_drag'), made.controls.mode), field(t('ai.view3d_side'), made.controls.side),
          field(t('ai.view3d_tilt'), made.controls.tilt), field(t('ai.view3d_zoom'), made.controls.zoom), made.controls.reset),
        h('div', { class: 'row' }, save));
    }

    const open = h('button', { class: 'btn', type: 'button', 'data-load-model': '', onclick: load }, t('ai.view3d_load'));
    fill(modelBox, h('h3', {}, t('ai.view3d_title')), h('p', { class: 'muted' }, t('ai.view3d_intro')),
      h('div', { class: 'model-controls' }, models.length > 1 ? field(t('ai.view3d_which'), picker) : null, plateField, open), status, stage);
    choosePlates();
  }

  // Every photo is kept next to the others; several can be chosen at once.
  async function addPhotos(files) {
    uploading = true;
    lastError = '';
    draw();
    for (const file of files) {
      const form = new FormData();
      form.append('file', file);
      try { await upload(`/api/projects/${projectId}/images/source`, form); } catch (e) { lastError = `${file.name}: ${e.message}`; break; }
    }
    uploading = false;
    await refresh();
  }

  function buildForm(got) {
    const saved = got.text;
    const limits = got.limits;
    const purpose = h('select', { onchange: () => { showLook(); store(); draw(); } },
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
      tintSwatches.hidden = !tintMode.value;
      if (viewer) viewer.setColour(chosenColour() || getModel().colour, !!chosenColour());
      if (form) showLook();
    };
    tintMode.addEventListener('change', () => { showColour(); store(); });
    tint.addEventListener('input', showColour);
    tint.addEventListener('change', () => store());
    tint.hidden = !saved.colour;
    // The colours the print has, to pick from instead of the colour picker: for the item, and below for the texts and the bars. They are read again when
    // the calculation changed (the calculation's filament lines are edited outside this card), as the pointer comes near or a field gets the focus.
    const printColoursNow = () => getModel().colours || [];
    const swatches = [];
    const showSwatches = () => { for (const row of swatches) row.show(); };
    const swatchesFor = (input) => {
      const row = printColours(input, printColoursNow, (hex) => setColour(input, hex));
      swatches.push(row);
      return row;
    };
    const tintSwatches = swatchesFor(tint);
    tintSwatches.hidden = !saved.colour;                           // with the picker, which is hidden while the item keeps the colour it has in the photo
    // The colours of the poster's texts and of its bars (and label), and the shape of the label: the template's, which follow the photo,
    // or the owner's own, to go with the item. The example beside them shows the whole as it will be.
    const firstOf = (p) => (purposes[p] || [])[0] || 'square';
    const templateAccent = () => posterColours(palette, purpose.value || Object.keys(purposes)[0], firstOf(purpose.value) === 'studio').accent;
    const lookMode = h('select', {}, h('option', { value: '' }, t('ai.look_auto')),
      h('option', { value: 'own', selected: !!(saved.text_colour || saved.accent_colour) }, t('ai.look_own')));
    const inkPick = h('input', { type: 'color', value: saved.text_colour || '#ffffff' });
    const accentPick = h('input', { type: 'color', value: saved.accent_colour || saved.colour || templateAccent() });
    const labelStyle = h('select', {}, palette.label_styles.filter((style) => LABEL_STYLE[style]).map((style) => h('option', { value: style,
      selected: (saved.label_style || palette.label_styles[0]) === style }, t(LABEL_STYLE[style]))));
    const matchItem = h('button', { class: 'btn tool', type: 'button', onclick: () => { accentPick.value = chosenColour() || getModel().colour || accentPick.value; showLook(); store(); } },
      t('ai.look_match'));
    const inkField = field(t('ai.look_text'), inkPick);
    const accentField = field(t('ai.look_accent'), accentPick);
    inkPick.after(swatchesFor(inkPick));                           // each is shown with its field, which is hidden while the colours are automatic
    accentPick.after(swatchesFor(accentPick));
    const own = [inkField, accentField, matchItem];
    const preview = h('div', { class: 'ai-look-frame' });
    const look = () => ({ text_colour: lookMode.value ? inkPick.value.toLowerCase() : '', accent_colour: lookMode.value ? accentPick.value.toLowerCase() : '',
      label_style: labelStyle.value });
    function showLook() {
      for (const part of own) part.hidden = !lookMode.value;
      const variant = firstOf(purpose.value);
      fill(preview, mockup(variant, { palette, purpose: purpose.value || Object.keys(purposes)[0], poster: true, logo: form && form.logoShown(),
        item: chosenColour() || getModel().colour, look: look() }));
      showSwatches();
    }
    lookMode.addEventListener('change', () => {
      if (lookMode.value && !saved.accent_colour && !saved.text_colour) accentPick.value = chosenColour() || templateAccent();
      showLook(); store();
    });
    for (const pick of [inkPick, accentPick]) { pick.addEventListener('input', showLook); pick.addEventListener('change', () => store()); }
    labelStyle.addEventListener('change', () => { showLook(); store(); });
    const scene = h('textarea', { rows: 2, maxlength: limits.scene, placeholder: t('ai.scene_ph') }, saved.scene || '');
    scene.addEventListener('change', () => store());
    // A text field with its standard texts under it (`presetBar`).
    const withPresets = (key, label, input, hint) => {
      const row = field(label, input, hint);
      input.after(presetBar(key, input, presets[key], label));
      return row;
    };
    let logo = saved.logo;
    const specLines = () => specs.value.split('\n').map((line) => line.trim()).filter(Boolean);
    // The logo is the business's: without the business mode the switch is shown off and cannot be turned (the saved choice is kept).
    const business = businessOn();
    const logoRow = switchRow(t('ai.logo'), t(!business ? 'ai.logo_hint_off' : got.logo_available ? 'ai.logo_hint_on' : 'ai.logo_hint_none'),
      business && logo, (on) => { logo = on; showLook(); store(); });
    logoRow.querySelector('.switch').disabled = !business;
    form = {
      values: () => ({ purpose: purpose.value || null, colour: chosenColour(), ...look(), scene: scene.value.trim(), product_name: name.value.trim(), specs: specLines(),
        extra_text: extra.value.trim(), logo }),
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
    showLook();
    fill(options,
      field(t('ai.purpose'), purpose, t('ai.purpose_hint')),
      h('div', { class: 'ai-colours', onpointerenter: showSwatches, onfocusin: showSwatches },
        h('div', { class: 'stack' },
          h('div', { class: 'model-controls' }, field(t('ai.colour'), tintMode), tint),
          tintSwatches,
          h('p', { class: 'hint' }, t('ai.colour_hint')),
          h('div', { class: 'model-controls' }, field(t('ai.look'), lookMode), own),
          field(t('ai.label_style'), labelStyle, t('ai.label_style_hint')),
          h('p', { class: 'hint' }, t('ai.look_hint'))),
        h('figure', { class: 'ai-look-preview' }, preview, h('figcaption', { class: 'hint' }, t('ai.look_preview')))),
      withPresets('scene', t('ai.scene'), scene, t('ai.scene_hint')),
      h('h3', {}, t('ai.text_title')),
      withPresets('product_name', t('ai.product_name'), name),
      withPresets('specs', t('ai.specs'), specs, t('ai.specs_hint', { max: limits.specs, len: limits.spec })),
      withPresets('extra_text', t('ai.extra_text'), extra, t('ai.extra_text_hint')),
      logoRow, status);
    options.hidden = false;
  }

  async function generate() {
    const chosen = form.values();
    // Before anything is sent: which of the four are wanted (each with an example), what goes on them, that it costs money, and a way out.
    const variants = await pickVariants({ palette, purpose: chosen.purpose, variants: purposes[chosen.purpose] || [], text: form.complete(), logo: form.logoShown(),
      item: chosen.colour || getModel().colour, look: chosen, room: Math.max(0, maxGenerated - images.filter((i) => i.kind === 'generated').length) });
    if (!variants || !variants.length) return;
    lastError = '';
    try { await api('POST', `/api/projects/${projectId}/images/generate`, { description: getDescription(), text: chosen, variants }); } catch (e) { lastError = e.message; }
    await refresh();                                               // shows what was queued and keeps asking while it runs
  }

  async function act(work) {
    try { await work(); lastError = ''; } catch (e) { lastError = e.message; }
    await refresh();
  }

  // Hands a picture to the browser as a file. It says nothing when it fails: the tile tells it with a toast, the pop-up in its own footer
  // (a toast would be behind a pop-up).
  async function saveImage(image) {
    const { blob, name } = await downloadFile(`${imageUrl(image.id)}?download=1`);
    saveBlob(blob, name);
  }
  async function download(image) {
    try { await saveImage(image); } catch (e) { toast(e.message, 'error'); }
  }

  const label = (variant) => t(VARIANT_LABEL[variant]);
  const purposeBadge = (item) => (item.purpose ? h('span', { class: 'badge' }, t(`${PURPOSE_LABEL[item.purpose]}_short`)) : null);

  // What can be done with a picture, as icons: download it, make it the cover of the calculation (the star is filled on the one
  // that is), remove it. Every picture has all three, the uploaded photo and the saved views of the model too.
  const tool = (name, text, onclick, more = {}) => h('button', { class: `btn small icon-only${more.danger ? ' danger' : ''}`, type: 'button',
    'aria-label': text, title: text, disabled: !!more.disabled, 'aria-pressed': more.pressed === undefined ? null : String(more.pressed), onclick }, icon(name));
  const tools = (image, locked = false) => h('div', { class: 'row ai-tools' },
    tool('download', t('ai.download'), () => download(image)),
    tool(image.is_cover ? 'star' : 'star-outline', t(image.is_cover ? 'ai.cover' : 'ai.make_cover'),
      () => { if (!image.is_cover) act(() => api('PUT', `/api/project-images/${image.id}/cover`)); }, { pressed: image.is_cover }),
    tool('trash', t('common.delete'), async () => {
      if (await confirmDialog(t('ai.delete_confirm'), t('common.delete'))) act(() => api('DELETE', `/api/project-images/${image.id}`));
    }, { danger: true, disabled: locked }));
  const coverBadge = (image) => (image.is_cover ? h('span', { class: 'badge' }, t('ai.cover')) : null);

  // A made picture opens large in a pop-up, with the other made pictures one chevron (or swipe) away, and can be saved from there.
  function look(made, image) {
    const items = made.map((m) => ({ src: imageUrl(m.id), alt: label(m.variant), title: label(m.variant), image: m,
      badges: [m.purpose && PURPOSE_LABEL[m.purpose] ? t(`${PURPOSE_LABEL[m.purpose]}_short`) : null, m.is_cover ? t('ai.cover') : null].filter(Boolean) }));
    openLightbox(items, made.indexOf(image), { save: (item) => saveImage(item.image) });
  }

  function tile(image, made) {
    return h('figure', { class: 'ai-tile' },
      h('button', { class: 'ai-zoom', type: 'button', title: t('ai.open'), 'aria-label': `${t('ai.open')}: ${label(image.variant)}`, onclick: () => look(made, image) },
        h('img', { src: imageUrl(image.id), alt: '', loading: 'lazy', width: image.width_px, height: image.height_px })),
      h('figcaption', {}, h('strong', {}, label(image.variant)), purposeBadge(image), coverBadge(image)),
      tools(image));
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
    const photos = images.filter((i) => i.kind === 'source' && i.origin !== 'model');
    const views = images.filter((i) => i.kind === 'source' && i.origin === 'model');
    // "Beeld van het 3D-model · voorkant · plaat 2": which model a saved view is of, when the calculation knows
    const viewName = (image) => {
      const [file, plate] = String(image.model_ref || '').split(':');
      return [t('ai.view_caption'), modelNames.get(file), plate ? `${t('file.plate').toLowerCase()} ${plate}` : ''].filter(Boolean).join(' · ');
    };
    const made = images.filter((i) => i.kind === 'generated');
    const coming = jobs.filter((j) => j.status === 'queued' || j.status === 'running');
    const failed = jobs.filter((j) => j.status === 'failed');
    const finished = jobs.filter((j) => j.status === 'done').length;
    const working = coming.length > 0;
    // What the pictures are made from: the photo, the saved view of the 3D model, or both.
    // A photo or view with the choice under it: does it go to the image model? What is ticked is what is sent (`sent`: with
    // nothing chosen that is the first picture, so there is always one).
    const kept = (image, caption, alt) => {
      const goes = sent.includes(image.id);
      const pick = h('input', { type: 'checkbox', checked: goes, disabled: working || (!goes && sent.length >= maxSent) || (goes && sent.length === 1),
        onchange: () => act(() => api('PUT', `/api/project-images/${image.id}/selected`, { selected: pick.checked })) });
      return h('figure', { class: `ai-tile ai-kept${goes ? ' sent' : ''}` },
        h('img', { class: 'ai-source', src: imageUrl(image.id), alt }),
        h('figcaption', {}, h('strong', {}, caption), coverBadge(image)),
        h('label', { class: 'check ai-send' }, pick, t('ai.send')),
        tools(image, working));                                      // not removed while pictures are being made from it
    };
    const file = h('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', multiple: true, disabled: uploading || working, 'aria-label': t('ai.photo_choose'),
      onchange: () => { if (file.files.length) addPhotos([...file.files]); } });
    const purposeChosen = !!(form && form.values().purpose);
    const sourceCount = photos.length + views.length;
    // Two parts that fold away on their own, so what was uploaded or saved from the 3D model (what the pictures are made *from*) is not mixed up
    // with the pictures that were made for Marktplaats, social media or a webshop. Each remembers in this browser whether it is open.
    const sources = foldSection('product-images-sources', t('ai.sources_title'), [
      h('p', { class: 'muted' }, t('ai.sources_intro')),
      sourceCount ? h('div', { class: 'stack' },
        h('p', { class: 'hint', role: 'status' }, t('ai.send_count', { n: sent.length, max: maxSent })),
        h('div', { class: 'ai-sources' },
          photos.map((photo, i) => kept(photo, photos.length > 1 ? `${t('ai.photo_caption')} ${i + 1}` : t('ai.photo_caption'), t('ai.photo_alt'))),
          views.map((view) => kept(view, viewName(view), t('ai.view_alt'))))) : h('p', { class: 'muted' }, t('ai.photo_none')),
      field(photos.length ? t('ai.photo_replace') : t('ai.photo_choose'), file, t('ai.photo_hint')),
      uploading ? h('div', { class: 'ai-progress', role: 'status' }, spinner(), h('strong', {}, t('ai.uploading'))) : null,
      // What is done with the photos and the views is made from them: the button is here, with them. While pictures are being made it waits (the progress is below, where a folded part does not hide it).
      h('div', { class: 'stack' },
        h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', disabled: !sourceCount || uploading || !purposeChosen || working, onclick: generate }, t('ai.generate'))),
        form && !purposeChosen ? h('p', { class: 'hint' }, t('ai.purpose_needed')) : null),
    ], { count: sourceCount });
    const results = foldSection('product-images-made', t('ai.made_title'), [
      h('p', { class: 'muted' }, t('ai.made_intro')),
      made.length || coming.length ? h('div', { class: 'ai-grid' }, made.map((image) => tile(image, made)), coming.map(pending)) : h('p', { class: 'muted' }, t('ai.made_none')),
    ], { count: made.length });
    fill(body,
      sources,
      working
        ? h('div', { class: 'ai-progress', role: 'status' }, spinner(),
          h('div', {}, h('strong', {}, t('ai.generating', { done: finished, n: finished + coming.length })), h('p', { class: 'hint' }, t('ai.generating_hint'))))
        : null,
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
      results);
  }

  setTimeout(refresh, 0);
  // Folded away until it is wanted: the pictures are not what a calculation is opened for. The choice is remembered in this browser.
  const card = h('div', { class: 'glass card stack' }, foldHead('product-images', t('ai.card_title'), { open: false }), h('p', { class: 'muted' }, t('ai.card_intro')), options, modelBox, body);
  // The way in from the print file: the card is folded away by default, and the model is what the file is looked at for. Unfolds
  // the card, starts loading the model when that has not been done, and brings it into view.
  card.showModel = (fileId = '') => {
    const fold = card.querySelector('.fold-toggle');
    if (fold && fold.getAttribute('aria-expanded') !== 'true') fold.click();
    wantedModel = fileId;
    shownKey = undefined;                                          // built again, with the model that was asked for in front
    drawModel();
    const load = modelBox.querySelector('[data-load-model]');
    if (load && !load.disabled) load.click();
    modelBox.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };
  return card;
}

/** The "busy" mark on a calculation in the list. */
export const busyBadge = () => h('span', { class: 'badge ai-busy', role: 'status' }, spinner(true), t('ai.busy_badge'));
