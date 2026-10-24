# Shared filament library

`filaments.json` is the filament library in the format of *Settings → Filaments → Export (JSON)*. An installation reads it with the
**Sync** button (the address is `FILAMENT_LIBRARY_URL`, see `.env.example`): filaments that are missing are added, known ones (matched on
SKU, else barcode, else filament ID, else brand/material/type/colour/refill) get what the file says for the fields it lists, and nothing is
ever deleted. Keep prices out of it: they differ per shop and per day.

Add filaments by exporting your own library, trimming it to the entries worth sharing, and sending a pull request. Entries need at least
`brand` and `roll_weight_g`; `backend/tests/test_filament_library.py` checks that the file stays a valid library.
