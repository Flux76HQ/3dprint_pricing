# Simple Icons

The brand marks in `../../js/brands.js` come from [Simple Icons](https://simpleicons.org/) (npm package `simple-icons`, version **16.38.1**, licence CC0-1.0, see `LICENSE`).
Only the path of each mark is used, unmodified (24 x 24, filled): `icons/etsy.svg` and `icons/vinted.svg`. The marks are trademarks of their owners and are shown only to say where a link
goes (see `DISCLAIMER.md`). Marktplaats and bol.com are not in the set.

To update or add a mark: `npm pack simple-icons@<version>`, unpack it, copy the `d` of the `<path>` in `icons/<name>.svg` into `BRANDS` as `'brand-<name>'`, add the kind to `LINK_ICONS` in
`../../js/links.js` if it is a new one, and change the version above and in `brands.js`.
