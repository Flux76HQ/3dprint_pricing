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
        hint: 'Scan de barcode met je camera of een scanner. Is de barcode bekend, dan worden de gegevens ingevuld en zie je wat je er nog van hebt.' },
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

// What is left per kind of filament: the rolls you still have (with what is on each) and the total,
// plus a total per material.
function stockPanel() {
  const body = h('div', { class: 'stack' });
  const panel = h('section', { class: 'glass card stack', 'aria-labelledby': 'stock-title', hidden: true },
    h('h2', { id: 'stock-title' }, 'Voorraad per soort'), body);
  let data = null;
  let match = () => true;
  const plural = (n) => `${n} ${n === 1 ? 'rol' : 'rollen'}`;

  function draw() {
    panel.hidden = !data || !data.groups.length;
    if (panel.hidden) return;
    const groups = data.groups.filter(match);
    if (!groups.length) { body.replaceChildren(h('p', { class: 'muted' }, 'Geen voorraad met deze filters.')); return; }
    const materials = new Map();                     // totals follow the filter, so they always match what is listed
    for (const g of groups) {
      const name = String(g.material || 'Onbekend materiaal').trim();
      const k = name.toLowerCase();                  // "PLA" and "pla" are one material
      const m = materials.get(k) || { name, rolls: 0, grams: 0 };
      m.rolls += g.roll_count;
      m.grams += Number(g.remaining_g);
      materials.set(k, m);
    }
    body.replaceChildren(
      h('p', { class: 'muted stock-materials' }, [...materials.values()].map((m) => `${m.name}: ${plural(m.rolls)}, ${fmt(m.grams, 0)} g`).join(' · ')),
      h('ul', { class: 'stock', 'aria-label': 'Voorraad per soort' }, groups.map((g) => h('li', { class: g.roll_count ? '' : 'out' },
        h('div', {},
          h('strong', {}, [g.brand, g.colour].filter(Boolean).join(' · ')),
          h('p', { class: 'muted' }, [g.material, g.barcode ? `Barcode ${g.barcode}` : null].filter(Boolean).join(' · ') || ' '),
          g.roll_count
            ? h('p', { class: 'muted' }, `Per rol: ${g.rolls.map((r) => `${fmt(r.remaining_g, 0)} g`).join(', ')}`)
            : h('p', { class: 'muted' }, 'Op: geen rol meer over.')),
        h('div', { class: 'stock-total' },
          h('strong', {}, `${fmt(g.remaining_g, 0)} g`), h('span', { class: 'muted' }, plural(g.roll_count)))))));
  }

  async function refresh() {
    try { data = await api('GET', '/api/spools/stock'); } catch { data = null; }      // a convenience: the list below still works
    draw();
  }
  return { panel, refresh, setFilter(fn) { match = fn; draw(); } };
}

// Filters for the filament list: by material ("soort") and by brand. Options come from what you have,
// the brand options narrow to the chosen material, and both the list and the stock overview follow.
const norm = (v) => String(v || '').trim().toLowerCase();

function filterBar(onChange) {
  const state = { material: '', brand: '' };
  const material = h('select', { id: 'filter-material', 'aria-label': 'Filter op soort' });
  const brand = h('select', { id: 'filter-brand', 'aria-label': 'Filter op merk' });
  const clear = h('button', { class: 'btn small', type: 'button', hidden: true, onclick: () => {
    state.material = ''; state.brand = ''; onChange(); update(lastItems);
  } }, 'Wis filters');
  let lastItems = [];

  const distinct = (rows, key) => {
    const seen = new Map();
    for (const r of rows) if (norm(r[key]) && !seen.has(norm(r[key]))) seen.set(norm(r[key]), String(r[key]).trim());
    return [...seen].sort((a, b) => a[1].localeCompare(b[1], 'nl'));
  };
  const fill = (select, all, options, current) => {
    select.replaceChildren(h('option', { value: '' }, all), ...options.map(([value, label]) => h('option', { value }, label)));
    select.value = options.some(([value]) => value === current) ? current : '';
  };
  function update(items) {
    lastItems = items;
    fill(material, 'Alle soorten', distinct(items, 'material'), state.material);
    state.material = material.value;
    fill(brand, 'Alle merken', distinct(items.filter((i) => !state.material || norm(i.material) === state.material), 'brand'), state.brand);
    state.brand = brand.value;
    clear.hidden = !state.material && !state.brand;
  }
  material.addEventListener('change', () => { state.material = material.value; update(lastItems); onChange(); });
  brand.addEventListener('change', () => { state.brand = brand.value; update(lastItems); onChange(); });

  const matches = (row) => (!state.material || norm(row.material) === state.material) && (!state.brand || norm(row.brand) === state.brand);
  const bar = h('div', { class: 'filters', role: 'group', 'aria-label': 'Filteren' },
    h('label', { for: 'filter-material' }, 'Soort'), material, h('label', { for: 'filter-brand' }, 'Merk'), brand, clear);
  return { bar, update, matches, active: () => !!(state.material || state.brand) };
}

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
  // camera. A known barcode says so, fills in what is known about that filament (never over what was
  // already typed, and only for a new roll) and shows what is in stock of it: confirming is all that is left.
  const CARRIED = ['brand', 'material', 'colour', 'roll_weight_g', 'price', 'diameter_mm', 'print_temp_c', 'bed_temp_c', 'notes'];
  const dirty = new Set();          // fields the user typed in themselves
  function stockLine(stock) {
    if (!stock || !stock.roll_count) return 'Je hebt hier nu geen rol meer van.';
    const weights = stock.rolls.map((r) => `${fmt(r.remaining_g, 0)} g`).join(', ');
    return `Je hebt er nog ${stock.roll_count} ${stock.roll_count === 1 ? 'rol' : 'rollen'} van (${weights}): samen ${fmt(stock.remaining_g, 0)} g.`;
  }
  function barcodeField(f) {
    const id = 'f-barcode';
    const notice = h('div', { class: 'notice stack', role: 'status', hidden: true });
    let looked = null;                              // Enter and then leaving the field must not look up (and reflow) twice
    const lookup = async () => {
      const code = (values[f.key] || '').trim();
      if (item || code === looked) return;         // editing: never overwrite the roll being edited
      looked = code;
      if (!code) { notice.hidden = true; return; }
      try {
        const { spool, stock } = await api('GET', `/api/spools/lookup?barcode=${encodeURIComponent(code)}`);
        if (!spool) {
          notice.replaceChildren(h('span', {}, 'Nieuwe barcode: deze heb je nog niet in je voorraad. Vul de gegevens in.'));
          notice.hidden = false;
          return;
        }
        for (const key of CARRIED) {
          if (dirty.has(key)) continue;
          values[key] = spool[key] ?? '';
          if (els[key]) els[key].value = values[key];
        }
        if (!dirty.has('remaining_g')) {
          values.remaining_g = spool.roll_weight_g;     // a new roll starts full
          if (els.remaining_g) els.remaining_g.value = values.remaining_g;
        }
        notice.replaceChildren(
          h('strong', {}, `Bekende barcode: ${[spool.brand, spool.colour].filter(Boolean).join(' · ')}`),
          h('span', {}, 'De gegevens zijn ingevuld. Controleer ze en kies Opslaan om deze rol toe te voegen.'),
          h('span', {}, stockLine(stock)));
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
      ? h('textarea', { rows: 3, oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); } }, values[f.key] ?? '')
      : h('input', { type: 'text', inputmode: f.type === 'number' ? 'decimal' : 'text', autocomplete: 'off',
        required: f.required, placeholder: f.placeholder, value: values[f.key] ?? '', list: listId,
        oninput: (e) => { values[f.key] = e.target.value; dirty.add(f.key); } });
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
    const visible = items.filter((i) => (showArchived || !i.archived) && (!filters || filters.matches(i)));
    if (!visible.length) {
      list.replaceChildren(h('p', { class: 'empty glass card' },
        filters?.active() && items.length ? 'Geen rollen met deze filters.' : `${config.empty} Voeg de eerste toe.`));
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

  const stock = key === 'filament' ? stockPanel() : null;
  const filters = key === 'filament' ? filterBar(() => {
    render();
    stock.setFilter((g) => filters.matches(g));        // stock groups carry brand and material too
  }) : null;

  async function load() {
    try {
      items = await api('GET', config.path);
      filters?.update(items.filter((i) => showArchived || !i.archived));
      render();
      stock?.refresh();
    } catch (e) { toast(e.message, 'error'); }
  }

  const archiveToggle = config.archivable
    ? h('label', { class: 'check' },
      h('input', { type: 'checkbox', onchange: (e) => { showArchived = e.target.checked; filters?.update(items.filter((i) => showArchived || !i.archived)); render(); } }),
      'Toon gearchiveerd')
    : null;

  load();
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, config.title), h('p', { class: 'muted' }, config.intro)),
      h('button', { class: 'btn primary', type: 'button', onclick: () => openForm(config, null, load) },
        icon('plus'), h('span', {}, `Nieuwe ${config.noun}`))),
    stock?.panel || null, filters?.bar || null, archiveToggle, list);
}
