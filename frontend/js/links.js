import { t } from './i18n.js';
import { h, icon } from './ui.js';

// What a link looks like, for a 3D model and for a customer: a button that opens in a new tab, with the icon of its kind in front of its name. Used by `projects.js` and `customers.js`.

/** Whether `url` is an address a link may have: the same rule as the server's (`api.URL`), so that what is turned into a link can never run anything (javascript:, data:). */
export const isLink = (url) => /^https?:\/\/\S+$/i.test(String(url || '').trim());

// The icon of each kind of link: the mark of the shop where there is one (`brands.js`), else an icon of Material Design (`mdi.js`). Every kind the server knows has one (`test_file_refs.py`).
export const LINK_ICONS = { model: 'cube-outline', marktplaats: 'storefront-outline', bol: 'shopping-outline', etsy: 'brand-etsy', vinted: 'brand-vinted', webshop: 'web', other: 'link-variant' };
export const linkIcon = (kind) => icon(LINK_ICONS[kind] || LINK_ICONS.other);

// Something that is not an address is never given an `href`: it is shown, but it does not go anywhere.
const target = (url) => (isLink(url) ? { href: String(url).trim(), target: '_blank', rel: 'noopener noreferrer', title: String(url).trim() } : { title: String(url || '') });

/** A link as a button that opens in a new tab: the icon of its kind and its name. `{ kind, name, url }` */
export const linkButton = ({ kind, name, url }) => h('a', { class: 'link-btn', ...target(url) }, linkIcon(kind), h('span', {}, name));

/** The same, small: for a tile or a row of a list. */
export const linkChip = ({ kind, name, url }) => h('a', { class: 'link-chip', ...target(url) }, linkIcon(kind), h('span', {}, name));

/** A link in an editor. While it is shown it is a button that opens it, with the icons for editing and removing it behind it; while it is edited the button gives way to its fields.
 *  A link that is empty, or that is not an address, is always edited: it can never be shown as a button that goes nowhere.
 *    show()       the button            fields()   the fields (an array of elements)       editClass   the class of the row while it is edited
 *    filled()     is there anything     ok()       is what is typed an address             removable() whether to offer removing it (it may be nothing yet)
 *    remove()     takes it away         editing    start with the fields open               onToggle(open)  told when the person opens or closes them */
export function linkRow({ show, fields, filled, ok, remove, removable = () => true, editClass = 'link-edit', editing = false, onToggle = () => {} }) {
  const root = h('div');
  const actions = h('div', { class: 'row-actions' });
  const refused = h('p', { class: 'hint error', role: 'alert', hidden: true }, t('link.bad_address'));
  let open = editing;
  const action = (name, label, onclick, extra = '') => h('button', { class: `btn tool icon-only${extra}`, type: 'button', title: label, 'aria-label': label, onclick }, icon(name));

  // What can be done depends on what is typed (a check once there is something, removing only when there is something to remove), so this is drawn again while typing.
  function drawActions() {
    const buttons = [];
    if (open && filled()) buttons.push(action('check', t('link.done'), close));
    if (!open) buttons.push(action('pencil-outline', t('link.edit'), () => { open = true; onToggle(true); draw(true); }));
    if (removable()) buttons.push(action('delete-outline', t('file.link_remove'), () => { remove(); open = true; draw(); }, ' danger'));
    actions.replaceChildren(...buttons);
  }

  function draw(focus = false) {
    open = open || !(filled() && ok());
    root.className = open ? editClass : 'link-row';
    refused.hidden = true;
    drawActions();
    root.replaceChildren(...(open ? [...fields(), actions, refused] : [show(), actions]));
    if (focus) (open ? root.querySelector('input, select') : root.querySelector('.row-actions .btn'))?.focus();
  }

  function close() {
    if (!ok()) {                                                    // not an address yet: stay, and say so
      const input = root.querySelector('input[type=url]');
      refused.hidden = false;
      input?.setAttribute('aria-invalid', 'true');
      input?.focus();
      return;
    }
    open = false;
    onToggle(false);
    draw(true);
  }

  root.addEventListener('input', () => {
    if (!open) return;
    drawActions();
    if (!refused.hidden && ok()) { refused.hidden = true; root.querySelector('input[aria-invalid]')?.removeAttribute('aria-invalid'); }    // an address takes the remark back
  });
  draw();
  return root;
}
