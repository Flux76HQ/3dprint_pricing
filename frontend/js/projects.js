import { api, upload } from './api.js';
import { blurToggle, confirmDialog, eur, field, fmt, h, icon, numberInput, parseNum, toast } from './ui.js';

const ROUNDINGS = [['none', 'Niet afronden'], ['0.05', 'Op 5 cent'], ['0.10', 'Op 10 cent'], ['0.50', 'Op 50 cent'],
  ['1.00', 'Op hele euro'], ['5.00', 'Op 5 euro'], ['x.95', 'Eindigend op ,95'], ['x.99', 'Eindigend op ,99']];
const UNITS = [['stuks', 'stuks'], ['m', 'meter'], ['g', 'gram (prijs per kg)']];
const dateFmt = new Intl.DateTimeFormat('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' });

// --- list -----------------------------------------------------------------------

export function projectListView(ctx) {
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
        h('div', {}, h('dt', {}, 'Kostprijs'), h('dd', { class: 'private' }, eur(p.totals.cost_price))),
        Number(p.vat_pct) > 0
          ? h('div', {}, h('dt', {}, `Verkoop incl. ${fmt(p.vat_pct)}% btw`), h('dd', {}, eur(p.totals.sell_price_incl_vat)))
          : (Number(p.margin_pct) > 0 || p.price_rounding !== 'none'
            ? h('div', {}, h('dt', {}, 'Verkoop'), h('dd', {}, eur(p.totals.sell_price))) : null)))));
  }).catch((e) => toast(e.message, 'error'));
  return h('section', { class: 'page' },
    h('header', { class: 'page-head' },
      h('div', {}, h('h1', {}, 'Berekeningen'), h('p', { class: 'muted' }, 'Kostprijs per print: filament, onderdelen, energie en afschrijving.')),
      h('div', { class: 'row' }, blurToggle(ctx),
        h('a', { class: 'btn primary', href: '#/berekeningen/nieuw' }, icon('plus'), h('span', {}, 'Nieuwe berekening')))),
    list);
}

// --- editor ---------------------------------------------------------------------

// "Bambu ABS Basis Black · ABS · 430 g over": the material is part of the choice (ABS/PLA/PLA+ ...).
const spoolLabel = (s) => [[s.brand, s.colour].filter(Boolean).join(' '), s.material, `${fmt(s.remaining_g, 0)} g over`].filter(Boolean).join(' · ');
const blankFilament = () => ({ spool_id: '', label: '', grams: '', price_per_kg: '' });
const blankPart = (group) => ({ group, packaging_id: '', label: '', quantity: '1', unit: 'stuks', unit_price: '' });

function fromSaved(project) {
  const d = project.data || {};
  const str = (v) => (v == null ? '' : String(v));
  return {
    id: project.id, name: project.name, notes: project.notes, margin_pct: str(project.margin_pct),
    file_id: project.file_id || null, source_url: project.source_url || '',
    vat_pct: str(project.vat_pct), price_rounding: project.price_rounding || 'none',
    stock_booked_at: project.stock_booked_at,
    filament: (d.filament || []).map((r) => ({ spool_id: r.spool_id || '', label: str(r.label), grams: str(r.grams), price_per_kg: str(r.price_per_kg) })),
    parts: (d.parts || []).map((r) => ({ group: r.group || 'onderdeel', packaging_id: r.packaging_id || '', label: str(r.label), quantity: str(r.quantity), unit: r.unit || 'stuks', unit_price: str(r.unit_price) })),
    depreciation: ((d.print || {}).depreciation || []).map((r) => ({ label: str(r.label), printer_id: r.printer_id || '', hours: str(r.hours), price_per_hour: str(r.price_per_hour) })),
    energy: ((d.print || {}).energy || []).map((r) => ({ label: str(r.label), tariff_id: r.tariff_id || '', hours: str(r.hours), kw: str(r.kw), price_per_kwh: str(r.price_per_kwh) })),
  };
}

export function projectEditorView(id, navigate, ctx = { prefs: {}, setPrefs: async () => {} }) {
  const root = h('section', { class: 'page' }, h('p', { class: 'muted' }, 'Laden…'));
  Promise.all([
    api('GET', '/api/spools'), api('GET', '/api/printers'), api('GET', '/api/tariffs'), api('GET', '/api/packaging'),
    id ? api('GET', `/api/projects/${id}`) : Promise.resolve(null),
  ]).then(([spools, printers, tariffs, packaging, project]) => {
    root.replaceChildren(buildEditor({
      spools: spools.filter((s) => !s.archived), printers: printers.filter((p) => !p.archived), tariffs,
      packaging: packaging.filter((p) => !p.archived), project, navigate, ctx,
    }));
  }).catch((e) => root.replaceChildren(h('p', { class: 'error', role: 'alert' }, e.message)));
  return root;
}

function buildEditor({ spools, printers, tariffs, packaging, project, navigate, ctx }) {
  const state = project ? fromSaved(project) : {
    id: null, name: '', notes: '', margin_pct: '0', stock_booked_at: null, file_id: null, source_url: '',
    vat_pct: ctx.prefs.vat_pct ?? '21', price_rounding: ctx.prefs.price_rounding || 'none',
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
  const roundNote = h('p', { class: 'hint', role: 'status', hidden: true });
  const calcError = h('p', { class: 'error', role: 'alert', hidden: true });
  const sections = h('div', { class: 'stack' });

  const payload = () => ({
    name: state.name, notes: state.notes, margin_pct: parseNum(state.margin_pct),
    vat_pct: parseNum(state.vat_pct), price_rounding: state.price_rounding,
    file_id: state.file_id, source_url: state.source_url.trim(),
    data: {
      filament: state.filament.map((r) => ({ spool_id: r.spool_id || null, label: r.label, grams: parseNum(r.grams), price_per_kg: parseNum(r.price_per_kg) })),
      parts: state.parts.map((r) => ({ group: r.group, packaging_id: r.packaging_id || null, label: r.label, quantity: parseNum(r.quantity), unit: r.unit, unit_price: parseNum(r.unit_price) })),
      print: {
        depreciation: state.depreciation.map((r) => ({ label: r.label, printer_id: r.printer_id || null, hours: parseNum(r.hours), price_per_hour: parseNum(r.price_per_hour) })),
        energy: state.energy.map((r) => ({ label: r.label, tariff_id: r.tariff_id || null, hours: parseNum(r.hours), kw: parseNum(r.kw), price_per_kwh: parseNum(r.price_per_kwh) })),
      },
    },
  });

  function renderTotals() {
    if (!result) return;
    // Cost-side rows are marked private so the "hide costs" setting can blur them; selling price, VAT stay visible.
    const row = (label, value, cls = '', priv = false) => [h('dt', { class: `${cls}${priv ? ' private' : ''}` }, label), h('dd', { class: `${cls}${priv ? ' private' : ''}` }, eur(value))];
    const cost = (label, value, cls = '') => row(label, value, cls, true);
    const s = result.subtotals;
    const hasMargin = Number(result.margin_amount) > 0 || result.rounding !== 'none';
    const hasVat = Number(result.vat_pct) > 0;
    totals.replaceChildren(
      ...cost('Filament', s.filament), ...cost('Onderdelen', s.parts), ...cost('Oplader / accessoires', s.charger),
      ...cost('Subtotaal onderdelen + lader', s.parts_and_charger, 'sub'),
      ...cost('Verpakking', s.packaging),
      ...cost('Afschrijving printer', s.depreciation), ...cost('Energie', s.energy),
      ...cost('Subtotaal energie + afschrijving', s.energy_and_depreciation, 'sub'),
      ...cost('Totale kostprijs', result.cost_price, 'grand'),
      ...(hasMargin ? cost(`Marge (${fmt(result.margin_pct_effective)}%)`, result.margin_amount) : []),
      ...(hasMargin || hasVat ? row('Verkoopprijs excl. btw', result.sell_price, 'sub') : []),
      ...(hasVat ? [...row(`BTW (${fmt(result.vat_pct)}%)`, result.vat_amount), ...row('Verkoopprijs incl. btw', result.sell_price_incl_vat, 'grand')] : []));
    const lifted = result.rounding !== 'none' && Number(result.margin_pct_effective) > Number(result.margin_pct) + 0.004;
    roundNote.textContent = lifted ? `Marge opgehoogd van ${fmt(result.margin_pct)}% naar ${fmt(result.margin_pct_effective)}% voor een ronde prijs.` : '';
    roundNote.hidden = !lifted;
    for (const key of Object.keys(costEls)) {
      costEls[key].forEach((el, i) => {
        if (el && result[key][i]) {
          el.textContent = eur(result[key][i].cost);
          if (result[key][i].hours_billed) el.title = `Gerekend als ${fmt(result[key][i].hours_billed, 0)} uur`;
        }
      });
    }
  }

  async function recalc() {
    try {
      const body = payload();
      result = await api('POST', '/api/calculate', { data: body.data, margin_pct: body.margin_pct, vat_pct: body.vat_pct, price_rounding: body.price_rounding });
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
    const el = h('output', { class: 'cost private' }, '—');
    costEls[bucket][index] = el;
    return h('div', { class: 'field cost-field' }, h('span', { class: 'lbl' }, 'Kosten'), el);
  };
  const removeBtn = (label, onClick) => h('button', { class: 'btn small danger icon-only', type: 'button', 'aria-label': label, onclick: onClick }, icon('trash'));
  const select = (options, value, onChange) => h('select', { onchange: (e) => onChange(e.target.value) },
    options.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));

  function setHours(v) {
    printHours = v;
    state.depreciation.forEach((r) => { r.hours = v; });
    state.energy.forEach((r) => { r.hours = v; });
  }

  function addPrinterRows(p) {
    state.depreciation.push({ label: `Afschrijving ${p.name}`, printer_id: p.id, hours: printHours, price_per_hour: String(Math.round((Number(p.purchase_price) / Number(p.lifetime_hours)) * 10000) / 10000) });
    state.energy.push({ label: `Stroom ${p.name}`, tariff_id: defaultTariff ? defaultTariff.id : '', hours: printHours, kw: String(Number(p.power_kw)), price_per_kwh: defaultTariff ? String(Number(defaultTariff.price_per_kwh)) : '' });
  }

  function section(title, hint, rows, addButtons) {
    return h('div', { class: 'glass card' },
      h('h2', {}, title), hint ? h('p', { class: 'muted' }, hint) : null,
      h('div', { class: 'lines' }, rows), h('div', { class: 'row' }, addButtons));
  }

  function filamentSection() {
    costEls.filament = [];
    const rows = state.filament.map((r, i) => h('div', { class: 'line filament' },
      field('Rol', select([['', 'Handmatig'], ...spools.map((s) => [s.id, spoolLabel(s)])], r.spool_id, (v) => {
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
    const isPack = group === 'verpakking';
    const known = (r) => (r.packaging_id && packaging.some((p) => p.id === r.packaging_id) ? r.packaging_id : '');
    const rows = state.parts.map((r, i) => (r.group !== group ? null : h('div', { class: `line parts${isPack ? ' pack' : ''}` },
      isPack ? field('Verpakking', select([['', 'Handmatig'], ...packaging.map((p) => [p.id, `${p.name} · ${eur(p.price)}`])], known(r), (v) => {
        const p = packaging.find((x) => x.id === v);
        r.packaging_id = v;
        if (p) { r.label = p.name; r.unit = 'stuks'; r.unit_price = String(Number(p.price)); }
        touch(); redraw();
      })) : null,
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
      addPrinterRows(p);
      touch(); redraw();
    };
    const hoursInput = numberInput(printHours, (v) => {
      setHours(v);
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
        field('Printtijd (uren)', hoursInput, 'Geldt voor alle regels hieronder. Machinetijd (afschrijving en stroom) wordt altijd naar boven afgerond op hele uren.'),
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
      partsSection('verpakking', 'Verpakkingsmateriaal', packaging.length
        ? 'Kies een verpakking uit je lijst, of vul een regel zelf in (vulmateriaal, tape, labels…).'
        : 'Tip: maak je dozen aan onder Verpakking, dan kies je ze hier met één klik.'),
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

  // --- print file: upload, read, adopt -------------------------------------------------
  let fileMeta = null;
  let plateIndex = 0;
  let densities = {};
  let material = 'PLA';
  let fillPct = '40';
  let estimateTimer = null;
  const fileBox = h('div', { class: 'glass card stack' });

  const spoolFor = (type) => {
    const matches = spools.filter((sp) => type && (sp.material || '').toUpperCase() === type.toUpperCase());
    return matches.length === 1 ? matches[0] : null;
  };
  const filamentRow = (label, grams, type) => {
    const sp = spoolFor(type);
    return { spool_id: sp ? sp.id : '', label: sp ? [sp.brand, sp.colour].filter(Boolean).join(' ') : label, grams: String(grams), price_per_kg: sp ? perKg(sp) : '' };
  };

  // Takes grams and hours from the slicer into the calculation: filament lines (priced from the
  // matching roll), whole print hours, and a printer line with depreciation and energy.
  function adoptSliced(plate, auto = false) {
    state.filament = plate.filaments.map((f) => filamentRow(`${f.type} ${f.color}`.trim() || 'Filament', f.grams, f.type));
    const notes = [];
    let whole = null;
    if (plate.hours) {
      whole = Math.ceil(plate.hours);                 // machine time is charged in whole hours, rounded up
      setHours(String(whole));
      if (!state.depreciation.length) {
        if (printers.length) addPrinterRows(printers[0]);
        else notes.push('voeg een printer toe voor afschrijving en stroom');
      }
      if (!defaultTariff) notes.push('voeg een energietarief toe');
    }
    if (state.filament.some((r) => !r.price_per_kg)) notes.push('kies per filamentregel een rol voor de prijs');
    touch(); redraw();
    const what = `${fmt(plate.grams || 0, 1)} g${whole ? `, ${fmt(plate.hours, 2)} u → ${whole} u` : ''}`;
    toast(`${auto ? 'Automatisch overgenomen' : 'Overgenomen'}: ${what}.${notes.length ? ` Let op: ${notes.join('; ')}.` : ''}`, notes.length ? 'error' : 'info');
  }

  const autoToggle = () => h('label', { class: 'check' },
    h('input', { type: 'checkbox', checked: ctx.prefs.auto_adopt_file !== false,
      onchange: (e) => ctx.setPrefs({ auto_adopt_file: e.target.checked }) }),
    'Gram en uren automatisch overnemen bij het inlezen van een gesliced bestand');

  async function adoptEstimate() {
    try {
      const res = await api('GET', `/api/print-files/${fileMeta.id}/estimate?density=${densities[material]}&fill=${parseNum(fillPct)}`);
      state.filament = [filamentRow(`${material} (schatting uit ${fileMeta.filename})`, res.grams, material)];
      touch(); redraw();
      toast('Geschat gewicht overgenomen. Vul de printtijd zelf in.');
    } catch (e) { toast(e.message, 'error'); }
  }

  function drawFile() {
    const url = textInput(state, 'source_url', { type: 'url', inputmode: 'url', placeholder: 'https://makerworld.com/…', maxlength: 500 });
    const link = state.source_url && /^https?:\/\//i.test(state.source_url)
      ? h('a', { href: state.source_url, target: '_blank', rel: 'noopener noreferrer' }, 'Link openen') : null;
    const parts = [h('h2', {}, 'Printbestand en bron')];
    if (!fileMeta) {
      const input = h('input', { type: 'file', accept: '.stl,.3mf', onchange: async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        input.disabled = true; status.textContent = 'Bestand lezen…';
        const form = new FormData();
        form.append('file', file);
        try {
          fileMeta = await upload('/api/print-files', form);
          state.file_id = fileMeta.id; plateIndex = 0; touch();
          if (!Object.keys(densities).length) densities = await api('GET', '/api/print-files/materials');
        } catch (err) { toast(err.message, 'error'); }
        drawFile();
        const first = fileMeta && fileMeta.analysis.plates[0];
        if (first && ctx.prefs.auto_adopt_file !== false) adoptSliced(first, true);
      } });
      const status = h('p', { class: 'muted', role: 'status' });
      parts.push(field('3D-printbestand (STL of 3MF)', input,
        'Een gesliced 3MF uit Bambu Studio of Orca (“Export plate sliced file”) geeft de echte gram en printtijd. ' +
        'Een STL of ongesliced 3MF geeft alleen een schatting van het gewicht.'), autoToggle(), status);
    } else {
      const a = fileMeta.analysis;
      parts.push(h('div', { class: 'list-row' },
        h('div', {}, h('strong', {}, fileMeta.filename),
          h('p', { class: 'muted' }, `${fileMeta.size_bytes < 1048576 ? `${fmt(fileMeta.size_bytes / 1024, 0)} kB` : `${fmt(fileMeta.size_bytes / 1048576, 1)} MB`} · `, h('span', { class: `badge${a.exact ? '' : ' muted'}` }, a.exact ? 'Exact uit slicer' : 'Schatting uit model'))),
        h('div', { class: 'row' },
          h('a', { class: 'btn small', href: `/api/print-files/${fileMeta.id}/download` }, 'Downloaden'),
          h('button', { class: 'btn small', type: 'button', onclick: () => { fileMeta = null; state.file_id = null; touch(); drawFile(); } }, 'Ontkoppelen'))));
      if (a.plates.length) {
        const plate = a.plates[Math.min(plateIndex, a.plates.length - 1)];
        if (a.plates.length > 1) {
          parts.push(field('Plaat', h('select', { onchange: (e) => { plateIndex = Number(e.target.value); drawFile(); } },
            a.plates.map((pl, i) => h('option', { value: i, selected: i === plateIndex }, `Plaat ${pl.index}${pl.grams ? ` · ${fmt(pl.grams, 1)} g` : ''}`)))));
        }
        parts.push(h('dl', { class: 'stats' },
          h('div', {}, h('dt', {}, 'Printtijd'), h('dd', {}, plate.hours ? `${fmt(plate.hours, 2)} uur` : '—')),
          h('div', {}, h('dt', {}, 'Filament totaal'), h('dd', {}, plate.grams ? `${fmt(plate.grams, 1)} g` : '—'))),
        h('ul', { class: 'plain-list' }, plate.filaments.map((f) => {
          const dot = h('span', { class: 'dot', 'aria-hidden': 'true' });
          if (/^#[0-9a-f]{6}$/i.test(f.color)) dot.style.background = f.color;
          return h('li', { class: 'row' }, dot, `${f.type || 'Filament'} ${f.color}`.trim(), h('span', { class: 'muted' }, `· ${fmt(f.grams, 1)} g`));
        })),
        h('button', { class: 'btn primary', type: 'button', onclick: () => adoptSliced(plate) }, 'Gram en uren overnemen'),
        autoToggle());
      } else {
        const estimate = h('output', { class: 'cost' }, '…');
        const refresh = () => {
          clearTimeout(estimateTimer);
          estimateTimer = setTimeout(async () => {
            try {
              const res = await api('GET', `/api/print-files/${fileMeta.id}/estimate?density=${densities[material]}&fill=${parseNum(fillPct)}`);
              estimate.textContent = `≈ ${fmt(res.grams, 1)} g`;
            } catch (e) { estimate.textContent = e.message; }
          }, 150);
        };
        parts.push(h('dl', { class: 'stats' },
          h('div', {}, h('dt', {}, 'Volume'), h('dd', {}, `${fmt(a.volume_cm3, 1)} cm³`)),
          a.bbox_mm ? h('div', {}, h('dt', {}, 'Afmetingen'), h('dd', {}, `${a.bbox_mm.map((v) => fmt(v, 0)).join(' × ')} mm`)) : null),
        h('p', { class: 'muted' }, 'Dit bestand bevat geen slicer-gegevens, dus het gewicht is een schatting en de printtijd is onbekend. ' +
          'Slice het model en laad het 3MF-bestand voor exacte waarden.'),
        h('div', { class: 'two' },
          field('Materiaal', h('select', { onchange: (e) => { material = e.target.value; refresh(); } },
            Object.keys(densities).map((m) => h('option', { value: m, selected: m === material }, `${m} (${fmt(densities[m])} g/cm³)`)))),
          field('Effectieve vulling (%)', numberInput(fillPct, (v) => { fillPct = v; refresh(); }), 'Wanden + infill als deel van het massieve volume; ±40% is gebruikelijk.')),
        h('div', { class: 'row' }, estimate, h('button', { class: 'btn primary', type: 'button', onclick: adoptEstimate }, 'Schatting overnemen')));
        refresh();
      }
    }
    parts.push(field('Link naar het model (optioneel)', url, 'Bijvoorbeeld de MakerWorld-pagina. Wordt alleen als link bewaard; de app leest die pagina niet uit.'), link);
    fileBox.replaceChildren(...parts);
  }

  if (state.file_id) {
    Promise.all([api('GET', `/api/print-files/${state.file_id}`), api('GET', '/api/print-files/materials')])
      .then(([meta, dens]) => { fileMeta = meta; densities = dens; drawFile(); })
      .catch(() => { state.file_id = null; drawFile(); });
  } else {
    api('GET', '/api/print-files/materials').then((d) => { densities = d; }).catch(() => {});
  }
  drawFile();

  const nameInput = textInput(state, 'name', { required: true, maxlength: 120, placeholder: 'bijv. USW-Ultra 10-inch rack-mount' });
  const marginInput = numberInput(state.margin_pct, bind(state, 'margin_pct'), { class: 'private' });
  const vatInput = numberInput(state.vat_pct, bind(state, 'vat_pct'), { list: 'vat-presets' });
  const vatPresets = h('datalist', { id: 'vat-presets' }, ['0', '9', '21'].map((v) => h('option', { value: v })));
  const roundingSelect = select(ROUNDINGS, state.price_rounding, (v) => { state.price_rounding = v; touch(); });
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
          field('Project', nameInput),
          h('div', { class: 'three' },
            field('Marge (%)', marginInput, 'Optioneel. Met afronding is dit het minimum.'),
            field('BTW (%)', vatInput, 'Over de verkoopprijs. 0 = geen btw. Je inkoopprijzen hierboven zijn excl. btw.'),
            field('Prijs incl. btw afronden', roundingSelect, 'De marge wordt zo nodig iets verhoogd.')),
          vatPresets,
          field('Notities', notes)),
        fileBox,
        sections),
      h('aside', { class: 'glass card summary', 'aria-label': 'Kostprijs' },
        h('div', { class: 'row between' }, h('h2', {}, 'Kostprijs'), blurToggle(ctx)), totals, roundNote, calcError,
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
