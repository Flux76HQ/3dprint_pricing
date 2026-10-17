import { api } from './api.js';
import { confirmDialog, eur, field, fmt, h, icon, numberInput, parseNum, toast } from './ui.js';

const UNITS = [['stuks', 'stuks'], ['m', 'meter'], ['g', 'gram (prijs per kg)']];
const dateFmt = new Intl.DateTimeFormat('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' });

// --- list -----------------------------------------------------------------------

export function projectListView() {
  const list = h('div', { class: 'cards' }, h('p', { class: 'muted' }, 'Laden…'));
  api('GET', '/api/projects').then((items) => {
    if (!items.length) {
      list.replaceChildren(h('p', { class: 'empty glass card' }, 'Nog geen berekeningen. Maak je eerste kostprijsberekening.'));
      return;
    }
    list.replaceChildren(...items.map((p) => h('a', { class: 'glass card item link-card', href: `#/berekeningen/${p.id}` },
      h('div', { class: 'item-head' },
        h('div', {}, h('h3', {}, p.name,
          p.stock_booked_at ? h('span', { class: 'badge' }, 'Verbruik afgeboekt') : null),
        h('p', { class: 'muted' }, dateFmt.format(new Date(p.updated_at))))),
      h('dl', { class: 'stats' },
        h('div', {}, h('dt', {}, 'Kostprijs'), h('dd', {}, eur(p.totals.cost_price))),
        Number(p.margin_pct) > 0
          ? h('div', {}, h('dt', {}, `Verkoop (+${fmt(p.margin_pct)}%)`), h('dd', {}, eur(p.totals.sell_price)))
          : null))));
  }).catch((e) => toast(e.message, 'error'));
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Berekeningen'), h('p', { class: 'muted' }, 'Kostprijs per print: filament, onderdelen, energie en afschrijving.')),
      h('a', { class: 'btn primary', href: '#/berekeningen/nieuw' }, icon('plus'), h('span', {}, 'Nieuwe berekening'))),
    list);
}

// --- editor ---------------------------------------------------------------------

const blankFilament = () => ({ spool_id: '', label: '', grams: '', price_per_kg: '' });
const blankPart = (group) => ({ group, label: '', quantity: '1', unit: 'stuks', unit_price: '' });

function fromSaved(project) {
  const d = project.data || {};
  const str = (v) => (v == null ? '' : String(v));
  return {
    id: project.id, name: project.name, notes: project.notes, margin_pct: str(project.margin_pct),
    stock_booked_at: project.stock_booked_at,
    filament: (d.filament || []).map((r) => ({ spool_id: r.spool_id || '', label: str(r.label), grams: str(r.grams), price_per_kg: str(r.price_per_kg) })),
    parts: (d.parts || []).map((r) => ({ group: r.group || 'onderdeel', label: str(r.label), quantity: str(r.quantity), unit: r.unit || 'stuks', unit_price: str(r.unit_price) })),
    depreciation: ((d.print || {}).depreciation || []).map((r) => ({ label: str(r.label), printer_id: r.printer_id || '', hours: str(r.hours), price_per_hour: str(r.price_per_hour) })),
    energy: ((d.print || {}).energy || []).map((r) => ({ label: str(r.label), tariff_id: r.tariff_id || '', hours: str(r.hours), kw: str(r.kw), price_per_kwh: str(r.price_per_kwh) })),
  };
}

export function projectEditorView(id, navigate) {
  const root = h('section', { class: 'page' }, h('p', { class: 'muted' }, 'Laden…'));
  Promise.all([
    api('GET', '/api/spools'), api('GET', '/api/printers'), api('GET', '/api/tariffs'),
    id ? api('GET', `/api/projects/${id}`) : Promise.resolve(null),
  ]).then(([spools, printers, tariffs, project]) => {
    root.replaceChildren(buildEditor({
      spools: spools.filter((s) => !s.archived), printers: printers.filter((p) => !p.archived), tariffs, project, navigate,
    }));
  }).catch((e) => root.replaceChildren(h('p', { class: 'error', role: 'alert' }, e.message)));
  return root;
}

function buildEditor({ spools, printers, tariffs, project, navigate }) {
  const state = project ? fromSaved(project) : {
    id: null, name: '', notes: '', margin_pct: '0', stock_booked_at: null,
    filament: [blankFilament()], parts: [], depreciation: [], energy: [],
  };
  let printHours = '1';
  let result = null;
  let dirty = false;
  let timer = null;
  const defaultTariff = tariffs.find((t) => t.is_default) || tariffs[0];
  const perKg = (s) => String(Math.round((Number(s.price) / Number(s.roll_weight_g)) * 1000 * 100) / 100);

  const costEls = { filament: [], parts: [], depreciation: [], energy: [] };
  const totals = h('dl', { class: 'totals' });
  const calcError = h('p', { class: 'error', role: 'alert', hidden: true });
  const sections = h('div', { class: 'stack' });

  const payload = () => ({
    name: state.name, notes: state.notes, margin_pct: parseNum(state.margin_pct),
    data: {
      filament: state.filament.map((r) => ({ spool_id: r.spool_id || null, label: r.label, grams: parseNum(r.grams), price_per_kg: parseNum(r.price_per_kg) })),
      parts: state.parts.map((r) => ({ group: r.group, label: r.label, quantity: parseNum(r.quantity), unit: r.unit, unit_price: parseNum(r.unit_price) })),
      print: {
        depreciation: state.depreciation.map((r) => ({ label: r.label, printer_id: r.printer_id || null, hours: parseNum(r.hours), price_per_hour: parseNum(r.price_per_hour) })),
        energy: state.energy.map((r) => ({ label: r.label, tariff_id: r.tariff_id || null, hours: parseNum(r.hours), kw: parseNum(r.kw), price_per_kwh: parseNum(r.price_per_kwh) })),
      },
    },
  });

  function renderTotals() {
    if (!result) return;
    const row = (label, value, cls = '') => [h('dt', { class: cls }, label), h('dd', { class: cls }, eur(value))];
    const s = result.subtotals;
    totals.replaceChildren(
      ...row('Filament', s.filament), ...row('Onderdelen', s.parts), ...row('Oplader / accessoires', s.charger),
      ...row('Subtotaal onderdelen + lader', s.parts_and_charger, 'sub'),
      ...row('Afschrijving printer', s.depreciation), ...row('Energie', s.energy),
      ...row('Subtotaal energie + afschrijving', s.energy_and_depreciation, 'sub'),
      ...row('Totale kostprijs', result.cost_price, 'grand'),
      ...(Number(result.margin_pct) > 0
        ? [...row(`Marge (${fmt(result.margin_pct)}%)`, result.margin_amount), ...row('Verkoopprijs', result.sell_price, 'grand')]
        : []));
    for (const key of Object.keys(costEls)) {
      costEls[key].forEach((el, i) => {
        if (el && result[key][i]) el.textContent = eur(result[key][i].cost);
      });
    }
  }

  async function recalc() {
    try {
      const body = payload();
      result = await api('POST', '/api/calculate', { data: body.data, margin_pct: body.margin_pct });
      calcError.hidden = true;
      renderTotals();
    } catch (e) {
      calcError.textContent = e.message;
      calcError.hidden = false;
    }
  }
  function touch() {
    dirty = true;
    clearTimeout(timer);
    timer = setTimeout(recalc, 200);
  }

  const bind = (obj, key, extra) => (v) => { obj[key] = v; if (extra) extra(); touch(); };
  const textInput = (obj, key, attrs = {}) => h('input', { type: 'text', value: obj[key], ...attrs, oninput: (e) => bind(obj, key)(e.target.value) });
  const costCell = (bucket, index) => {
    const el = h('output', { class: 'cost' }, '—');
    costEls[bucket][index] = el;
    return h('div', { class: 'field cost-field' }, h('span', { class: 'lbl' }, 'Kosten'), el);
  };
  const removeBtn = (label, onClick) => h('button', { class: 'btn small danger icon-only', type: 'button', 'aria-label': label, onclick: onClick }, icon('trash'));
  const select = (options, value, onChange) => h('select', { onchange: (e) => onChange(e.target.value) },
    options.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));

  function section(title, hint, rows, addButtons) {
    return h('div', { class: 'glass card' },
      h('h2', {}, title), hint ? h('p', { class: 'muted' }, hint) : null,
      h('div', { class: 'lines' }, rows), h('div', { class: 'row' }, addButtons));
  }

  function filamentSection() {
    costEls.filament = [];
    const rows = state.filament.map((r, i) => h('div', { class: 'line filament' },
      field('Rol', select([['', 'Handmatig'], ...spools.map((s) => [s.id, `${[s.brand, s.colour].filter(Boolean).join(' ')} · ${fmt(s.remaining_g, 0)} g over`])], r.spool_id, (v) => {
        r.spool_id = v;
        const s = spools.find((x) => x.id === v);
        if (s) { r.label = [s.brand, s.colour].filter(Boolean).join(' '); r.price_per_kg = perKg(s); }
        touch(); redraw();
      })),
      field('Omschrijving', textInput(r, 'label')),
      field('Gewicht print (g)', numberInput(r.grams, bind(r, 'grams'))),
      field('Prijs per kg (€)', numberInput(r.price_per_kg, bind(r, 'price_per_kg'))),
      costCell('filament', i),
      removeBtn('Verwijder filamentregel', () => { state.filament.splice(i, 1); touch(); redraw(); })));
    return section('Filament', spools.length ? null : 'Tip: voeg je rollen toe onder Filament om ze hier te kiezen.', rows,
      h('button', { class: 'btn small', type: 'button', onclick: () => { state.filament.push(blankFilament()); redraw(); } }, icon('plus'), h('span', {}, 'Filamentregel')));
  }

  function partsSection(group, title, hint) {
    const rows = state.parts.map((r, i) => (r.group !== group ? null : h('div', { class: 'line parts' },
      field('Omschrijving', textInput(r, 'label')),
      field('Aantal', numberInput(r.quantity, bind(r, 'quantity'))),
      field('Eenheid', select(UNITS, r.unit, (v) => { r.unit = v; touch(); })),
      field(r.unit === 'g' ? 'Prijs per kg (€)' : `Prijs per ${r.unit === 'm' ? 'meter' : 'stuk'} (€)`, numberInput(r.unit_price, bind(r, 'unit_price'))),
      costCell('parts', i),
      removeBtn('Verwijder regel', () => { state.parts.splice(i, 1); touch(); redraw(); }))));
    return section(title, hint, rows,
      h('button', { class: 'btn small', type: 'button', onclick: () => { state.parts.push(blankPart(group)); redraw(); } }, icon('plus'), h('span', {}, 'Regel toevoegen')));
  }

  function printSection() {
    const printerSelect = h('select', { 'aria-label': 'Printer' }, printers.map((p) => h('option', { value: p.id }, p.name)));
    const addPrinter = () => {
      const p = printers.find((x) => x.id === printerSelect.value);
      if (!p) return;
      state.depreciation.push({ label: `Afschrijving ${p.name}`, printer_id: p.id, hours: printHours, price_per_hour: String(Math.round((Number(p.purchase_price) / Number(p.lifetime_hours)) * 10000) / 10000) });
      state.energy.push({ label: `Stroom ${p.name}`, tariff_id: defaultTariff ? defaultTariff.id : '', hours: printHours, kw: String(Number(p.power_kw)), price_per_kwh: defaultTariff ? String(Number(defaultTariff.price_per_kwh)) : '' });
      touch(); redraw();
    };
    const hoursInput = numberInput(printHours, (v) => {
      printHours = v;
      state.depreciation.forEach((r) => { r.hours = v; });
      state.energy.forEach((r) => { r.hours = v; });
      touch();
      document.querySelectorAll('.line.print input[data-hours]').forEach((el) => { el.value = v; });
    });
    costEls.depreciation = [];
    costEls.energy = [];
    const depRows = state.depreciation.map((r, i) => h('div', { class: 'line print' },
      field('Afschrijving', textInput(r, 'label')),
      field('Uren', numberInput(r.hours, bind(r, 'hours'), { 'data-hours': '1' })),
      field('Prijs per uur (€)', numberInput(r.price_per_hour, bind(r, 'price_per_hour'))),
      costCell('depreciation', i),
      removeBtn('Verwijder afschrijvingsregel', () => { state.depreciation.splice(i, 1); touch(); redraw(); })));
    const energyRows = state.energy.map((r, i) => h('div', { class: 'line print energy' },
      field('Energie', textInput(r, 'label')),
      field('Uren', numberInput(r.hours, bind(r, 'hours'), { 'data-hours': '1' })),
      field('Vermogen (kW)', numberInput(r.kw, bind(r, 'kw'))),
      field('Tarief', select([['', 'Handmatig'], ...tariffs.map((t) => [t.id, `${t.name} · ${eur(t.price_per_kwh)}`])], r.tariff_id, (v) => {
        r.tariff_id = v;
        const t = tariffs.find((x) => x.id === v);
        if (t) r.price_per_kwh = String(Number(t.price_per_kwh));
        touch(); redraw();
      })),
      field('Prijs per kWh (€)', numberInput(r.price_per_kwh, bind(r, 'price_per_kwh'))),
      costCell('energy', i),
      removeBtn('Verwijder energieregel', () => { state.energy.splice(i, 1); touch(); redraw(); })));
    return h('div', { class: 'glass card' },
      h('h2', {}, 'Printtijd, energie en afschrijving'),
      !printers.length ? h('p', { class: 'muted' }, 'Tip: voeg je printer toe onder Printers; afschrijving en vermogen worden dan automatisch ingevuld.') : null,
      h('div', { class: 'line add-printer' },
        field('Printtijd (uren)', hoursInput, 'Geldt voor alle regels hieronder; je kunt ze apart aanpassen.'),
        printers.length ? field('Printer', printerSelect) : null,
        printers.length ? h('button', { class: 'btn', type: 'button', onclick: addPrinter }, icon('plus'), h('span', {}, 'Printer toevoegen')) : null),
      h('div', { class: 'lines' }, depRows, energyRows),
      h('div', { class: 'row' },
        h('button', { class: 'btn small', type: 'button', onclick: () => { state.energy.push({ label: 'Extra energie', tariff_id: defaultTariff ? defaultTariff.id : '', hours: printHours, kw: '', price_per_kwh: defaultTariff ? String(Number(defaultTariff.price_per_kwh)) : '' }); redraw(); } }, icon('plus'), h('span', {}, 'Extra energieregel')),
        h('button', { class: 'btn small', type: 'button', onclick: () => { state.depreciation.push({ label: 'Afschrijving', printer_id: '', hours: printHours, price_per_hour: '' }); redraw(); } }, icon('plus'), h('span', {}, 'Extra afschrijving'))));
  }

  function redraw() {
    costEls.parts = [];
    sections.replaceChildren(
      filamentSection(),
      partsSection('onderdeel', 'Andere onderdelen', 'Magneten, schroeven, inserts… Bij gram geef je de prijs per kg op.'),
      partsSection('oplader', 'USB-kabel + lader', 'Accessoires die bij het product horen.'),
      printSection());
    renderTotals();
  }

  async function save(asCopy = false) {
    try {
      const body = payload();
      if (asCopy) body.name = `${body.name} (kopie)`;
      const saved = state.id && !asCopy ? await api('PUT', `/api/projects/${state.id}`, body) : await api('POST', '/api/projects', body);
      dirty = false;
      toast('Opgeslagen');
      if (!state.id || asCopy) navigate(`#/berekeningen/${saved.id}`);
      else { state.stock_booked_at = saved.stock_booked_at; }
    } catch (e) { toast(e.message, 'error'); }
  }

  async function bookStock() {
    if (dirty) { toast('Sla de berekening eerst op, dan boek je het opgeslagen verbruik af.', 'error'); return; }
    if (!(await confirmDialog('Het filamentverbruik van deze berekening van de gekozen rollen aftrekken?', 'Afboeken'))) return;
    try {
      const res = await api('POST', `/api/projects/${state.id}/book-stock`);
      toast(res.short.length ? `Afgeboekt, maar te weinig op: ${res.short.join(', ')}` : 'Verbruik afgeboekt', res.short.length ? 'error' : 'info');
      navigate(`#/berekeningen/${state.id}`, true);
    } catch (e) { toast(e.message, 'error'); }
  }

  const nameInput = textInput(state, 'name', { required: true, maxlength: 120, placeholder: 'bijv. USW-Ultra 10-inch rack-mount' });
  const marginInput = numberInput(state.margin_pct, bind(state, 'margin_pct'));
  const notes = h('textarea', { rows: 2, oninput: (e) => bind(state, 'notes')(e.target.value) }, state.notes || '');
  const canBook = state.id && !state.stock_booked_at && state.filament.some((r) => r.spool_id);

  redraw();
  recalc();
  return h('div', { class: 'editor' },
    h('header', { class: 'page-head' },
      h('div', {}, h('a', { class: 'back', href: '#/berekeningen' }, '← Berekeningen'),
        h('h1', {}, state.id ? 'Berekening' : 'Nieuwe berekening'),
        state.stock_booked_at ? h('span', { class: 'badge' }, 'Verbruik afgeboekt') : null)),
    h('div', { class: 'editor-grid' },
      h('div', { class: 'stack' },
        h('div', { class: 'glass card stack' },
          h('div', { class: 'two' }, field('Project', nameInput), field('Marge (%)', marginInput, 'Optioneel: geeft een adviesverkoopprijs.')),
          field('Notities', notes)),
        sections),
      h('aside', { class: 'glass card summary', 'aria-label': 'Kostprijs' },
        h('h2', {}, 'Kostprijs'), totals, calcError,
        h('div', { class: 'stack' },
          h('button', { class: 'btn primary', type: 'button', onclick: () => save(false) }, 'Opslaan'),
          state.id ? h('button', { class: 'btn', type: 'button', onclick: () => save(true) }, 'Opslaan als kopie') : null,
          canBook ? h('button', { class: 'btn', type: 'button', onclick: bookStock }, 'Verbruik afboeken van voorraad') : null,
          state.id ? h('button', { class: 'btn danger', type: 'button', onclick: async () => {
            if (await confirmDialog('Deze berekening verwijderen?')) {
              await api('DELETE', `/api/projects/${state.id}`).catch((e) => toast(e.message, 'error'));
              navigate('#/berekeningen');
            }
          } }, 'Verwijderen') : null))));
}
