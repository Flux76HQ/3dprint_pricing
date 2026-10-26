import { api, downloadFile, upload } from './api.js';
import { formatDate, getLanguage, t } from './i18n.js';
import { colourOf, spoolIcon } from './filament-ui.js';
import { libraryConfig, libraryName, openForm } from './resources.js';
import { confirmDialog, enhanceDialog, eur, fill, fmt, h, icon, saveBlob, toast } from './ui.js';

const norm = (v) => String(v || '').trim().toLowerCase();

// What an entry says besides its name: the supplier's ID, the SKU, the specs and the reference price.
function details(e) {
  return [
    e.filament_id ? `${t('library.id_short')} ${e.filament_id}` : null,
    e.sku ? `${t('library.sku_short')} ${e.sku}` : null,
    `${fmt(e.roll_weight_g, 0)} g · ${fmt(e.diameter_mm)} mm`,
    e.print_temp_c != null ? `${e.print_temp_c} °C` : null,
    e.bed_temp_c != null ? `${t('filament.bed_temp_short')} ${e.bed_temp_c} °C` : null,
    e.price != null ? `${t('library.price_short')} ${eur(e.price)}` : null,
  ].filter(Boolean).join(' · ');
}

/** The list of filaments in the library, with a search box. */
function listCard(state) {
  const body = h('div', { class: 'stack' });
  const count = h('p', { class: 'muted', 'aria-live': 'polite' });
  const search = h('input', { type: 'text', autocomplete: 'off', 'aria-label': t('library.search'), placeholder: t('library.search'),
    oninput: () => draw() });

  function draw() {
    const needle = norm(search.value);
    const shown = state.items.filter((e) => !needle || norm([libraryName(e), e.filament_id, e.sku, e.barcode, e.colour].join(' ')).includes(needle));
    count.textContent = state.items.length ? t('library.count', { n: shown.length }) : '';
    search.hidden = state.items.length < 6;
    if (!shown.length) {
      fill(body, h('p', { class: 'muted' }, state.items.length ? t('library.no_match') : t('library.empty')));
      return;
    }
    fill(body, h('ul', { class: 'plain-list' }, shown.map((e) => h('li', { class: 'list-row' },
      h('div', { class: 'item-head' }, spoolIcon(colourOf(e), 30),
        h('div', { class: 'grow' }, h('strong', {}, libraryName(e)), h('p', { class: 'muted' }, details(e)))),
      h('div', { class: 'row' },
        h('button', { class: 'btn small', type: 'button', onclick: () => openForm(libraryConfig(), e, state.reload) }, t('common.edit')),
        h('button', { class: 'btn small danger', type: 'button', 'aria-label': t('common.delete_named', { name: libraryName(e) }), onclick: async () => {
          if (!(await confirmDialog(t('common.delete_confirm', { name: libraryName(e) })))) return;
          try { await api('DELETE', `/api/filament-library/${e.id}`); state.reload(); } catch (err) { toast(err.message, 'error'); }
        } }, icon('trash')))))));
  }
  state.draw = draw;
  draw();
  return h('div', { class: 'glass card stack' },
    h('div', { class: 'row between' }, h('h2', {}, t('library.title')),
      h('button', { class: 'btn primary', type: 'button', onclick: () => openForm(libraryConfig(), null, state.reload) }, icon('plus'), h('span', {}, t('library.add')))),
    h('p', { class: 'muted' }, t('library.intro')), h('div', { class: 'field' }, search), count, body);
}

/** The lines of an invoice, to choose from: what goes in the library. The rolls on the shelf are never touched from here. */
function invoiceDialog(invoice, onDone) {
  const rows = invoice.lines.map((line) => ({
    line, add: h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: true, 'aria-label': t('library.invoice_add') }) }));
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const apply = async () => {
    const lines = rows.filter((r) => r.add.checked).map((r) => r.line);
    if (!lines.length) { error.textContent = t('library.invoice_none'); error.hidden = false; return; }
    try {
      const done = await api('POST', '/api/filament-library/invoice/apply', { lines });
      dialog.close();
      toast(t('library.import_done', done));
      onDone();
    } catch (e) { error.textContent = e.message; error.hidden = false; }
  };
  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
    h('div', { class: 'stack' },
      h('h2', {}, t('library.invoice_title', { number: invoice.invoice_number || invoice.order_number || '' })),
      h('p', { class: 'muted' }, t('library.invoice_meta', { order: invoice.order_number || '?', date: invoice.invoice_date ? formatDate(invoice.invoice_date, { dateStyle: 'medium' }) : '?' })),
      ...invoice.warnings.map((text) => h('p', { class: 'notice', role: 'status' }, text)),
      invoice.skipped.length ? h('p', { class: 'muted' }, t('library.invoice_skipped', { names: invoice.skipped.join(', ') })) : null,
      h('p', { class: 'hint' }, t('library.invoice_hint_library')),
      h('ul', { class: 'plain-list' }, rows.map(({ line, add }) => h('li', { class: 'list-row' },
        h('div', { class: 'item-head' }, spoolIcon(colourOf(line), 30),
          h('div', { class: 'grow' }, h('strong', {}, libraryName(line)),
            h('p', { class: 'muted' }, [line.filament_id ? `${t('library.id_short')} ${line.filament_id}` : null,
              t('library.invoice_price', { price: eur(line.price) })].filter(Boolean).join(' · ')),
            h('p', { class: 'muted' }, line.barcode ? t('library.invoice_barcode', { code: line.barcode }) : t('library.invoice_no_barcode')),
            line.library_id ? h('p', { class: 'muted' }, t('library.invoice_known')) : null)),
        h('label', { class: 'check' }, add, t('library.invoice_add'))))),
      error,
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
        h('button', { class: 'btn primary', type: 'button', onclick: apply }, t('library.invoice_apply'))))));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

/** What goes to GitHub as a contribution: the library file format with only the chosen filaments. Empty fields and the values the server fills in
 * again (`DEFAULTS` in filament_library.py) are left out, so more filaments fit in the address. */
const FORMAT = 'printpricing-filament-library';
const MAX_URL = 7000;                                     // what GitHub takes in an address; a bigger contribution is pasted into the form instead
const DEFAULTS = { roll_weight_g: 1000, diameter_mm: 1.75 };
const FILL_LABELS = { sku: 'library.fill_sku', filament_id: 'library.fill_filament_id', barcode: 'library.fill_barcode', colour_hex: 'library.fill_colour_hex',
  print_temp_c: 'library.fill_print_temp_c', bed_temp_c: 'library.fill_bed_temp_c', price: 'library.fill_price' };      // what a completion can fill in (SHARE_FILLS)

export function contributionJson(entries) {
  const slim = entries.map((e) => Object.fromEntries(Object.entries(e)
    .filter(([key, v]) => key !== 'source' && v !== null && v !== '' && v !== false && !(key in DEFAULTS && Number(v) === DEFAULTS[key]))));
  return JSON.stringify({ format: FORMAT, format_version: 1, filaments: slim });
}

/** The filaments that the shared library lacks, to choose from. Opening GitHub is the only thing it does: nothing is sent from here, the person
 * reviews the issue there and presses the button themselves. Notes are not part of an entry; neither is anything about the rolls. A contribution
 * that does not fit in an address (about 20 filaments) is shown as a text to copy, and GitHub opens with an empty form to paste it in. */
function contributeDialog({ entries, completions, already_there: known }, base) {
  const toggle = () => h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: true, 'aria-label': t('library.contribute_add') });
  const rows = [
    ...entries.map((entry) => ({ entry, add: toggle(), note: entry.source === 'roll' ? t('library.contribute_from_roll') : null, badge: t('library.contribute_new') })),
    ...completions.map(({ entry, fills }) => ({ entry, add: toggle(), badge: t('library.contribute_fill'),
      note: t('library.contribute_fills', { fields: fills.map((key) => t(FILL_LABELS[key])).join(', ') }) })),
  ];
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const body = h('div', { class: 'stack' });

  // Too big for the address: the JSON to copy, then GitHub with an empty form. Nothing is hidden in a toast that can be missed.
  const steps = (json, href, copied) => {
    const box = h('textarea', { readonly: true, rows: 6, class: 'mono', 'aria-label': t('library.contribute_json'), onfocus: () => box.select() }, json);
    const status = h('p', { class: 'notice', role: 'status' }, copied ? t('library.contribute_copied') : t('library.contribute_copy_hint'));
    const copy = async () => {
      try { await navigator.clipboard.writeText(json); status.textContent = t('library.contribute_copied'); } catch { box.focus(); status.textContent = t('library.contribute_copy_hint'); }
    };
    fill(body,
      h('h2', {}, t('library.contribute_steps_title')),
      h('p', { class: 'muted' }, t('library.contribute_steps_intro')),
      h('ol', { class: 'steps' },
        h('li', {}, t('library.contribute_step_copy')), h('li', {}, t('library.contribute_step_open')), h('li', {}, t('library.contribute_step_paste'))),
      box, status,
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: copy }, t('library.contribute_copy')),
        h('a', { class: 'btn primary', href, target: '_blank', rel: 'noopener noreferrer', onclick: () => dialog.close() }, t('library.contribute_open_github'))));
  };

  const open = () => {
    const chosen = rows.filter((r) => r.add.checked).map((r) => r.entry);
    if (!chosen.length) { error.textContent = t('library.contribute_none'); error.hidden = false; return; }
    const json = contributionJson(chosen);
    const form = `${getLanguage() === 'nl' ? 'nl-' : ''}05-filament-library.yml`;
    const params = new URLSearchParams({ template: form, title: t('library.contribute_issue_title', { n: chosen.length }) });
    const bare = `${base}?${params}`;
    params.set('contribution', json);
    if (`${base}?${params}`.length <= MAX_URL) {
      window.open(`${base}?${params}`, '_blank', 'noopener');
      dialog.close();
      toast(t('library.contribute_opened'));
      return;
    }
    const copied = navigator.clipboard?.writeText(json);                          // started in the click, so the browser allows it
    steps(json, bare, false);
    Promise.resolve(copied).then(() => { if (copied) body.querySelector('[role=status]').textContent = t('library.contribute_copied'); }, () => null);
  };
  fill(body,
    h('h2', {}, t('library.contribute_title')),
    h('p', { class: 'muted' }, t('library.contribute_intro', { n: entries.length, filled: completions.length, known })),
    h('p', { class: 'hint' }, t('library.contribute_hint')),
    h('ul', { class: 'plain-list' }, rows.map(({ entry, add, note, badge }) => h('li', { class: 'list-row' },
      h('div', { class: 'item-head' }, spoolIcon(colourOf(entry), 30),
        h('div', { class: 'grow' }, h('strong', {}, libraryName(entry), ' ', h('span', { class: 'badge muted' }, badge)), h('p', { class: 'muted' }, details(entry)),
          note ? h('p', { class: 'hint' }, note) : null)),
      h('label', { class: 'check' }, add, t('library.contribute_add'))))),
    error,
    h('div', { class: 'row end' },
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
      h('button', { class: 'btn primary', type: 'button', onclick: open }, t('library.contribute_do'))));
  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' }, body));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

/** Invoice, the rolls in stock, JSON file and GitHub sync: the ways to fill the library without typing. */
function shareCard(state) {
  const pdf = h('input', { type: 'file', accept: '.pdf,application/pdf', hidden: true, 'aria-label': t('library.invoice'), onchange: async () => {
    const chosen = pdf.files[0];
    pdf.value = '';
    if (!chosen) return;
    const form = new FormData();
    form.append('file', chosen);
    try { invoiceDialog(await upload('/api/filament-library/invoice', form), state.reload); } catch (e) { toast(e.message, 'error'); }
  } });

  const json = h('input', { type: 'file', accept: '.json,application/json', hidden: true, 'aria-label': t('library.import'), onchange: async () => {
    const chosen = json.files[0];
    json.value = '';
    if (!chosen) return;
    let doc;
    try { doc = JSON.parse(await chosen.text()); } catch { toast(t('backup.not_json'), 'error'); return; }
    try {
      const counts = await api('POST', '/api/filament-library/import?dry_run=1', doc);                    // checked first, nothing changes yet
      if (!(await confirmDialog(t('library.import_confirm', counts), t('library.import_do')))) return;
      const done = await api('POST', '/api/filament-library/import', doc);
      toast(t('library.import_done', done));
      state.reload();
    } catch (e) { toast(e.message, 'error'); }
  } });

  const exportFile = async () => {
    try {
      const { blob, name } = await downloadFile('/api/filament-library/export');
      saveBlob(blob, name);
      toast(t('library.exported', { name }));
    } catch (e) { toast(e.message, 'error'); }
  };

  const sync = async () => {
    try {
      const counts = await api('POST', '/api/filament-library/sync?dry_run=1');
      if (!counts.added && !counts.updated) { toast(t('library.sync_nothing')); return; }
      if (!(await confirmDialog(t('library.sync_confirm', counts), t('library.sync_do')))) return;
      const done = await api('POST', '/api/filament-library/sync');
      toast(t('library.import_done', done));
      state.reload();
    } catch (e) { toast(e.message, 'error'); }
  };

  // The rolls in the filament list (not archived) go in the library, so they can be shared too. Asked first, with the numbers, like Sync.
  const fromRolls = async () => {
    try {
      const counts = await api('POST', '/api/filament-library/from-rolls?dry_run=1');
      const unclear = counts.unclear ? ` ${t('library.from_rolls_unclear', counts)}` : '';
      if (!counts.added && !counts.updated) { toast(t('library.from_rolls_nothing') + unclear); return; }
      if (!(await confirmDialog(t('library.from_rolls_confirm', counts) + unclear, t('library.from_rolls_do')))) return;
      const done = await api('POST', '/api/filament-library/from-rolls');
      toast(t('library.from_rolls_done', done));
      state.reload();
    } catch (e) { toast(e.message, 'error'); }
  };

  // Offer the filaments that the shared library lacks as a contribution: GitHub opens with the issue filled in, nothing is sent from here.
  const contribute = async (base) => {
    try {
      const offer = await api('POST', '/api/filament-library/contribution');
      if (!offer.entries.length && !offer.completions.length) { toast(t('library.contribute_nothing')); return; }
      contributeDialog(offer, base);
    } catch (e) { toast(e.message, 'error'); }
  };

  const syncBox = h('div', { class: 'stack', hidden: true });
  api('GET', '/api/filament-library/source').then(({ url, contribute_url: base }) => {
    if (!url) return;
    fill(syncBox, h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: sync }, icon('sync'), h('span', {}, t('library.sync'))),
      base ? h('button', { class: 'btn', type: 'button', onclick: () => contribute(base) }, t('library.contribute')) : null),
      h('p', { class: 'hint breakable' }, t('library.sync_hint', { url })),
      base ? h('p', { class: 'hint' }, t('library.contribute_button_hint')) : null);
    syncBox.hidden = false;
  }).catch(() => { /* the button just stays away */ });

  return h('div', { class: 'glass card stack' }, h('h2', {}, t('library.share_title')),
    h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: () => pdf.click() }, t('library.invoice')), pdf),
    h('p', { class: 'hint' }, t('library.invoice_hint')),
    h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: fromRolls }, icon('sync'), h('span', {}, t('library.from_rolls')))),
    h('p', { class: 'hint' }, t('library.from_rolls_hint')),
    syncBox,
    h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onclick: exportFile }, t('library.export')),
      h('button', { class: 'btn', type: 'button', onclick: () => json.click() }, t('library.import')), json),
    h('p', { class: 'hint' }, t('library.share_hint')));
}

/** The cards of Settings -> Filaments. */
export function filamentLibraryCards() {
  const state = { items: [], draw: () => {}, reload: null };
  state.reload = async () => {
    try { state.items = await api('GET', '/api/filament-library'); state.draw(); } catch (e) { toast(e.message, 'error'); }
  };
  const cards = [shareCard(state), listCard(state)];
  state.reload();
  return cards;
}
