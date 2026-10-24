import { api, downloadFile, upload } from './api.js';
import { formatDate, t } from './i18n.js';
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

/** The lines of an invoice, to choose from: what goes in the library and how many rolls go on the shelf. */
function invoiceDialog(invoice, onDone) {
  const rows = invoice.lines.map((line) => {
    const add = h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: true, 'aria-label': t('library.invoice_add') });
    const rolls = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', 'aria-label': t('library.invoice_rolls'),
      value: invoice.rolls_on_shelf ? '0' : String(line.quantity) });
    return { line, add, rolls };
  });
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const apply = async () => {
    const lines = rows.filter((r) => r.add.checked || Number(r.rolls.value) > 0)
      .map((r) => ({ ...r.line, add_to_library: r.add.checked, rolls: r.rolls.value.trim() }));
    if (!lines.length) { error.textContent = t('library.invoice_none'); error.hidden = false; return; }
    try {
      const done = await api('POST', '/api/filament-library/invoice/apply', { order_number: invoice.order_number, lines });
      dialog.close();
      toast(t('library.invoice_done', done));
      onDone();
    } catch (e) { error.textContent = e.message; error.hidden = false; }
  };
  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet' },
    h('div', { class: 'stack' },
      h('h2', {}, t('library.invoice_title', { number: invoice.invoice_number || invoice.order_number || '' })),
      h('p', { class: 'muted' }, t('library.invoice_meta', { order: invoice.order_number || '?', date: invoice.invoice_date ? formatDate(invoice.invoice_date, { dateStyle: 'medium' }) : '?' })),
      invoice.warning ? h('p', { class: 'notice', role: 'status' }, invoice.warning) : null,
      invoice.rolls_on_shelf ? h('p', { class: 'notice', role: 'status' }, t('library.invoice_again', { n: invoice.rolls_on_shelf })) : null,
      invoice.skipped.length ? h('p', { class: 'muted' }, t('library.invoice_skipped', { names: invoice.skipped.join(', ') })) : null,
      h('p', { class: 'hint' }, t('library.invoice_rolls_hint')),
      h('ul', { class: 'plain-list' }, rows.map(({ line, add, rolls }) => h('li', { class: 'list-row' },
        h('div', { class: 'item-head' }, spoolIcon(colourOf(line), 30),
          h('div', { class: 'grow' }, h('strong', {}, libraryName(line)),
            h('p', { class: 'muted' }, [line.filament_id ? `${t('library.id_short')} ${line.filament_id}` : null, `${line.quantity} ×`,
              t('library.invoice_prices', { price: eur(line.price), paid: eur(line.paid_price) })].filter(Boolean).join(' · ')),
            line.library_id ? h('p', { class: 'muted' }, t('library.invoice_known')) : null)),
        h('div', { class: 'row' },
          h('label', { class: 'check' }, add, t('library.invoice_add')),
          h('label', { class: 'field roll-count' }, t('library.invoice_rolls'), rolls))))),
      error,
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
        h('button', { class: 'btn primary', type: 'button', onclick: apply }, t('library.invoice_apply'))))));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

/** Invoice, JSON file and GitHub sync: the ways to fill the library without typing. */
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

  const syncBox = h('div', { class: 'stack', hidden: true });
  api('GET', '/api/filament-library/source').then(({ url }) => {
    if (!url) return;
    fill(syncBox, h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', onclick: sync }, icon('sync'), h('span', {}, t('library.sync')))),
      h('p', { class: 'hint breakable' }, t('library.sync_hint', { url })));
    syncBox.hidden = false;
  }).catch(() => { /* the button just stays away */ });

  return h('div', { class: 'glass card stack' }, h('h2', {}, t('library.share_title')),
    h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: () => pdf.click() }, t('library.invoice')), pdf),
    h('p', { class: 'hint' }, t('library.invoice_hint')),
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
