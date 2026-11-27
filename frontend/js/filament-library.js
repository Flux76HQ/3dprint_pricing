import { api, downloadFile, upload } from './api.js';
import { formatDate, formatDateTime, getLanguage, t } from './i18n.js';
import { colourOf, spoolIcon } from './filament-ui.js';
import { libraryConfig, libraryName, openForm } from './resources.js';
import { confirmDialog, enhanceDialog, eur, fill, fmt, foldHead, h, icon, saveBlob, toast } from './ui.js';
import { spoolmanDbCard } from './spoolmandb.js';

const norm = (v) => String(v || '').trim().toLowerCase();

/** What an entry is called when two of them differ only by their spool: the name as the invoice preview shows it, with "met spoel" for the one that is not a refill. */
const entryName = (e) => libraryName(e) + (e.refill ? '' : ` · ${t('library.spool_short')}`);

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

const MAX_ROLLS = 200;                                    // BULK_MAX_ROLLS of the server: what one delivery may hold

/** The lines of an invoice, to choose from: what goes in the library and how many rolls go on the shelf (by default the number the invoice says). Nothing happens
 * until *Verwerken*. An invoice that was read in before says so, and then puts nothing on the shelf unless the owner switches it on again. What is done is kept
 * (`invoice_imports`, shown by `importsCard`), so it can be checked against the invoice. */
function invoiceDialog(invoice, onDone) {
  const earlier = invoice.already_imported || [];
  const shelfDone = earlier.some((e) => e.rolls_added > 0);
  const rows = invoice.lines.map((line) => {
    const stock = h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: !shelfDone && line.quantity > 0, 'aria-label': t('library.invoice_shelf') });
    const count = h('input', { type: 'number', min: '0', max: String(MAX_ROLLS), step: '1', inputmode: 'numeric', value: String(line.quantity), disabled: !stock.checked,
      class: 'roll-count', 'aria-label': t('library.invoice_shelf_count') });
    return { line, stock, count, add: h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: true, 'aria-label': t('library.invoice_add') }) };
  });
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const total = h('p', { class: 'muted', 'aria-live': 'polite' });
  const shelf = () => {
    const n = rows.reduce((sum, r) => sum + (r.stock.checked ? Math.max(0, Math.trunc(Number(r.count.value)) || 0) : 0), 0);
    total.textContent = t('library.invoice_shelf_total', { n });
  };
  for (const r of rows) r.stock.addEventListener('change', () => { r.count.disabled = !r.stock.checked; shelf(); });
  for (const r of rows) r.count.addEventListener('input', shelf);
  shelf();
  const apply = async () => {
    error.hidden = true;
    const lines = [];
    for (const { line, add, stock, count } of rows) {
      const n = stock.checked ? Number(count.value) : 0;
      if (!Number.isInteger(n) || n < 0 || n > MAX_ROLLS) { error.textContent = t('library.invoice_bad_count', { max: MAX_ROLLS }); error.hidden = false; count.focus(); return; }
      lines.push({ ...line, library: add.checked, stock_quantity: n });
    }
    if (!lines.some((l) => l.library || l.stock_quantity)) { error.textContent = t('library.invoice_none'); error.hidden = false; return; }
    const meta = { invoice_number: invoice.invoice_number, order_number: invoice.order_number, invoice_date: invoice.invoice_date, total: invoice.total, lines_total: invoice.lines_total };
    try {
      const done = await api('POST', '/api/filament-library/invoice/apply', { lines, invoice: meta });
      dialog.close();
      toast([t('library.import_done', done), done.rolls ? t('library.invoice_rolls_done', { n: done.rolls }) : ''].filter(Boolean).join(' '));
      onDone();
    } catch (e) { error.textContent = e.message; error.hidden = false; }
  };
  const last = earlier[earlier.length - 1];
  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
    h('div', { class: 'stack' },
      h('h2', {}, t('library.invoice_title', { number: invoice.invoice_number || invoice.order_number || '' })),
      h('p', { class: 'muted' }, t('library.invoice_meta', { order: invoice.order_number || '?', date: invoice.invoice_date ? formatDate(invoice.invoice_date, { dateStyle: 'medium' }) : '?' })),
      last ? h('p', { class: 'notice', role: 'status' }, t(shelfDone ? 'library.invoice_again_shelf' : 'library.invoice_again_library',
        { date: formatDateTime(last.imported_at, { dateStyle: 'medium', timeStyle: 'short' }), rolls: earlier.reduce((sum, e) => sum + e.rolls_added, 0) })) : null,
      ...invoice.warnings.map((text) => h('p', { class: 'notice', role: 'status' }, text)),
      invoice.skipped.length ? h('p', { class: 'muted' }, t('library.invoice_skipped', { names: invoice.skipped.join(', ') })) : null,
      h('p', { class: 'hint' }, t('library.invoice_hint_library')),
      total,
      h('ul', { class: 'plain-list' }, rows.map(({ line, add, stock, count }) => h('li', { class: 'list-row' },
        h('div', { class: 'item-head' }, spoolIcon(colourOf(line), 30),
          h('div', { class: 'grow' }, h('strong', {}, entryName(line)),
            h('p', { class: 'muted' }, [line.filament_id ? `${t('library.id_short')} ${line.filament_id}` : null, line.sku ? `${t('library.sku_short')} ${line.sku}` : null].filter(Boolean).join(' · ')),
            h('p', { class: 'muted' }, t('library.invoice_price', { price: eur(line.price) })),
            h('p', { class: 'muted' }, t('library.invoice_paid', { price: eur(line.paid) })),
            h('p', { class: 'muted' }, line.barcode ? t('library.invoice_barcode', { code: line.barcode }) : t('library.invoice_no_barcode')),
            line.library_id ? h('p', { class: 'muted' }, t('library.invoice_known')) : null)),
        h('div', { class: 'stack' },
          h('label', { class: 'check' }, add, t('library.invoice_add')),
          h('label', { class: 'check' }, stock, t('library.invoice_shelf')),
          h('label', { class: 'row' }, count, h('span', { class: 'muted' }, t('library.invoice_shelf_of', { n: line.quantity }))))))),
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

export function contributionJson(entries) {
  const slim = entries.map((e) => Object.fromEntries(Object.entries(e)
    .filter(([key, v]) => v !== null && v !== '' && v !== false && !(key in DEFAULTS && Number(v) === DEFAULTS[key]))));
  return JSON.stringify({ format: FORMAT, format_version: 1, filaments: slim });
}

/** The filaments that the shared library lacks, to choose from. Opening GitHub is the only thing it does: nothing is sent from here, the person
 * reviews the issue there and presses the button themselves. Notes are not part of an entry; neither is anything about the rolls. A contribution
 * that does not fit in an address (about 20 filaments) is shown as a text to copy, and GitHub opens with an empty form to paste it in. */
function contributeDialog({ entries, already_there: known }, base) {
  const rows = entries.map((entry) => ({
    entry, add: h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: true, 'aria-label': t('library.contribute_add') }) }));
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
    h('p', { class: 'muted' }, t('library.contribute_intro', { n: entries.length, known })),
    h('p', { class: 'hint' }, t('library.contribute_hint')),
    h('ul', { class: 'plain-list' }, rows.map(({ entry, add }) => h('li', { class: 'list-row' },
      h('div', { class: 'item-head' }, spoolIcon(colourOf(entry), 30),
        h('div', { class: 'grow' }, h('strong', {}, libraryName(entry)), h('p', { class: 'muted' }, details(entry)))),
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

/** Rolls that fit more than one entry (a refill and a roll with spool): the owner says which one each is, comparing the roll with the invoice data of every
 * entry it could be (name, ID, SKU, reference price and barcode, as the invoice preview shows them). A choice completes that entry from the roll and gives the
 * roll the entry's barcode; a roll left on *Overslaan* is only read. Nothing happens until *Toepassen*. */
function unclearDialog(counts, onDone) {
  const rows = counts.unclear_rolls.map((roll) => {
    const name = `pick-${roll.id}`;
    return { roll, skip: h('input', { type: 'radio', name, value: '', checked: true }),
      options: roll.candidates.map((entry) => ({ entry, input: h('input', { type: 'radio', name, value: entry.id }) })) };
  });
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  // A roll that has a barcode of its own, or belongs to Spoolman or the Bambu cloud, keeps it (`taggable` is the server's word).
  const note = (roll, entry) => {
    if (!roll.taggable) return t('library.unclear_fixed');
    return entry.barcode ? t('library.unclear_tag', { code: entry.barcode }) : t('library.unclear_no_tag');
  };
  const apply = async () => {
    const choices = {};
    for (const { roll, options } of rows) {
      const picked = options.find((o) => o.input.checked);
      if (picked) choices[roll.id] = picked.entry.id;
    }
    if (!Object.keys(choices).length && !counts.added && !counts.updated) { error.textContent = t('library.unclear_none'); error.hidden = false; return; }
    try {
      const done = await api('POST', '/api/filament-library/from-rolls', { choices });
      dialog.close();
      toast([t('library.from_rolls_done', done), done.tagged ? t('library.from_rolls_tagged', done) : '', done.unclear ? t('library.from_rolls_unclear', { n: done.unclear }) : ''].filter(Boolean).join(' '));
      onDone();
    } catch (e) { error.textContent = e.message; error.hidden = false; }
  };
  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
    h('div', { class: 'stack' },
      h('h2', {}, t('library.unclear_title')),
      h('p', { class: 'muted' }, t('library.unclear_intro', { n: rows.length })),
      counts.added || counts.updated ? h('p', { class: 'muted' }, [counts.added ? t('library.unclear_added', { n: counts.added }) : '', counts.updated ? t('library.unclear_updated', { n: counts.updated }) : ''].filter(Boolean).join(' ')) : null,
      h('p', { class: 'hint' }, t('library.unclear_hint')),
      h('ul', { class: 'plain-list' }, rows.map(({ roll, skip, options }) => h('li', { class: 'list-row' }, h('div', { class: 'stack pick-roll' },
        h('div', { class: 'item-head' }, spoolIcon(colourOf(roll), 30),
          h('div', { class: 'grow' }, h('strong', {}, libraryName(roll)),
            h('p', { class: 'muted' }, [`${fmt(roll.roll_weight_g, 0)} g · ${fmt(roll.diameter_mm)} mm`, t('library.unclear_paid', { price: eur(roll.price) }),
              t('library.unclear_left', { g: fmt(roll.remaining_g, 0) })].join(' · ')),
            h('p', { class: 'muted' }, roll.barcode ? t('library.invoice_barcode', { code: roll.barcode }) : t('library.unclear_roll_no_barcode')))),
        h('fieldset', { class: 'pick-list' }, h('legend', { class: 'muted' }, t('library.unclear_pick')),
          options.map(({ entry, input }) => h('label', { class: 'check pick' }, input,
            h('div', { class: 'grow' }, h('strong', {}, entryName(entry)), h('p', { class: 'muted' }, details(entry)),
              h('p', { class: 'muted' }, entry.barcode ? t('library.invoice_barcode', { code: entry.barcode }) : t('library.invoice_no_barcode')),
              h('p', { class: 'hint' }, note(roll, entry))))),
          h('label', { class: 'check pick' }, skip, t('library.unclear_skip'))))))),
      error,
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
        h('button', { class: 'btn primary', type: 'button', onclick: apply }, t('library.unclear_do'))))));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

/** What each invoice that was read in brought, to check it against the invoice: per line the filament, what the invoice says, what went on the shelf, the price paid
 * per roll and what happened in the library. Read from `GET /api/filament-library/invoice-imports`; `state.reloadImports` draws it again after an import. */
function importsCard(state) {
  const body = h('div', { class: 'stack' });
  const sum = (lines, key) => lines.reduce((total, line) => total + Number(line[key] || 0), 0);
  const headings = [[t('library.imports_col_filament'), ''], [t('library.imports_col_invoice'), 'num'], [t('library.imports_col_shelf'), 'num'],
    [t('library.imports_col_paid'), 'num'], [t('library.imports_col_library'), '']];
  const outcome = { added: t('library.imports_lib_added'), updated: t('library.imports_lib_updated'), unchanged: t('library.imports_lib_unchanged'), skipped: t('library.imports_lib_skipped') };
  const table = (lines) => h('div', { class: 'table-wrap' }, h('table', { class: 'data-table' },
    h('thead', {}, h('tr', {}, headings.map(([text, cls]) => h('th', { class: cls, scope: 'col' }, text)))),
    h('tbody', {}, lines.map((line) => h('tr', {},
      h('td', {}, h('div', { class: 'cell-main' }, spoolIcon(colourOf(line), 22), h('div', {}, h('span', { class: 'cell-title' }, entryName(line)),
        h('div', { class: 'cell-sub muted' }, [line.filament_id ? `${t('library.id_short')} ${line.filament_id}` : null, line.sku || null, line.barcode ? t('library.invoice_barcode', { code: line.barcode }) : null].filter(Boolean).join(' · '))))),
      h('td', { class: 'num' }, String(line.quantity)),
      h('td', { class: `num${line.rolls_added === line.quantity ? '' : ' strong'}` }, String(line.rolls_added)),
      h('td', { class: 'num' }, line.paid_price != null ? eur(line.paid_price) : '—'),
      h('td', {}, outcome[line.library] || line.library)))),
    h('tfoot', {}, h('tr', {}, h('th', { scope: 'row' }, t('library.imports_sum')), h('td', { class: 'num strong' }, String(sum(lines, 'quantity'))),
      h('td', { class: 'num strong' }, String(sum(lines, 'rolls_added'))), h('td', {}), h('td', {})))));
  const draw = (imports) => fill(body, imports.length ? imports.map((imp) => h('section', { class: 'stack' },
    h('div', { class: 'row between' }, h('strong', {}, t('library.invoice_title', { number: imp.invoice_number || imp.order_number || '' })),
      h('span', { class: 'badge' }, t('library.imports_rolls', { n: imp.rolls_added }))),
    h('p', { class: 'muted' }, t('library.imports_meta', { order: imp.order_number || '?', date: imp.invoice_date ? formatDate(imp.invoice_date, { dateStyle: 'medium' }) : '?',
      read: formatDateTime(imp.imported_at, { dateStyle: 'medium', timeStyle: 'short' }) })),
    imp.invoice_total != null ? h('p', { class: 'muted' }, t('library.imports_totals', { total: eur(imp.invoice_total), lines: eur(imp.lines_total) })) : null,
    table(imp.lines))) : h('p', { class: 'muted' }, t('library.imports_empty')));
  state.reloadImports = async () => {
    try { draw(await api('GET', '/api/filament-library/invoice-imports')); } catch (e) { fill(body, h('p', { class: 'error' }, e.message)); }
  };
  state.reloadImports();
  return h('div', { class: 'glass card stack' }, foldHead('library-imports', t('library.imports_title'), { open: false }), h('p', { class: 'hint' }, t('library.imports_hint')), body);
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
      if (counts.unclear_rolls.length) { unclearDialog(counts, state.reload); return; }        // some rolls need the owner to say which entry they are
      if (!counts.added && !counts.updated) { toast(t('library.from_rolls_nothing')); return; }
      if (!(await confirmDialog(t('library.from_rolls_confirm', counts), t('library.from_rolls_do')))) return;
      const done = await api('POST', '/api/filament-library/from-rolls');
      toast(t('library.from_rolls_done', done));
      state.reload();
    } catch (e) { toast(e.message, 'error'); }
  };

  // Offer the filaments that the shared library lacks as a contribution: GitHub opens with the issue filled in, nothing is sent from here.
  const contribute = async (base) => {
    try {
      const offer = await api('POST', '/api/filament-library/contribution');
      if (!offer.entries.length) { toast(t('library.contribute_nothing')); return; }
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

  return h('div', { class: 'glass card stack' }, foldHead('library-share', t('library.share_title'), { open: false }),
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
    if (state.reloadImports) state.reloadImports();                              // an import changes the library and brings rolls: its record too
  };
  const cards = [shareCard(state), importsCard(state), spoolmanDbCard(), listCard(state)];
  state.reload();
  return cards;
}
