import { api } from './api.js';
import { scanBarcode } from './scanner.js';
import { confirmDialog, eur, field, fmt, h, icon, toast } from './ui.js';

// Declarative config for the three inventory/rate screens. Money and quantities are
// sent as typed; the server validates and is the only place that decides what is valid.
const num = (v) => (v === '' || v == null ? '' : String(v).replace(',', '.'));

export const RESOURCES = {
  filament: {
    title: 'Filament', path: '/api/spools', noun: 'rol', empty: 'Nog geen filamentrollen.', archivable: true,
    intro: 'Je filamentrollen met aanschafprijs en wat er nog op zit. Kies ze in een berekening; ' +
      'de prijs per kg volgt uit prijs ÷ gewicht.',
    defaults: { brand: '', material: '', colour: '', roll_weight_g: '1000', price: '', remaining_g: '1000',
      barcode: '', diameter_mm: '1.75', print_temp_c: '', bed_temp_c: '', notes: '' },
    fields: [
      { key: 'barcode', label: 'Barcode', type: 'barcode',
        hint: 'Scan de barcode met je camera of een scanner. Bij een bekende barcode kun je de gegevens van de vorige rol overnemen.' },
      { key: 'brand', label: 'Merk / type', type: 'text', required: true, placeholder: 'Bambu ABS Basis' },
      { key: 'material', label: 'Materiaal', type: 'text', placeholder: 'ABS' },
      { key: 'colour', label: 'Kleur', type: 'text', placeholder: 'Black' },
      { key: 'roll_weight_g', label: 'Gewicht rol (gram)', type: 'number', required: true },
      { key: 'price', label: 'Prijs rol (€)', type: 'number', required: true },
      { key: 'remaining_g', label: 'Nog over (gram)', type: 'number', required: true },
      { key: 'diameter_mm', label: 'Diameter (mm)', type: 'number', required: true, list: ['1.75', '2.85'] },
      { key: 'print_temp_c', label: 'Printtemperatuur (°C)', type: 'number', placeholder: 'bijv. 250', hint: 'Optioneel; de aanbevolen nozzle-temperatuur.' },
      { key: 'bed_temp_c', label: 'Bedtemperatuur (°C)', type: 'number', placeholder: 'bijv. 90', hint: 'Optioneel.' },
      { key: 'notes', label: 'Notities', type: 'textarea' },
    ],
    card(item) {
      const perKg = Number(item.price) / Number(item.roll_weight_g) * 1000;
      const pct = Math.max(0, Math.min(100, Number(item.remaining_g) / Number(item.roll_weight_g) * 100));
      const bar = h('div', { class: 'meter', role: 'img',
        'aria-label': `${fmt(item.remaining_g, 0)} van ${fmt(item.roll_weight_g, 0)} gram over` }, h('span'));
      bar.firstChild.style.width = `${pct}%`;
      return {
        title: [item.brand, item.colour].filter(Boolean).join(' · '),
        subtitle: [item.material, `${eur(item.price)} per rol`].filter(Boolean).join(' · '),
        stats: [['Per kg', eur(perKg)], ['Over', `${fmt(item.remaining_g, 0)} g`], ['Diameter', `${fmt(item.diameter_mm)} mm`],
          ...(item.print_temp_c != null ? [['Printtemp.', `${item.print_temp_c} °C`]] : []),
          ...(item.bed_temp_c != null ? [['Bedtemp.', `${item.bed_temp_c} °C`]] : [])],
        extra: bar,
        footnote: item.barcode ? `Barcode ${item.barcode}` : null,
      };
    },
  },
  verpakking: {
    title: 'Verpakking', path: '/api/packaging', noun: 'verpakking', empty: 'Nog geen verpakkingen.', archivable: true,
    intro: 'Dozen en ander verpakkingsmateriaal met de prijs per stuk. Kies ze per product in een berekening.',
    defaults: { name: '', price: '', notes: '' },
    fields: [
      { key: 'name', label: 'Naam', type: 'text', required: true, placeholder: 'Doos 20 × 15 × 10 cm' },
      { key: 'price', label: 'Prijs per stuk (€)', type: 'number', required: true,
        hint: 'Reken vulmateriaal en tape mee, of maak daar een eigen regel voor.' },
      { key: 'notes', label: 'Notities', type: 'textarea' },
    ],
    card(item) {
      return { title: item.name, subtitle: item.notes || null, stats: [['Per stuk', eur(item.price)]] };
    },
  },
  printers: {
    title: 'Printers', path: '/api/printers', noun: 'printer', empty: 'Nog geen printers.', archivable: true,
    intro: 'De afschrijving per uur is aanschafwaarde ÷ verwachte levensduur in uren.',
    defaults: { name: '', purchase_price: '', lifetime_hours: '3000', power_kw: '0.15', notes: '' },
    fields: [
      { key: 'name', label: 'Naam', type: 'text', required: true, placeholder: 'Bambu Lab X1C' },
      { key: 'purchase_price', label: 'Aanschafwaarde (€)', type: 'number', required: true },
      { key: 'lifetime_hours', label: 'Levensduur (uren)', type: 'number', required: true },
      { key: 'power_kw', label: 'Gemiddeld vermogen (kW)', type: 'number',
        hint: 'kWh per printuur, bijv. 0,15 voor 150 W gemiddeld.' },
      { key: 'notes', label: 'Notities', type: 'textarea' },
    ],
    card(item) {
      const perHour = Number(item.purchase_price) / Number(item.lifetime_hours);
      return {
        title: item.name,
        subtitle: `${eur(item.purchase_price)} · ${fmt(item.lifetime_hours, 0)} uur levensduur`,
        stats: [['Afschrijving', `${eur(perHour)} /uur`], ['Vermogen', `${fmt(item.power_kw, 3)} kW`]],
      };
    },
  },
  energie: {
    title: 'Energie', path: '/api/tariffs', noun: 'tarief', empty: 'Nog geen stroomtarieven.', archivable: false,
    intro: 'Je stroomprijzen per kWh. Het standaardtarief wordt voorgesteld in nieuwe berekeningen.',
    defaults: { name: '', price_per_kwh: '' },
    fields: [
      { key: 'name', label: 'Naam', type: 'text', required: true, placeholder: 'Thuis, dynamisch' },
      { key: 'price_per_kwh', label: 'Prijs per kWh (€)', type: 'number', required: true },
    ],
    card(item) {
      return {
        title: item.name, badge: item.is_default ? 'Standaard' : null,
        stats: [['Prijs', `${eur(item.price_per_kwh)} /kWh`]],
      };
    },
    actions(item, reload) {
      if (item.is_default) return [];
      return [h('button', { class: 'btn small', type: 'button', onclick: async () => {
        await api('PATCH', `${this.path}/${item.id}`, { is_default: true });
        reload();
      } }, 'Maak standaard')];
    },
  },
};

function toPayload(config, values) {
  const out = {};
  for (const f of config.fields) {
    out[f.key] = f.type === 'number' ? num(values[f.key]) : values[f.key];
  }
  return out;
}

function openForm(config, item, reload) {
  const values = { ...(item || config.defaults) };
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const els = {};          // inputs by key, so "copy from the previous roll" can fill them
  const datalists = [];

  // A barcode field: type it, use a hardware scanner (it types and presses Enter), or scan with the
  // camera. A known barcode offers to copy the details of the newest roll with that barcode.
  function barcodeField(f) {
    const id = 'f-barcode';
    const notice = h('div', { class: 'notice stack', role: 'status', hidden: true });
    const lookup = async () => {
      const code = (values[f.key] || '').trim();
      notice.hidden = true;
      if (item || !code) return;                   // editing: never overwrite the roll being edited
      try {
        const { spool } = await api('GET', `/api/spools/lookup?barcode=${encodeURIComponent(code)}`);
        if (!spool) return;
        notice.replaceChildren(
          h('span', {}, `Bekende barcode: ${[spool.brand, spool.colour].filter(Boolean).join(' ')} (${eur(spool.price)} per rol). `),
          h('button', { class: 'btn small', type: 'button', onclick: () => {
            for (const key of ['brand', 'material', 'colour', 'roll_weight_g', 'price', 'diameter_mm', 'print_temp_c', 'bed_temp_c', 'notes']) {
              values[key] = spool[key] ?? '';
              if (els[key]) els[key].value = values[key];
            }
            values.remaining_g = spool.roll_weight_g;     // a new roll starts full
            if (els.remaining_g) els.remaining_g.value = values.remaining_g;
            notice.hidden = true;
            toast('Gegevens overgenomen van de vorige rol');
          } }, 'Gegevens overnemen'));
        notice.hidden = false;
      } catch { /* the lookup is a convenience */ }
    };
    const input = h('input', { type: 'text', id, autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false',
      placeholder: 'Scan of typ de barcode', value: values[f.key] ?? '',
      oninput: (e) => { values[f.key] = e.target.value; },
      onchange: lookup,
      // Hardware scanners end with Enter: look it up instead of submitting the form half-filled.
      onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); lookup(); } } });
    els[f.key] = input;
    const scan = h('button', { class: 'btn', type: 'button', onclick: async () => {
      const code = await scanBarcode();
      if (code) { input.value = code; values[f.key] = code; lookup(); }
    } }, icon('scan'), h('span', {}, 'Scan'));
    return h('div', { class: 'field' }, h('label', { for: id }, f.label),
      h('div', { class: 'row nowrap' }, input, scan), f.hint ? h('p', { class: 'hint' }, f.hint) : null, notice);
  }

  const inputs = config.fields.map((f) => {
    if (f.type === 'barcode') return barcodeField(f);
    let listId = null;
    if (f.list) {
      listId = `dl-${f.key}`;
      datalists.push(h('datalist', { id: listId }, f.list.map((v) => h('option', { value: v }))));
    }
    const input = f.type === 'textarea'
      ? h('textarea', { rows: 3, oninput: (e) => { values[f.key] = e.target.value; } }, values[f.key] ?? '')
      : h('input', { type: 'text', inputmode: f.type === 'number' ? 'decimal' : 'text', autocomplete: 'off',
        required: f.required, placeholder: f.placeholder, value: values[f.key] ?? '', list: listId,
        oninput: (e) => { values[f.key] = e.target.value; } });
    els[f.key] = input;
    return field(f.label, input, f.hint);
  });
  const dialog = h('dialog', { class: 'glass sheet' },
    h('form', { class: 'stack', method: 'dialog', onsubmit: async (e) => {
      e.preventDefault();
      try {
        const payload = toPayload(config, values);
        if (item) await api('PATCH', `${config.path}/${item.id}`, payload);
        else await api('POST', config.path, payload);
        dialog.close();
        toast('Opgeslagen');
        reload();
      } catch (err) { error.textContent = err.message; error.hidden = false; }
    } },
    h('h2', {}, item ? `${config.noun[0].toUpperCase()}${config.noun.slice(1)} wijzigen` : `Nieuwe ${config.noun}`),
    ...inputs, ...datalists, error,
    h('div', { class: 'row end' },
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.close() }, 'Annuleren'),
      h('button', { class: 'btn primary', type: 'submit' }, 'Opslaan'))));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

export function resourceView(key) {
  const config = RESOURCES[key];
  const list = h('div', { class: 'cards' });
  let showArchived = false;
  let items = [];

  const render = () => {
    const visible = items.filter((i) => showArchived || !i.archived);
    if (!visible.length) {
      list.replaceChildren(h('p', { class: 'empty glass card' }, `${config.empty} Voeg de eerste toe.`));
      return;
    }
    list.replaceChildren(...visible.map((item) => {
      const c = config.card(item);
      const extraActions = config.actions ? config.actions.call(config, item, load) : [];
      return h('article', { class: `glass card item${item.archived ? ' archived' : ''}` },
        h('div', { class: 'item-head' },
          h('div', {}, h('h3', {}, c.title, c.badge ? h('span', { class: 'badge' }, c.badge) : null,
            item.archived ? h('span', { class: 'badge muted' }, 'Gearchiveerd') : null),
          c.subtitle ? h('p', { class: 'muted' }, c.subtitle) : null)),
        h('dl', { class: 'stats' }, c.stats.map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v)))),
        c.extra || null,
        c.footnote ? h('p', { class: 'muted footnote' }, c.footnote) : null,
        h('div', { class: 'row' },
          h('button', { class: 'btn small', type: 'button', onclick: () => openForm(config, item, load) }, 'Wijzigen'),
          ...extraActions,
          config.archivable ? h('button', { class: 'btn small', type: 'button', onclick: async () => {
            await api('PATCH', `${config.path}/${item.id}`, { archived: !item.archived });
            load();
          } }, item.archived ? 'Terugzetten' : 'Archiveren') : null,
          h('button', { class: 'btn small danger', type: 'button', 'aria-label': `Verwijder ${c.title}`,
            onclick: async () => {
              if (await confirmDialog(`“${c.title}” verwijderen? Opgeslagen berekeningen blijven ongewijzigd.`)) {
                await api('DELETE', `${config.path}/${item.id}`);
                load();
              }
            } }, icon('trash'))));
    }));
  };

  async function load() {
    try {
      items = await api('GET', config.path);
      render();
    } catch (e) { toast(e.message, 'error'); }
  }

  const archiveToggle = config.archivable
    ? h('label', { class: 'check' },
      h('input', { type: 'checkbox', onchange: (e) => { showArchived = e.target.checked; render(); } }),
      'Toon gearchiveerd')
    : null;

  load();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, config.title), h('p', { class: 'muted' }, config.intro)),
      h('button', { class: 'btn primary', type: 'button', onclick: () => openForm(config, null, load) },
        icon('plus'), h('span', {}, `Nieuwe ${config.noun}`))),
    archiveToggle, list);
}
