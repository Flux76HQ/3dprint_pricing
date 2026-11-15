// The top of Settings -> Koppelingen: where the filament and the printers are read from (backend/app/sources.py). One source at a time; below the choice
// only the cards of the chosen source are shown. The other sources keep their settings on the server and are not used until they are chosen again.
import { api } from './api.js';
import { t } from './i18n.js';
import { bambuCloudCard } from './bambu-cloud.js';
import { haspelsyncCard } from './haspelsync.js';
import { spoolmanCard } from './spoolman.js';
import { field, fill, h, toast } from './ui.js';

// A source the server knows -> its name, what choosing it means, and the cards of its connections. Another printer set-up is a line here, an entry in
// `SOURCES` on the server and its two texts; a source without a line here is offered by its id and has no cards.
const SOURCES = {
  spoolman: { name: () => t('sources.spoolman'), hint: () => t('sources.spoolman_hint'), cards: () => [spoolmanCard(undefined, { configure: true }), haspelsyncCard()] },
  bambu: { name: () => t('sources.bambu'), hint: () => t('sources.bambu_hint'), cards: () => [bambuCloudCard()] },
};
const known = (id) => SOURCES[id] || { name: () => id, hint: () => '', cards: () => [] };

/** The choice of the source, then the cards of the chosen one. */
export function sourceCards() {
  const choice = h('div', { class: 'glass card stack' });
  const cards = h('div', { class: 'stack' });

  async function draw() {
    let state;
    try { state = await api('GET', '/api/sources'); } catch { return; }
    const select = h('select', { disabled: !state.can_change, onchange: async (e) => {
      const wanted = e.target.value;
      select.disabled = true;
      try {
        await api('PUT', '/api/sources', { source: wanted });
        toast(t('sources.changed', { name: known(wanted).name() }));
      } catch (err) { toast(err.message, 'error'); }
      draw();
    } }, state.sources.map((s) => h('option', { value: s.id, selected: s.id === state.source }, known(s.id).name())));
    fill(choice, h('h2', {}, t('sources.title')), h('p', { class: 'muted' }, t('sources.intro')),
      field(t('sources.label'), select, known(state.source).hint()),
      state.chosen ? null : h('p', { class: 'hint' }, t('sources.derived')));
    fill(cards, ...known(state.source).cards());
  }

  draw();
  return h('div', { class: 'stack' }, choice, cards);
}
