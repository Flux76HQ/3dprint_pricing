# Shared filament library

`filaments.json` is the filament library in the format of *Settings → Filaments → Export (JSON)*. An installation reads it with the
**Sync** button (the address is `FILAMENT_LIBRARY_URL`, see `.env.example`): filaments that are missing are added, known ones (the same SKU,
barcode or filament ID, or the same brand/material/type/colour/weight/diameter/refill) get what the file says for the fields it lists, and nothing is
ever deleted. A `price` is a reference price excl. VAT and optional.

**Contribute from the app:** *Settings → Filaments → Contribute to the central library* lists the filaments of your library and of your rolls that this file lacks, and the ones it has but with blank fields that you have filled in (a completion only fills blanks and never overwrites)
(the same SKU, barcode or filament ID, or the same name, weight and diameter counts as the same filament), lets you choose, and opens GitHub with an
issue filled in (form `.github/ISSUE_TEMPLATE/05-filament-library.yml`). Notes and everything about your rolls stay out. A contribution of more than about 20 filaments does not fit in a GitHub address: the app then shows the JSON to copy and opens the (empty) form to paste it into. You submit the issue yourself;
the workflow `library-contribution` checks it with the app's own rules (`scripts/apply_library_contribution.py`) and opens a pull request into `beta` that
only **adds** filaments and fills blank fields of existing ones (nothing that is filled in is ever changed this way), which a maintainer reviews. The button only shows while `FILAMENT_LIBRARY_URL` is the
default, because the issue form belongs to this repository. Issue forms and workflows that run on `issues` are only read from the repository's **default branch**, so that must be `beta` (Settings → Branches) or the form and the workflow only work after `beta` has been promoted to `main`.

By hand: export your own library, trim it to the entries worth sharing, and send a pull request. Entries need at least
`brand` and `roll_weight_g`; `backend/tests/test_filament_library.py` checks that the file stays a valid library.
