# Shared filament library

`filaments.json` is the filament library in the format of *Settings → Filaments → Export (JSON)*. An installation reads it with the
**Sync** button (the address is `FILAMENT_LIBRARY_URL`, see `.env.example`): filaments that are missing are added, known ones (the same SKU,
barcode or filament ID, or the same brand/material/type/colour/weight/diameter/refill) get what the file says for the fields it lists, and nothing is
ever deleted. A `price` is a reference price excl. VAT and optional.

**Contribute from the app:** *Settings → Filaments → Contribute to the central library* lists the filaments of your library that this file lacks
(the same SKU, barcode or filament ID, or the same name, weight and diameter counts as the same filament), lets you choose, and opens GitHub with an
issue filled in (form `.github/ISSUE_TEMPLATE/05-filament-library.yml`). Notes and everything about your rolls stay out. You submit the issue yourself;
the workflow `library-contribution` checks it with the app's own rules (`scripts/apply_library_contribution.py`) and opens a pull request into `beta` that
only **adds** filaments (an existing entry is never changed this way), which a maintainer reviews. The button only shows while `FILAMENT_LIBRARY_URL` is the
default, because the issue form belongs to this repository.

By hand: export your own library, trim it to the entries worth sharing, and send a pull request. Entries need at least
`brand` and `roll_weight_g`; `backend/tests/test_filament_library.py` checks that the file stays a valid library.
