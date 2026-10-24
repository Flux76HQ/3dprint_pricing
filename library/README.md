# Shared filament library

`filaments.json` is the filament library in the format of *Settings → Filaments → Export (JSON)*. An installation reads it with the
**Sync** button (the address is `FILAMENT_LIBRARY_URL`, see `.env.example`): filaments that are missing are added, known ones (the same SKU,
barcode or filament ID, or the same brand/material/type/colour/weight/diameter/refill) get what the file says for the fields it lists, and nothing is
ever deleted. A `price` is a reference price excl. VAT and optional.

Add filaments by exporting your own library, trimming it to the entries worth sharing, and sending a pull request. Entries need at least
`brand` and `roll_weight_g`; `backend/tests/test_filament_library.py` checks that the file stays a valid library.
