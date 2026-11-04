import { api } from './api.js';
import { t } from './i18n.js';
import { colourOf, spoolIcon } from './filament-ui.js';
import { cameraAvailable, cameraPanel } from './scanner.js';
import { enhanceDialog, fill, fmt, h, icon, spoolName, toast } from './ui.js';

// Adding a delivery of rolls by scanning them one after the other: with the camera (it keeps reading) or a hardware scanner (it types
// the code and presses Enter). Every scan is one roll, so scanning a barcode again adds a roll to its line. What a roll is made of (the
// newest roll with that barcode, else the filament library's entry with it) is decided by the server, for the list as for adding
// (`/api/spools/from-barcode`, `/api/spools/bulk`), so what is listed is what is made. A barcode that neither knows is filled in once
// with the roll form; the other rolls with that barcode then follow from it.
const SAME_ROLL_MS = 1500;      // the camera reads a code several times a second: it counts again once it has been out of view this long
const num = (v) => (v === '' || v == null ? '' : String(v).replace(',', '.'));

/** Opens the scan list. `newRoll(code, saved)` opens the roll form for a new roll with that barcode and returns its dialog (it calls
    `saved` once the roll is saved); `reload` refreshes the page behind once rolls were added. */
export function openBulkScan({ newRoll, reload }) {
  const lines = [];             // { code, count, state: 'loading' | 'known' | 'unknown' | 'error', roll, source, stock, price, el }
  let changed = false;          // rolls were saved (by the roll form or by adding the list): the page behind is refreshed on closing
  let saving = false;
  let seq = 0;

  const status = h('p', { class: 'muted scan-status', role: 'status' });
  const list = h('div', { class: 'scan-list' });
  const empty = h('p', { class: 'muted' }, t('bulk.empty_list'));
  const blocked = h('p', { class: 'notice warn', hidden: true }, t('bulk.blocked'));
  const error = h('p', { class: 'error', role: 'alert', hidden: true });
  const library = h('input', { type: 'checkbox', class: 'toggle', role: 'switch', checked: true });
  const submit = h('button', { class: 'btn primary', type: 'button', onclick: () => save() });
  const total = () => lines.reduce((n, line) => n + line.count, 0);

  // Typing, or a hardware scanner (which types the code and presses Enter).
  const input = h('input', { type: 'text', id: 'bulk-code', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', enterkeyhint: 'done',
    placeholder: t('barcode.placeholder'), onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); take(); } } });
  function take() {
    const code = input.value.trim();
    input.value = '';
    if (code) add(code);
  }

  // The camera keeps reading until it is turned off; the same code only counts again after it was out of view for a moment.
  const seen = new Map();
  const camera = cameraPanel((code) => {
    const now = Date.now();
    const before = seen.get(code);
    seen.set(code, now);
    if (before !== undefined && now - before < SAME_ROLL_MS) return;
    add(code);
    camera.frame.classList.add('hit');
    setTimeout(() => camera.frame.classList.remove('hit'), 350);
  });
  const cameraBox = h('div', { class: 'stack scan-camera', hidden: true }, camera.frame, camera.status, camera.help, h('div', { class: 'row' }, camera.retry));
  const cameraLabel = h('span', {});
  const cameraButton = h('button', { class: 'btn', type: 'button', 'aria-pressed': 'false', onclick: () => setCamera(cameraBox.hidden) }, icon('scan'), cameraLabel);
  function setCamera(on) {
    cameraBox.hidden = !on;
    cameraButton.setAttribute('aria-pressed', String(on));
    cameraLabel.textContent = on ? t('bulk.camera_off') : t('bulk.camera_on');
    if (on) camera.start(); else camera.stop();
  }
  setCamera(false);

  function add(code) {
    let line = lines.find((l) => l.code === code);
    const fresh = !line;
    if (line) {
      line.count += 1;
      lines.splice(lines.indexOf(line), 1);
    } else {
      line = { id: ++seq, code, count: 1, state: 'loading', price: '', el: h('article', { class: 'scan-item' }) };
    }
    lines.unshift(line);                                        // the last one scanned on top, where it is seen
    list.prepend(line.el);
    if (fresh) look(line); else draw(line);
    announce(line);
    line.el.classList.remove('hit');
    void line.el.offsetWidth;                                   // restart the highlight when the same line is scanned again
    line.el.classList.add('hit');
  }

  function remove(line) {
    lines.splice(lines.indexOf(line), 1);
    line.el.remove();
    refresh();
  }

  async function look(line) {
    line.state = 'loading';
    draw(line);
    try {
      const found = await api('GET', `/api/spools/from-barcode?barcode=${encodeURIComponent(line.code)}`);
      Object.assign(line, { roll: found.roll, source: found.source, stock: found.stock, state: found.roll ? 'known' : 'unknown' });
      if (found.roll && !line.priceTyped) line.price = found.roll.price ?? '';
    } catch (e) {
      Object.assign(line, { state: 'error', error: e.message });
    }
    if (!lines.includes(line)) return;                          // taken off the list meanwhile
    draw(line);
    if (lines[0] === line) announce(line);
  }

  function announce(line) {
    const name = line.roll ? spoolName(line.roll, ' · ') : line.code;
    status.textContent = {
      loading: t('bulk.looking', { code: line.code }),
      known: t('bulk.scanned', { name, n: line.count }),
      unknown: t('bulk.scanned_unknown', { code: line.code }),
      error: t('bulk.lookup_failed', { code: line.code }),
    }[line.state];
  }

  // The roll form for a barcode that is not known yet: it saves one roll, and the rest of the line is then made like that one.
  function fillIn(line) {
    const cameraWasOn = !cameraBox.hidden;
    if (cameraWasOn) setCamera(false);                          // nothing is scanned behind the form
    const form = newRoll(line.code, () => {
      changed = true;
      line.count -= 1;
      if (line.count < 1) remove(line); else look(line);
      status.textContent = t('bulk.form_saved', { code: line.code });
    });
    form.addEventListener('close', () => { if (cameraWasOn && dialog.open) setCamera(true); });
  }

  function draw(line) {
    const roll = line.roll;
    const name = roll ? spoolName(roll, ' · ') : t('bulk.unknown_title');
    const count = h('span', { class: 'scan-count' }, String(line.count));
    const less = h('button', { class: 'btn small', type: 'button', disabled: line.count <= 1, 'aria-label': t('bulk.less', { name }),
      onclick: () => { line.count -= 1; draw(line); } }, '−');
    const more = h('button', { class: 'btn small', type: 'button', 'aria-label': t('bulk.more', { name }),
      onclick: () => { line.count += 1; draw(line); } }, '+');
    const drop = h('button', { class: 'btn small danger', type: 'button', 'aria-label': t('bulk.remove', { name }), onclick: () => remove(line) }, icon('trash'));
    const priceId = `bulk-price-${line.id}`;
    const price = line.state === 'known' ? h('div', { class: 'scan-price' }, h('label', { for: priceId }, t('filament.roll_price')),
      h('input', { type: 'text', id: priceId, inputmode: 'decimal', autocomplete: 'off', value: line.price ?? '', required: true,
        oninput: (e) => { line.price = e.target.value; line.priceTyped = true; } })) : null;
    const about = {
      loading: t('bulk.looking', { code: line.code }),
      known: [t('filament.barcode_note', { code: line.code }), t(line.source === 'library' ? 'bulk.from_library' : 'bulk.from_roll'),
        roll ? `${fmt(roll.roll_weight_g, 0)} g` : null, roll?.material].filter(Boolean).join(' · '),
      unknown: t('filament.barcode_note', { code: line.code }),
      error: line.error,
    }[line.state];
    fill(line.el,
      h('div', { class: 'item-head' },
        line.state === 'known' ? spoolIcon(colourOf(roll), 30) : icon('scan'),
        h('div', { class: 'grow' }, h('h3', {}, name), h('p', { class: 'muted' }, about),
          line.state === 'known' && line.stock?.roll_count ? h('p', { class: 'muted' }, t('bulk.in_stock', { n: line.stock.roll_count })) : null)),
      line.state === 'unknown' ? h('div', { class: 'notice warn stack' }, h('p', {}, t('bulk.unknown_hint', { n: line.count })),
        h('div', { class: 'row' }, h('button', { class: 'btn small primary', type: 'button', onclick: () => fillIn(line) }, t('bulk.fill_in')))) : null,
      line.state === 'error' ? h('div', { class: 'row' }, h('button', { class: 'btn small', type: 'button', onclick: () => look(line) }, t('scanner.retry'))) : null,
      h('div', { class: 'row scan-controls' }, price, h('div', { class: 'row nowrap scan-stepper', role: 'group', 'aria-label': t('bulk.count_label') }, less, count, more), drop));
    refresh();
  }

  // The summary and the button: nothing is added while a barcode is still being looked up, is unknown or could not be looked up.
  function refresh() {
    const n = total();
    empty.hidden = lines.length > 0;
    const open = lines.some((line) => line.state !== 'known');
    blocked.hidden = !lines.some((line) => line.state === 'unknown' || line.state === 'error');
    submit.textContent = n ? t('bulk.add', { n }) : t('bulk.add_none');
    submit.disabled = saving || !n || open;
  }

  async function save() {
    saving = true;
    refresh();
    error.hidden = true;
    try {
      const done = await api('POST', '/api/spools/bulk', {
        items: lines.map((line) => ({ barcode: line.code, count: line.count, price: num(line.price) })),
        add_to_library: library.checked,
      });
      lines.length = 0;                                          // added: closing has nothing left to lose
      changed = true;
      dialog.close();
      toast(t('bulk.done', { n: done.created }));
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
    } finally {
      saving = false;
      refresh();
    }
  }

  const dialog = enhanceDialog(h('dialog', { class: 'glass sheet scan-sheet' },
    h('h2', {}, t('bulk.title')),
    h('p', { class: 'muted' }, t('bulk.intro')),
    h('div', { class: 'field' }, h('label', { for: 'bulk-code' }, t('filament.barcode')),
      h('div', { class: 'row nowrap' }, input, h('button', { class: 'btn', type: 'button', onclick: () => { take(); input.focus(); } }, t('bulk.add_code')))),
    cameraAvailable() ? h('div', { class: 'row' }, cameraButton) : null,
    cameraBox,
    status,
    empty,
    list,
    blocked,
    h('div', { class: 'field' }, h('label', { class: 'check' }, library, t('library.also_add')), h('p', { class: 'hint' }, t('library.also_add_hint'))),
    error,
    h('div', { class: 'row end' },
      h('button', { class: 'btn', type: 'button', onclick: () => dialog.requestClose() }, t('common.cancel')),
      submit)),
  { dirty: () => lines.length > 0, message: () => t('bulk.discard', { n: total() }) });
  dialog.addEventListener('close', () => {
    camera.stop();
    dialog.remove();
    if (changed) reload();
  });
  refresh();
  document.body.append(dialog);
  dialog.showModal();
  // On a phone the camera is the scanner, so it starts at once; elsewhere a hardware scanner is more likely and the camera waits to be asked.
  if (cameraAvailable() && ['ios', 'android'].includes(document.documentElement.getAttribute('data-platform'))) setCamera(true);
}
