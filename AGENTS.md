# AGENTS.md — Working conventions for AI agents

Working conventions for **any** AI coding agent operating in this repository —
Claude Code, GitHub Copilot, OpenAI Codex / ChatGPT, or anything else. This file
is **canonical**: when a client-specific file disagrees with it, this file wins.

This project adopts the Flux76 baseline in
[`shared/guidelines/project-baseline.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/project-baseline.md)
(repository `Flux76HQ/App-Guidance`), which is enforceable and remains the source of truth for
*what* is required. This file describes how to *work* here.

## Client surfaces

| Client | Entry file it reads automatically | Client-specific extras |
|---|---|---|
| OpenAI Codex / ChatGPT | `AGENTS.md` (this file) | none |
| Claude Code | [`CLAUDE.md`](CLAUDE.md) | none |
| GitHub Copilot | [`.github/copilot-instructions.md`](.github/copilot-instructions.md) | none |

`CLAUDE.md` and `.github/copilot-instructions.md` are deliberately thin: they add
only what is specific to their client and defer to this file for everything else.
A rule stated twice is a rule that will drift, and the stale copy reads exactly
as authoritative as the current one.

## About this repository

3D Print Pricing is a self-hosted **PWA with a backend** for a 3D-print business: it calculates
the cost price of a print (filament, parts, charger, printer depreciation, energy) and keeps the
inventory those prices come from (filament rolls, printers, energy tariffs). A few people can sign in
(the owner who set it up, other administrators and regular users, section 6f), with passkeys or a
password. It is still a single-tenant app: one business, so there is no per-user data scoping and
everything people make is shared. If that ever changes, every query in `backend/app/api.py` needs a user filter first.

Stack: Flask + Gunicorn, SQLite (one file, WAL mode), a no-build vanilla-JS frontend served by the same
process, Docker Compose. Layout: `backend/` (API, auth, migrations, tests), `frontend/` (static
PWA), `deploy/` (container entrypoint), `scripts/` (repo tooling), `homeassistant/` (the Home Assistant app, section 6g).

## 1. Before you change code

- Money is `Decimal` in `backend/app/calc.py`; each line is rounded to cents *before* summing so
  the lines on screen add up to the total. Never use floats for money, and never compute totals in
  the frontend: it displays what `/api/calculate` returns.
- Machine time (depreciation and energy lines) is always charged in whole hours, rounded up
  (`whole_hours` in `calc.py`); this is a business rule, not a display choice, so it lives in the
  calculator and not in the frontend. VAT is charged on the selling price (cost + margin); purchase
  prices are entered excl. VAT. With a price rounding, the VAT-inclusive price is authoritative:
  round up, take the VAT out, and the margin becomes a minimum (the loop in `calc.price_from_cost` exists
  because cent-rounding the VAT can otherwise land a cent under that minimum).
- In a calculation filament is chosen per **kind in stock** (`stock.key_of`, the groups of `GET /api/spools/stock` with their `spool_ids`), never per roll: the editor lists a kind once, a line still stores one `spool_id` (the roll nearest to empty, whose price it copies) and means its kind, `book_stock` takes what that roll lacks from the other rolls of the kind, and the editor warns when the lines ask for more of a kind than there is. A sliced file's filaments are matched to a kind by material and nearest colour (`stockFor` in `projects.js`: the difference as the eye sees it, CIE L*a*b*, at most `SAME_COLOUR`; a line keeps the file's `colour` and shows it, or its kind's, as an icon); no near colour means the line stays manual, never a guess.
- A saved project stores the prices as they were when saved (`projects.data`). Do not make a
- Packaging, parts and accessories (`packaging_items`, `part_items`, `accessory_items`) are price lists a calculation line copies from, except packaging: that is added on the order (a normal line at cost price, margin 0, from `Verpakking toevoegen` in the order editor), because what is needed depends on the order, not on the model. The calculation editor no longer adds `verpakking` lines; one saved with them keeps them (the calculator still sums the `verpakking` group, so no saved price changes) and shows the section until they are removed. The line's `group` (`verpakking`, `onderdeel`, `oplader`) is what the calculator sums on and is stored in saved projects, so it is never renamed even though `oplader` is shown as *Accessoires*; the link (`packaging_id`, `part_id`, `accessory_id`) is only a convenience, an order line made from a calculation puts that calculation's `oplader` lines on lines of their own with `optional` set, at cost price (they are billed, but the invoice lists `optional` lines apart, after the others), and a unit is `stuks`, `m` or `g` (price per kg) everywhere.
  project read live prices from spools, printers or tariffs: that rewrites history.
- `backend/tests/test_calc.py` pins the owner's real spreadsheet example (total 2,74). If that test
  has to change, the calculation changed: say so in the pull request.
- WebAuthn is checked by the open-source `webauthn` package (py_webauthn); `backend/app/webauthn.py` is a thin adapter that
  fixes the policy (ES256 only, user presence required, user verification not, because password managers such as Enpass
  do not report it) and translates the library's errors. Do not write ceremony checks ourselves (baseline §19). Do not widen what is accepted
  without a test that fails first.
- A calculation keeps two kinds of print files apart: `projects.calc_files` (migration 0009, a list of file ids, validated by `api.project_calc_files`; its first is also kept in `file_id` for older clients and backups) are the files the filament is worked out from (a sliced file gives exact grams and hours; an object printed as several jobs has one per job, and the editor adds them up), `projects.models` (migration 0008, a list of `{file_id, label}`, validated by `api.project_models`, at most `MAX_MODELS`) are the 3D models of the object, one per part, for the viewer and the pictures only. A file is kept while either names it (`files._purge_orphans`). A saved view of a model is a `source` image with `origin = 'model'` and a `model_ref` (`<file id>` or `<file id>:<plate>`, a name and not a foreign key: the view stays when the file goes); every saved view and every uploaded photo is kept (migration 0011; at most `MAX_MODEL_VIEWS` and `MAX_PHOTOS`). Which of them go to the image model is `project_images.selected` (`PUT /project-images/<id>/selected`): the first picture by default, at most `MAX_SELECTED`, and `ai_images._sent` is the one place that says what is sent (with nothing chosen: the first picture, never none). Any picture can be the cover, the photos and the views too. One build plate of a slicer project is `?plate=N` on the mesh and preview routes (`printfile._slicer_plates`).
- Uploaded print files are untrusted. All parsing goes through `backend/app/printfile.py`
  (defusedxml, size caps, readable `PrintFileError`s); never open an upload with another parser. A
  sliced 3MF is exact, geometry is only an estimate, and print time is never derived from geometry.
  Test with the synthetic fixtures in `backend/tests/printfiles.py`; a real slicer file is the
  final check, since the 3MF/slice_info layout is the slicer's, not ours.
- All data lives in one host folder, `DATA_PATH`: the database is the SQLite file `DATA_PATH/db/printpricing.sqlite3` and the uploads are in `DATA_PATH/uploads` (the app sees `DATA_PATH` as `/data`; `DATA_PATH/postgres` is the database of the releases before SQLite, which `db` still mounts until the importer goes). They are plain folders, never Docker volumes (`test_deploy_layout.py` fails on a named volume or a changed mount), and `DATA_PATH` is an absolute folder of the Docker host, never `./data` (a relative path is resolved by the tool that starts the stack; under Dockhand on Unraid it landed in the host's RAM disk). `docker-compose.yml` requires it, `deploy/entrypoint.sh` warns about a relative one, `scripts/init_env.py` refuses one, and `scripts/migrate_data.sh` (run by `scripts/update.sh`) moves data that sits in another folder than `DATA_PATH`; it never deletes the old folder and refuses when `DATA_PATH/postgres` already holds a database (it reads where the `db` service keeps it, so it goes with that service). `deploy/migrate_uploads.sh` moves the uploads of releases before this layout (`DATA_PATH/app/uploads`) on start; never remove it while such installations may exist, and never `chown` the whole of `/data` (it is the host's folder and holds `db/`, and an old `postgres/`); only `UPLOAD_DIR` and the database folder are handed to `app`. `scripts/update.sh` copies the database to `DATA_PATH/backups` before an update (SQLite's online backup through `backend/backup_db.py`; never a plain `cp` of a file that is being written, the newest data is in the `-wal` file). Changing where the database lives needs a move of the existing folder first: a different path makes a running installation start on an empty database, which is why `migrate.py` refuses to start when it finds an old `DATA_PATH/postgres` and nothing to import it with.
- Uploads live under `UPLOAD_DIR` (`/data/uploads`, i.e. `DATA_PATH/uploads`), never in the
  image. Stored names are generated; the original filename is only a download name.
- Every page starts with a `.page-head` header: it is the sticky title bar (safe-area aware on phones) and holds the page's main button, so keep a page's intro text outside it (`.page-intro`). `html, body` use `overflow-x: clip`, not `hidden`: `hidden` makes the body a scroll container and breaks `position: sticky`. A roll's colour is `filament_spools.colour_hex` (`#rrggbb`, empty = guess from the colour name in `filament-ui.js`).
- The screenshots in `docs/assets/` (shown by `README.md` and `README.nl.md`) are generated, never edited by hand: `python scripts/generate_screenshots.py` (needs `playwright` and `pillow`; `CHROMIUM_PATH` if the browser is elsewhere) starts a throwaway app on a scratch database with Dutch demo data and re-takes them as desktop, iPhone (iOS-style bar) and Android (Android-style bar) frames. Re-run it, and commit the PNGs, when a change alters how a screen looks; it never touches a real installation.
- Navigation icons are the Material Design Icons (`frontend/js/mdi.js`, licence in `frontend/vendor/mdi/`); the bottom bar has two styles (`html[data-nav]`: `ios` floating glass: the slider value 0-100 is turned into plain `--nav-alpha` / `--nav-blur` values by `applyNavGlass` (`ui.js`, mirrored in `theme-boot.js`) because Safari drops a `backdrop-filter` or colour that has `calc()` / `color-mix()` around a variable, or `android`), both set from the account preferences `navbar_style` (`auto` = the device's: `theme-boot.js` sets `data-platform` before the first paint, `navStyle()` in `ui.js` resolves it) / `navbar_glass` and cached for `theme-boot.js`.
- Customers (`backend/app/customers.py`, migration 0014) own the klantnummer (unique, case-insensitive; empty = next free whole number, claimed in a transaction, which holds the database's write lock). An order always has a `customer_id` (required by the API) and keeps a copy of the customer's details; saving the order or editing the customer refreshes that copy, except in orders that already have an invoice number. A customer with orders cannot be deleted. Backups carry customers; an older file without them gets customers derived from its orders.
- Margin and rounding are decided per order, not in the calculation (the calculation editor saves `price_rounding` as `none`; the account preference `price_rounding` is
  only the default for new orders). An order has `price_rounding`; a line made from a calculation keeps that calculation's cost price (excl. VAT) and has its own
  `margin_pct`, and its price per piece is derived on the server by `calc.price_from_cost` (the same code the calculation uses), never in the browser. A line without a
  cost price (a free line, or one from before migration 0017) keeps its typed price. A loose accessory (picked from `accessory_items` in the order editor, no calculation) is an `optional` line with its cost price and margin 0; the sync button
  next to a model line re-reads the calculation's cost price in the browser (`modelLines`, the same rule that added it) and only changes the line's `cost_price`, never its margin, VAT or quantity.
- Orders (`backend/app/orders.py`) keep the price per piece *including* VAT (derived as above, or copied/typed when the line has no cost price), and
  work out the totals on the server per VAT rate (`compute_totals`); the browser only displays them. An invoice number
  (a template in the business preferences, default `{JJJJ}-{NNNN}`, see `invoice_numbers.py`; counted per year in `invoice_counters`, or under year 0 when the template has no year) is claimed atomically once per order and never reused. Invoice templates (`invoice_docs.py`,
  `invoice_template.py`) are untrusted uploads like print files: capped in size and unpacked size, parsed only by `python-docx` / `pypdf`,
  stored under `UPLOAD_DIR`, and part of the backup together with orders and calculation numbers. The invoice logo (`invoice_logo.py`) is an upload too (PNG/JPEG only, size and pixel caps). Template, logo and the made invoice PDFs (`invoice_pdfs`) are stored as `BLOB` in the database, never as files under `UPLOAD_DIR` (a rebuilt container without its volume must not lose them); the invoice is always a PDF, a Word template is converted with LibreOffice (`docx_to_pdf`, `SOFFICE_BIN`, installed in the image). The built-in invoice follows the owner's example layout (`invoice_docs.py`); the payment QR is a SEPA/EPC code, not an iDEAL link, unless the owner sets an own https payment link (`invoice_qr_link`, fields from `invoice_docs.LINK_FIELDS`, validated on save and on restore) and it is off when `invoice_qr` is false; Open Sans lives in `backend/app/fonts/` with its licence.
- AI product images (`backend/app/ai_images.py`, `frontend/js/ai-images.js`) are optional and exist only with `AI_IMAGES_ENABLED=TRUE`: the flag is checked on the server for every route
  (404 when off) and the browser only follows `ai_images` in `/api/auth/status`. The OpenAI key is typed under Settings, kept sealed with `passwords.seal` (own `info` label) and never returned or
  put in a backup (`test_backup.py` and `test_ai_images.py` assert it); photos and results are re-encoded and live in the database (`project_images`), not under `UPLOAD_DIR`. One picture per
  picture, made by a background thread of the web worker that took the request (`ai_image_jobs` is the state the browser polls, so leaving the page stops nothing; a job that has not moved for 5 minutes is
  failed as interrupted when it is next read). The pictures are made from one or two `kind = 'source'` rows (`origin`, migration 0003: `photo`, an upload, and `model`, a view of the 3D model; at most one of each, both re-encoded by `_clean`; the photo is sent first, two go as `image[]`, and `LEAD` holds the words for each set). The view of the model is drawn in the browser by `frontend/js/model-viewer.js` (own WebGL code, nothing vendored; the turn is a rotation matrix turned on about the screen's axes, never two clamped angles, so the model goes round in every direction) from `GET /api/print-files/<id>/mesh`: **the browser never parses a print file**, `printfile.triangles` does (same defusedxml and size caps as `analyze`, at most `MAX_VIEW_TRIANGLES`, a small little-endian binary layout documented there, read from the file on each request and never stored). The colours come with it, one per triangle, where the file names them: a 3MF's `basematerials` / `colorgroup` per triangle or object, else the filament of the object or part in a Bambu Studio / OrcaSlicer project (`_slicer_colours`), or the filament painted on the triangle (`_painted`: the one that covers most of it); settings and paint that cannot be read are skipped, never an error. A colour chosen for the item overrides them in the viewer (`uOwn`). A file without a model (a sliced `.gcode.3mf` holds only the print job) is answered with 422 `pf.no_model`; the card then offers the slicer's own picture of the plate (`GET /api/print-files/<id>/preview`, `printfile.plate_picture`, re-encoded by `ai_images._clean` like any upload) to keep as the view of the model. Pictures are made for a purpose (`PURPOSES`: marktplaats, social, webshop; four each, and the four of `social` are one shape because they are posted as a carousel), and the choice, the item's own colour (`colour`, `#rrggbb` or empty for "as in the photo"; said in the prompt with a plain word from `colour_name`, and the tint of the 3D view), the owner's own words about the setting (`scene`, added to the prompt of every picture but the studio one) and the texts are kept in `projects.image_text` (migration 0002, written only by `PUT /api/projects/<id>/images/settings` and the generate request, validated by `ai_images.image_text`, in the backup). **The model never writes text**: `image_overlay.py` lays the product name, specs and extra text over the photo as an advertising poster (no panel or box: a soft shade that fades into the picture, a display typeface per purpose from `app/fonts` with its `OFL-*.txt` licence, layout per shape in `LAYOUTS`, typeface and accent per purpose in `TEMPLATES`, nothing random) on the *first* picture of the four only, and only when all three texts are filled in; the prompt merely asks for calm room there (`image_overlay.room`). The colours of the texts follow the photo (`_tone`: white on a dark shade, or dark on a light one for a light picture), and a headline with a character the display typeface lacks is set in Open Sans (`_covers`); never make either a fixed choice, a poster nobody can read is worse than none. The invoice logo goes at the top left of all four when the switch is on **and** the person asking has `business_mode` on (checked on the server at queue time). A new variant needs a line in `VARIANTS` and in `LAYOUTS`, a label in `frontend/lang` and a skeleton shape in `app.css`. Every event and error goes to `ai_image_log` (message key + parameters, worded when read; text from OpenAI is scrubbed of anything key-like and cut short; never the key),
  neither is in a backup. The host is fixed, and `test_ai_images.py` mocks `requests.request` and runs the thread on the spot: never call OpenAI from a test. A frontend child that may be `null` goes through `fill()`, not a bare `replaceChildren`.
- The filament library (`filament_library`, migration 0021, `backend/app/filament_library.py`, `bambu_invoice.py`, `bambu_store.py`) is a standalone list of the filaments that *exist* (specs, reference price excl. VAT); it never touches `filament_spools`, and nothing done to it (invoice, sync, JSON import) ever creates, changes or deletes a roll. A roll is only made *from* an entry by copying (the roll form's picker), never linked, so editing the library never rewrites a roll; a roll typed in by hand may be added to the library (`add_roll`, the `add_to_library` flag of `POST /api/spools`) and may complete an existing entry, and `POST /api/filament-library/from-rolls` (the *Rollen toevoegen aan bibliotheek* button) does the same for every roll that is not archived, through the same `add_roll`; it only reads the rolls. A contribution to the central file (`POST /api/filament-library/contribution`, *Bijdragen*) is only computed here (the entries the shared file lacks by `keys()`, without `notes`) and leaves by the person's own hand: the browser opens a pre-filled GitHub issue (form `05-filament-library.yml`, `nl-` twin) and the app holds no GitHub token and calls only the fixed `FILAMENT_LIBRARY_URL`; the button exists only while that is the default. The workflow `library-contribution` turns the issue into a pull request into `beta` through `scripts/apply_library_contribution.py`, which treats the issue text as untrusted data (an environment variable and a file, never a shell line), validates it with `_parse_library`, caps it (`MAX_ENTRIES`, `MAX_BODY_BYTES`), only *adds* what `keys()` does not know and never edits an existing entry; nothing is merged without a maintainer.
  **One rule says what the same filament is** (`keys()`: SKU, barcode, supplier `filament_id` with `refill`, or brand/material/type/colour/refill/weight/diameter, case-insensitive) and every write goes through it, serialised by the write lock every writing transaction holds: the generic create/update (`before_create` / `before_update`), `_merge` (JSON import and sync), the invoice apply, `add_roll` and the backup restore (`first_clash`). Never add a way into the table that skips it. A copy is refused (409 `library.duplicate`); only a *new* clash counts (`Index.clash`), so entries that were already alike can still be edited. An existing entry is only ever *completed* (`complete`: the empty fields in `FILLABLE`, plus the reference price from an invoice), never overwritten; the JSON import and the sync overwrite only the fields the file lists, and never delete.
  A Bambu Lab invoice is an untrusted upload (pypdf only, size and page caps; `tests/bambu_invoices.py` is the synthetic fixture: never commit a real invoice, it holds a name and an address); its prices are incl. VAT and are turned into excl. VAT, and a discount is not part of the price. The sync address is `FILAMENT_LIBRARY_URL`, checked in `config.py` (https, a GitHub raw host), fetched by the server without following redirects and never taken from a request; `library/filaments.json` is the shared file that sync reads by default and must stay a valid library (tested). The roll form's Bambu Lab panel (`bambu_catalog.py`, `GET /api/bambu/products[/<slug>]`) lists the colours of one product of the fixed list `bambu_store.CATALOG` (a slug that is not in it is never fetched; a new product is one line). The invoice import also looks each filament up on the Bambu Lab web shop (`bambu_store.py`): the `id=` of its product address, which the owner uses as the *barcode*. Only `eu.store.bambulab.com` is ever contacted (a redirect to another host ends the lookup, because the other regions' IDs differ), the page's JSON-LD is the only thing read, a failure is a warning and never stops the import, and tests never reach the shop (`tests/bambu_invoices.py:Shop`).
- Spoolman (`backend/app/spoolman.py`, migration 0025, `SPOOLMAN_URL`, `frontend/js/spoolman.js`) is an optional source of the rolls. A sync mirrors every spool as a `filament_spools` row keyed on `spoolman_id` (calculations keep pointing at the local roll, so prices and saved projects are untouched); the mirrored fields are Spoolman's, so `api.update` / delete refuse a mirrored roll except `notify_low` (409 `spoolman.managed`) and `propagate` skips it, and a spool gone from Spoolman is archived, never deleted. **A roll is one row, wherever it was entered first**: a spool that is new here and that a hand-typed roll already *is* gets linked to that roll (`_twins` + `_link`: the roll keeps its id and `notify_low`, takes Spoolman's details, and the sync counts it as `linked`) instead of being added next to it; "the same roll" is `_same`, the one rule that also finds a roll's filament in Spoolman (vendor + article number, else vendor + name + material), a roll is never two spools nor a spool two rolls (nearest weight first), and an archived roll or one without a name or barcode is nobody's twin. A hand-typed roll that no spool is, and the library, are never touched by a sync. Never add a way for a spool to become a row that skips `_twins`. **What is used is Spoolman's to keep** (the printer reports it there): while there is a Spoolman `api.book_stock` refuses every booking (409 `spoolman.no_booking`, hand-typed rolls too) and the calculation editor does not offer it, because the same grams would be taken off twice. The outbox (`spoolman_pending_use`, `flush`) only drains what was booked while the app still reported it with `PUT /spool/<id>/use` (sent first by the next sync, subtracted from the weight Spoolman reports until it is sent); nothing writes to it any more, it is not in a backup, `spoolman_id` is (a restore stays linked). *Library to Spoolman* (`push_library`) only *creates* the vendors and filaments Spoolman lacks (matched on vendor + article number, else vendor + name + material), never updates or deletes there, creates at most `MAX_CREATED` per run and has a dry run like the other syncs. *Rolls to Spoolman* (`push_rolls`) makes a spool of every hand-typed, non-archived roll that has a name or barcode (a roll Spoolman already has as a spool no roll here is linked to is only linked, by the same `_twins`, never made a second time) and links the roll (`spoolman_id`) in the same per-roll transaction, under the sync's lock, so a failure half way never leaves a spool that a second run would make again; both pushes share `Catalogue` (the vendors and filaments Spoolman has, only ever added to). The address is `SPOOLMAN_URL` when .env sets it (then the screen shows it read-only and `PUT /api/spoolman/settings` answers 409), else the one an administrator types in Settings -> Filaments (`spoolman_settings`, migration 0026, not in a backup: it describes one network); both go through `config.check_spoolman_url` (http(s), no login, query or fragment; a path is fine) and `address()` reads it once per request, before the request holds a connection, so the server only ever calls the fixed `/api/v1/...` paths of that one host, `POST /api/spoolman/test` tests the *saved* address and passes on only a verdict, and a regular user never gets the address; redirects are not followed, answers are size-capped, and Spoolman's data is clamped before it reaches a column. Tests never reach a Spoolman: `tests/test_spoolman.py` replaces `requests.request`. Syncing and pushing are administrator-only (`/api/spoolman` in `access.ADMIN_ONLY`, writes only); the status is for everybody.
- Adding a delivery by scanning (`frontend/js/bulk-scan.js`, `GET /api/spools/from-barcode`, `POST /api/spools/bulk`): what a scanned roll is made of is decided once, by `api._from_barcode`
  (the newest roll with that barcode, else the library entry with it; full, no notes), and both the list and the adding use it, so what is listed is what is made. The adding is one transaction:
  all or nothing, at most `BULK_MAX_ROLLS`. A barcode neither knows is filled in with the normal roll form, never guessed. The camera keeps reading (`scanner.cameraPanel`), and the
  page's `Permissions-Policy` allows `camera=(self)` and nothing else (`test_static_build.py`): `camera=()` made Chrome and Android refuse every scan.
- Third-party browser code is vendored under `frontend/vendor/` (unmodified, with its licence and a
  README saying how to update), never loaded from a CDN: the CSP only allows scripts from this origin.
  Currently only ZXing, for barcode scanning where the browser has no `BarcodeDetector`.
- The installed-app surface (iOS icons, launch images, no-zoom viewport, manifest) is generated and
  guarded: change `frontend/icons/icon-mark.svg` or `scripts/generate_pwa_assets.py`, re-run the script,
  and never hand-edit the `splash:` block in `index.html`. `test_pwa_assets.py` fails on a launch image
  whose size does not match its media query, an orphaned PNG, or an icon with transparency.
  Installed (standalone) navigation must use `goTo()` from `js/pwa.js`, never `location.hash =`, so
  no history entries are added.
- Web push goes through one function, `push.send_one`, and every kind (the test button included) goes
  through `push.notify`. TTL, `Urgency` and `Topic` are stated there, with the human reason next to the
  number; `high` urgency, a zero TTL, `requireInteraction` and vibration are forbidden and each is
  asserted by `test_push.py` (see project baseline section 11). Quiet hours are wall-clock plus IANA
  timezone, wrap midnight, defer rather than discard, and fail open.
- `frontend/sw.js` contains the line `const APP_VERSION = 'dev';` exactly: the server replaces it with
  the running release so every release changes the worker's bytes. Do not rename or reformat it.
- Never copy `ctx.prefs` (or any setting) into a local variable that outlives a save; read it when needed.
  `setPrefs` rolls back and returns false when the server refuses a change.
- UI text is Dutch. Build DOM with the `h()` helper and `textContent`; never `innerHTML` with data
  (the CSP also forbids inline script and style).
- **Every overview is `listView` (`frontend/js/listview.js`)**: the toolbar (search while typing, filters, order, grouping, tiles or a list), the table with headings that sort and the empty states are decided there, so the pages cannot drift apart. A page only gives its rows, `sorts`, `columns` and `tile`; a new overview does not build its own search field, sort buttons or table. The view, order and grouping are remembered per overview in the browser (`pp-list-<id>`), not in the account. Columns marked `wide` and the layout of the lines in an editor follow the room they have (container queries), not the width of the screen, because the menu and the cost price take their share.
- **An editor's actions are in its title bar** (`backLink` and `headAction` in `ui.js`): the way back, then one `.btn-group` with what else can be done, then *Save* as the primary button. Controls have two sizes from tokens (`--control`, `--control-sm`: 44 px on a touch screen, more compact where a mouse points); use `.btn.tool` for a button in a toolbar, row or line and `rowActions` for the icons of a row, never a fixed height.
- **The parts of the settings are one list, `settingsMenu()` in `settings.js`**: the menu on the left draws them under *Settings* (`main.js`, only on the settings pages) and the page draws them itself where that menu is not there (a phone) or is folded away; the css decides which is shown. A new part is an entry in `SECTIONS`, `GROUPS` and `SECTION_ICONS` and appears in both.
- A packaging item can have a picture (`backend/app/packaging_images.py`, migration 0005, `/api/packaging-images`): an untrusted upload like the product photos, so it goes through `ai_images._clean` (decoded, turned upright, scaled to `MAX_EDGE`, written again as a JPEG: no metadata, no second payload), is kept in the database and never under `UPLOAD_DIR`, goes with its item (`ON DELETE CASCADE`) and is in the backup, read again on restore. The list asks once which items have one (`GET /api/packaging-images`, id and version) and the address of a picture carries its version.
- A 3D model has `links` (migration 0004): a list of `kind`, `label` and `url`, validated by `api._project_links` (`LINK_KINDS`, at most `MAX_LINKS`, http(s) only). The kind is kept so that a later connection to a sales channel can find its own listing; a new channel is a line in `LINK_KINDS`, in `LINK_KINDS`/`HOSTS` of `projects.js` and a `link.*` text. `source_url` stays the address of the model itself (the first link of kind `model`), for a backup read by an older release, and a body with only `source_url` still works.

## 2. Versioning discipline

- Version source of truth is the `VERSION` file (`MAJOR.MINOR.PATCH`).
- **A pull request never changes `VERSION`.** Two pull requests that each raise it collide as soon as the other one merges, so the
  pipeline raises it after the merge to `main`, i.e. when `beta` is promoted: the `docker` workflow runs `scripts/bump_version.py` on every push to `main`, commits the new
  number (`Release X.Y.Z`) and builds the image from that commit. `enforce-version-bump` fails a pull request (into `beta` or `main`) that touches `VERSION`.
  A push to `beta` never raises it and publishes no release, only the `beta` image (section 5).
- A promotion that changed protected paths raises the **patch** number; put the label `version:minor` or `version:major` on the
  **promotion pull request** (`beta` → `main`, the pull request the bump reads) to raise that part instead. A promotion of documentation only (`*.md`, `*.txt`) keeps the number.
- Protected paths: `backend/`, `frontend/`, `deploy/`, `homeassistant/`, `repository.yaml`, `scripts/`, `.github/workflows/`,
  `.github/copilot-instructions.md`, `Dockerfile`, `docker-compose.yml`, `docker-compose.build.yml`, `.env.example`
  (`scripts/check_version_bump.py` holds the list).
- The workflow needs to push to `main`: github-actions must be allowed to bypass the branch protection, if there is any. Without it
  the bump fails before anything is published, with the reason in the log.

## 3. Local enforcement and CI controls

- Activate hooks once per clone: `python scripts/setup_hooks.py`.
- Every MUST rule needs an automated enforcement point (CI or hook).
- CI jobs on every pull request into `beta` or `main` (`only-from-beta` only on `main`):

  | Job name | What it checks |
  |---|---|
  | `only-from-beta` | a pull request into `main` comes from `beta` of this repository (the promotion); every other one fails |
  | `enforce-version-bump` | the pull request changed `VERSION` (it is raised after the merge, not in the pull request) |
  | `agent-instructions-lint` | that this file stays canonical and unduplicated |
  | `backend-tests` | calculator, WebAuthn, migrations, API; fails if any test was skipped |
  | `frontend-syntax` | every frontend module parses, checked as an ES module (a copy named `.mjs`: `node --check` on a `.js` file that uses `import` reports nothing, even for a broken one); the manifest is valid JSON; the service worker answers from its cache only what it may (`scripts/test_service_worker.mjs`, section 6i) |
  | `docker-build` | the image builds (also for arm64), a Word invoice template is turned into a PDF inside it (LibreOffice, as the unprivileged user), and both compose files are valid for `.env.example` |

- A control has to be findable on the pull request under the name a document cites it by.
- Migrations are forward-only: never edit an applied `NNNN_*.sql`; add a new one. A file may only be *renamed* (a number two pull requests both took) through `db.RENAMED`, which renames the record of it in an installation that already ran it; its content must stay byte for byte the same. The runner
  refuses to start on a changed checksum.

## 4. Secrets and configuration hygiene

- Never commit `.env` or real secrets; only `.env.example` is tracked.
- Keep `.env.example` complete and safe (placeholders only). A new environment variable is added
  to `backend/app/config.py`, `.env.example` and the configuration table in `README.md` and `README.nl.md` in the same change.
- Rotate `SESSION_SECRET` and `SETUP_CODE` before any public release.

## 5. Branch topology and pull request workflow

- **Pull requests go to `beta`, never directly to `main`.** `beta` is the integration branch: feature branches start from it and
  merge into it. Set GitHub's Default branch to `beta` so a new pull request targets it, and because GitHub reads issue forms and `issues`-triggered workflows (`library-contribution`) only from the default branch.
- `main` is the stable line. It only receives a pull request **from `beta`** (the promotion), when the owner asks for one, and that
  pull request is merged with a **merge commit**, never squashed or rebased (a squash leaves `beta` diverged from `main`). `only-from-beta`
  fails every other pull request into `main`. The owner makes `only-from-beta` required, and forbids pushing to `main` directly, in the
  branch protection of GitHub; that cannot be done from the code.
- A push to `beta` builds `ghcr.io/flux76hq/3dprint_pricing:beta` (and `beta-<sha>`, `docker-beta` workflow). It writes no stable tag, no
  release and no `VERSION`. A promotion builds `latest`, raises `VERSION`, and publishes `X.Y.Z` with its GitHub Release (`docker` workflow), which then
  merges `main` back into `beta` so `beta` carries the new `VERSION` (best effort; if it warns, merge `main` into `beta` by hand).
  github-actions must be allowed to push to `beta` as well as to `main`, if either is protected.
- **One variable picks the build: `PRINTPRICING_TAG`** (`latest` = stable, the default; `beta`; or a version number to pin), set in `.env`.
  `docker-compose.yml` uses it for the image (`ghcr.io/flux76hq/3dprint_pricing:${PRINTPRICING_TAG:-latest}`) and passes the same value into the
  container, where `config.build_channel()` turns it into the channel (`beta` when the tag contains `beta`). `BUILD.channel` in `js/build.js`
  (stamped by the server), `/api/version` and `<title>` carry it, and a beta build shows a **beta** label next to the app name (`betaBadge()` in
  `ui.js`, sidebar and login screen) and installs on a home screen as "PrintPricing beta". There is no `APP_IMAGE` any more. Same set-up as
  MealieShopper (`MEALIESHOPPER_TAG`); `test_deploy_layout.py` and `test_static_build.py` pin it.
- Develop on a feature branch off `beta`; never commit directly to `beta` or `main`.
- Give a new feature its own worktree and its own agent session.
- Check for an existing open PR before opening a new one; never push without a PR; never add
  commits to a branch whose PR is already merged — rebase and open a new one.
- Issues and pull requests use the templates in `.github/ISSUE_TEMPLATE/` and `.github/PULL_REQUEST_TEMPLATE.md` (adopted from App-Guidance's
  `shared/templates/github/`). The pull request template is where the deployment-file and limit statements are answered: fill every section, and
  write "nothing to do" rather than leaving one blank. Every English form has a Dutch twin (`nl-*.yml`, and `.github/PULL_REQUEST_TEMPLATE/nl.md`, opened with `?template=nl.md`); change both together, with the same field ids and labels. There is no Change Spec block: release notes are generated (see the promotion bullet below).
- Keep a branch current with `python scripts/update_branch.py` (base `origin/beta`), not a hand-made `git merge origin/beta`: it merges the base and
  settles the conflicts that are only bookkeeping (a migration whose number `beta` took meanwhile is renumbered, a screenshot in
  `docs/assets/` becomes the base's, a stray `VERSION` change becomes the base's). Run it before the first
  push of a new branch, before opening the PR, and whenever the PR turns "dirty"; anything it leaves in conflict is a real one.
- Make a conflict less likely to start with: keep a PR to what it needs, do not reflow or reformat lines you are not changing, add
  language keys at their alphabetical place, and regenerate the screenshots only when a screen changed.
- Carry your own PR into `beta` to merge: watch it, drive failing checks green, merge at all green without
  asking again. The promotion to `main` is the exception: open and merge it only when the owner asks.
- **Promoting `beta` to `main`** follows App-Guidance's
  [`shared/guidelines/promotion-runbook.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/promotion-runbook.md).
  Here: this app is on the pipeline-bump model, so the promotion does not change `VERSION` and the number is only known after the merge (section 2);
  the release notes are generated by the `docker` workflow (`gh release create --generate-notes`), not written beforehand, so step 2 of the runbook
  (curated notes first) is skipped and the promotion pull request states "since the previous stable version" in its body instead; the owner's request
  covers both opening and merging it, merged with a merge commit once the checklist is green; the full test command is
  `cd backend && PYTHONPATH=. python -m pytest -q`, plus the frontend syntax check and `python -m unittest discover -s scripts -p "test_*.py"` from `ci.yml`.
  After the merge, check that release `vX.Y.Z` exists and is *latest* (the update check reads it, section 6e) and that the `latest` and `X.Y.Z` images were built.

## 6. Testing

- Backend: `cd backend && PYTHONPATH=. python -m pytest -q`. Every test gets its own empty SQLite file (`fresh_db` in `conftest.py`); `connect()` there is a plain
  connection (tuple rows) for arranging and checking data. Only `test_pg_import.py` needs PostgreSQL (the source of the one-off import): set `TEST_DATABASE_URL`, or run as
  root with the system PostgreSQL installed and the fixtures start a throwaway cluster.
- `backend/tests/fake_authenticator.py` is a software passkey; use it for any auth test.
- Test a guard by breaking what it guards before trusting it.

## 6a. Password login and relying party

Follows the reference in App-Guidance's `shared/framework/technical-framework/auth-passkeys-password-mfa.md` (MealieShopper): a password is a door of its own, two-step verification (TOTP) is a second, separate choice, and
`RP_ID` / `RP_ORIGINS` are optional (`backend/app/passwords.py`, `password_api.py`, `relying_party.py`).

- **A password alone signs in** (`password_credentials` row, `enabled`); with an authenticator app (`totp_secret` not NULL) it takes the password and then a code, and **no session exists before both pass**
  (`/password/login` answers `mfa_required` and a token that is no session; `/password/mfa` finishes). Never weaken the lockout (5 failures, then 15 minutes and doubling, per person, plus the per-address limiter) or the TOTP
  replay guard (`last_totp_step`), and keep refusals generic ("Inloggen mislukt."). The TOTP secret being set up waits in `pending_totp_secret` until a code is confirmed; the confirmed one keeps working until then.
- **Turning a thing on needs only the session** (a password: `POST /password/setup`; the app: `/totp/start` + `/totp/confirm`; it must work on a device without a passkey). **Anything that weakens or changes it needs a fresh
  confirmation**: `password_api._confirm` takes a passkey assertion bound to the action (`auth._purpose`), or the password plus a code *when there is an authenticator app* (`_reauthenticate`: same lock, counter and replay
  guard as logging in). That covers changing the password, turning it or the authenticator app off, new backup codes, new recovery codes (`/recovery/regenerate`), promoting and resetting users, removing a backup from the server (6c), and the factory reset.
- **A refused passkey says one thing** (`auth.verification_failed`, 401 at login, 403 for a confirmation). Why it was refused (an unknown or stale passkey, another person's, no open challenge, the library's own words such as a counter that did not go up) goes to the process log only, from `auth._verify_assertion`, with the purpose and never the answer itself; `test_auto_backup.py` checks both sides.
- **Nobody is locked out by their own hand**: the password cannot be turned off without a passkey (409 `pwapi.last_method`), and the last passkey cannot be deleted without a password (409 `auth.last_passkey`).
- **The owner may start with a password** (`POST /api/auth/onboarding/password`: same setup code, same limiter, same write lock as the passkey path), for an address where no passkey can work. Invitations offer both ways too
  (`/api/invites/password` is one step; no pending state is kept). Both paths hand out the 8 recovery codes.
- **`RP_ID` and `RP_ORIGINS` are optional.** `relying_party.py` is the only place that decides them: configured values win; empty, the relying party is the host of the request and the origin is `scheme://host` as the browser used it
  (`X-Forwarded-Host` / `X-Forwarded-Proto` first, so a proxy that terminates TLS is believed), and the session cookie's `Secure` follows the request. Everything that used `cfg.rp_id` / `cfg.rp_origins` goes through it; do not read the config
  directly. The CSRF check in `create_app`'s `_guard` is `relying_party.origin_allowed`: pinned, the origin must be one of `RP_ORIGINS`; unpinned, it must be the address the page was served from. `/api/auth/status`
  reports `passkey_problem` (a message key, only for what is certain: an IP address, or no https outside localhost) and `passkey_login` (is any passkey registered), and the screens use them to open the password and explain why. Push needs a contact: `VAPID_SUBJECT`, else `mailto:admin@<RP_ID>`, else `mailto:admin@localhost`.
- The login view shows the password option only when `/api/auth/status` reports `password_login`, and the passkey button only while a passkey exists (or there is no password).

## 6b. Texts

No user-visible sentence is written in the code. Screens use `t('key')` with the text in `frontend/lang/*.json`; the server
raises `ApiError(status, "key", name=value)` with the text in `backend/app/lang/*.json`. Add a key to every language file
in the same commit (`backend/tests/test_i18n.py` fails otherwise) and give `{placeholders}` the same names in each.

## 6c. Backup and restore

`backend/app/backup.py`. A backup never contains credentials (passkeys, recovery codes, the password and its TOTP secret,
push subscriptions), users or invitations: `tests/test_backup.py` and `tests/test_users.py` check the file for them. Restore validates the whole file with the same
validators as the normal endpoints, recalculates calculations, re-reads print files, and swaps everything in one
transaction. A new table or column that holds user data belongs in the backup and in its round-trip test.

With print files the download is a ZIP (`backup.json` plus every model under `files/`, referenced by `archive_path`); without them it is one JSON file, and a JSON
file with the models inline (`content_b64`) still restores. A ZIP is never extracted to disk: a member is read by name, capped at `MAX_UPLOAD_MB`, and stored under a generated name.
The screen sends the file once to `POST /api/backup/stage` (checked, kept as `UPLOAD_DIR/.restore-<token>`), and after the owner confirms `POST /api/backup/jobs` restores it in a
thread of the web worker, so leaving the page stops nothing; the state is `backup_jobs` (polled with `GET /api/backup/jobs/latest`, not in a backup, marked done in the same transaction as the swap).
Never make the restore depend on the request that started it, and never let a refused or finished restore leave its staged file behind.

**Automatic backups** (`backend/app/auto_backup.py`, Settings → Beheer → Back-up). By default every 12 hours (`INTERVAL`) the server writes the ZIP of a download with print files
(`backup.document` + `backup.write_zip`: one code path, so the same exclusions hold and a new section is in both) to `Config.backup_dir` (`DATA_PATH/backups/auto`, made and handed to
`app` by `deploy/entrypoint.sh`; outside `UPLOAD_DIR`, so a factory reset leaves it) and keeps the newest `KEEP` (14). An administrator chooses (`GET/PUT /api/backup/auto`, `settings()` in `app_state['auto_backup:settings']`, so a factory reset puts the defaults back and the files stay): on/off, `every_days` 0.5|1|2|7|14 and `keep` 0-60; `keep == 0` makes none and removes the ones there (the worker does it too, also when switched off), a lower number prunes at once, and the About health list has an `auto_backup` check that warns only for a failed attempt (off is a choice). A new setting is validated in `validated()` with its texts in `app/lang`. A backup is written as `.tmp-*`, fsynced and renamed; the oldest are
removed only after that, so a failure never leaves fewer. Each web worker runs `start_worker`; `db.try_named_lock` lets one of them do it, and the check is repeated with the lock held.
When one is due is read from the file names (UTC), never the database (a restore or reset must not restart the clock); none is made without an owner (an empty database must not push
a real backup out) or while a restore job runs. A failure is kept in `app_state` (`auto_backup:error`, worded when read), shown on the card, and retried after `RETRY` (an hour). Restoring one
goes through `backup.stage_copy` (a copy staged like an upload, then the same job): never restore from or move the kept file itself. A name from a request is checked against `NAME` / `MANUAL`
before it touches a path. Tests turn the loop off (`AUTO_BACKUP_WORKER=off`) and call `run_once(app, now)`; `test_auto_backup.py` starts the real loop once.

**Backups made by hand.** *Maak back-up* has the server make the backup and keep it in the same folder (`POST /api/backup/auto`, `keep_manual`: what the person's own download would hold, a ZIP with
the print files or one JSON file without, written like an automatic one); nothing is downloaded, that is done from the list (`GET /api/backup/auto/<name>`). It is named `printpricing-manual-<UTC>Z.zip|json`
(`MANUAL`; a second one in the same second gets the next second, never the same name), so `_names()` (the automatic ones only) never counts it: the rotation, `keep == 0` and the schedule leave it
alone. When the folder cannot take it the answer is 507 (`backup.keep_failed`, with the reason) and nothing half-written stays. `GET /api/backup` (the plain download, which keeps nothing)
still exists for the API; no button uses it. The list (`GET /api/backup/auto`) shows both kinds, newest first, with `kind` and `with_files`. **Removing one** (`DELETE /api/backup/auto/<name>`, automatic or by hand) is the only way a
backup leaves the folder by hand: the name is checked first (an unknown one spends nothing), then `password_api._confirm(body, "backup-delete", name)`, a fresh passkey confirmation bound to that one
backup (`auth._purpose`: `backup:<name>:delete`) or the password plus a code. Never let it run without that proof.

## 6d. Factory reset

Follows App-Guidance's [`shared/guidelines/factory-reset.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/factory-reset.md).
`backend/app/system.py` (`POST /api/system/reset`, Settings → Systeem). It empties *every* table in the file except `schema_migrations`
(read from `sqlite_master`, so a table added later is covered without a change here; a table another one points at with RESTRICT waits for its turn), restarts the counters, compacts the file (`VACUUM`, so passkeys and invoices do not linger in free pages), removes the files under `UPLOAD_DIR` and the
session cookie. It is the only thing that also deletes the credentials, so it takes two things in the request itself, in this order: the typed word
(`CONFIRM_WORD`, `RESET`; `RESET_WORD` in `settings.js` is the same word and `tests/test_system.py` pins both), checked first so a missing word spends no passkey
confirmation and no attempt; then the same proof as turning off password login (`password_api._confirm`, action `factory-reset`, purpose `system:reset`): a fresh
passkey confirmation, or the password plus a code, counted against the same lockout as signing in. Never let it run without both, and never keep a table out of it unless
the app cannot start without it (`tests/test_system.py` checks that no row is left). The screen shows the warning (what goes, the owner's own passkeys too, what stays: `.env`, the image,
`DATA_PATH/backups`, accounts at other services) before the word field, asks one last question after it, and disables the form while it runs. **No restart**: nothing is held in the
process (a thread keeps its connections to the file between transactions, but nothing of the app's data: SQLite checks its own page cache against the file before every use; the secrets are in `.env`), and a test sets the app up again in the same process. The only trace is one
warning in the process log: how many tables were emptied and how many files removed, with their names (never contents). This adds no variable and changes no deployment file.

## 6e. Update check

Follows App-Guidance's [`shared/guidelines/update-check.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/update-check.md).
`backend/app/updates.py` (`GET /api/update`, `POST /api/update/check`, administrators only: `access.py`), `frontend/js/release.js` (banner, dot on the entries that lead to Settings,
dismissed per version in `localStorage`) and the *Updatecontrole* card in Settings → Beheer → Over. It reads the redirect of `github.com/Flux76HQ/3dprint_pricing/releases/latest`
(never `api.github.com`: 60 anonymous requests an hour per IP address), so it sees stable releases only, which `docker.yml` creates as `vX.Y.Z` at every promotion; a beta
never hears of a newer beta. It announces and nothing else: it never updates, restarts or downloads, and the request carries a fixed `User-Agent` and nothing about the installation.
**It is switched off with `PRINTPRICING_UPDATE_CHECK=false`** (default on; documented in `.env.example`, both READMEs and the handleiding; `docker-compose.yml` needs no change, it
passes `.env` through). The server answers with a reason *key* (`ERROR_KEYS`), never a sentence (section 6b); every key has a `release.err.*` text. This is not `frontend/js/updates.js`, which
notices that the *server* was updated since the page loaded and offers to reload.

## 6f. Users and roles

Follows App-Guidance's [`shared/guidelines/user-management.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/user-management.md)
(invitation links, reset links, removing a user), plus the one thing that guideline leaves out and this app needs: an administrator can
**promote** a regular user to administrator. Code: `users.py` (administrator routes), `invites.py` (the guest's half, no session), `access.py`,
`preferences.py`; migration `0024`; tests `tests/test_users.py`.

- **Two roles, `admin` and `user`, and an owner.** The first user (onboarding) is `is_owner`: always an administrator, never reset, demoted or
  removed (the database refuses a second owner or a non-administrator owner), so there is always one. Nobody changes their own role. A role is read
  from the database on every request (`auth.load_session`), so a promotion or demotion works at once, and so does a removal.
- **What is for administrators is one list: `access.ADMIN_ONLY`**, checked in `create_app`'s `_guard` before any handler runs. A new route under one of
  its prefixes needs nothing else; a new administrator-only area is a new line there **and** a line in `ADMIN_ONLY_CALLS` in `test_users.py`. Hiding a tab in
  `settings.js` (`ADMIN_SECTIONS`) is courtesy, never the control. Everything not listed is for any signed-in person. Handler-level checks use
  `http.require_admin` / `admin_required` (for what a path cannot say, like `PUT /api/preferences` with a company key).
- **Shared or personal.** `preferences.SHARED` (`business`, `vat_pct`, `price_rounding`, `low_stock`) is the company's, in `shared_preferences`, written by
  administrators only; everything else in `users.preferences` is the person's own. A new preference key is one or the other: decide when you add it, and put a
  company-wide one in `SHARED`. Code that needs the company's details reads `preferences.shared(conn)`, never one user's row. `GET /api/preferences` returns both
  as one document, a backup holds both under `preferences` (the restoring administrator's own plus the company's), and a backup from before the split still restores.
- **Sessions carry the user's `session_epoch`** (`ep` claim; a session without one is epoch 0). A reset bumps it, which ends that person's sessions on every device.
  `issue_session` reads the epoch as it is now, so call it after the transaction that changed the user has committed.
- **Invitations (`invitations`).** 32 random bytes, only the SHA-256 stored, shown once; the link is `<origin>/#invite=<token>` (a fragment: never sent, never logged;
  the page sends it in `X-Invite-Token` and removes it from the address bar). One use (`_finish` claims it by deleting it), 7 days, one `reset` per person, caps of 50
  users (open invitations for new people count) and 50 invitations. Unknown, expired and used tokens are one 404 (`invite.invalid`), checked **before** the body is
  looked at. A reset changes nothing until the guest has finished (the password path is one step, `/api/invites/password`). The origin in the link
  is the request's own `Origin` when it is in `RP_ORIGINS`, else the first one (with no `RP_ORIGINS`: the address the administrator opened the app on, `relying_party.public_origin`): never a host the request merely claims. A passkey goes through the same `_registration_options`,
  `_verify_registration`, `_save_credential` as onboarding (baseline §19): no second WebAuthn path.
- **Confirmations.** Promoting someone and resetting an *administrator* each need a fresh passkey confirmation (or password plus code) bound to that person
  (`auth._purpose` `user-promote` / `user-reset`, `password_api._confirm(body, action, target)`); demoting, removing and resetting a regular user do not.
- **Names are the sign-in name for a password login**, unique case-insensitively (`users_name_unique`), also against names reserved by an open invitation.
  `POST /api/auth/password/login` takes `name`; without one it only works while there is a single person (`status.login_name_required` tells the screen).
- **Removing a person is the foreign keys.** Every table with a `user_id` must reference `users` with `ON DELETE CASCADE` (or `SET NULL` for an author);
  `test_every_table_with_a_user_id_is_cleaned_by_removing_the_person` fails otherwise. What a person made belongs to the business and stays.
- Backups and invitations: a backup never holds users, invitations or credentials (6c), and a restore does not touch who can sign in. A factory reset (6d) removes everybody.
- Test a guard by breaking what it guards: `test_users.py` was checked by removing each guard in turn (the list entry, the owner check, the epoch check, the confirmation, the
  company-preferences check, the single use) and watching a test fail. Do that for the next one too.

## 6g. Home Assistant app

`repository.yaml` (root) and `homeassistant/` make this repository an app repository for Home Assistant OS / Supervised: the user adds
`https://github.com/Flux76HQ/3dprint_pricing` under Settings > Apps > Repositories. Home Assistant runs one container per app, so
`homeassistant/Dockerfile` builds on the published image (`FROM ghcr.io/flux76hq/3dprint_pricing:${BUILD_VERSION}`) and adds PostgreSQL 17, which `run.py` starts
(only while `/data/postgres` is there and the SQLite file is not, for the one-off import) before the image's own `entrypoint.sh`; it stops both if either dies. Operational detail: `docs/handleiding.md`, section *Home Assistant-app*.

- **`version` in `homeassistant/config.yaml` is the image tag it is built on.** It equals `VERSION`, is raised by `scripts/bump_version.py` in the same
  release commit, and is never edited by hand or in a pull request (`scripts/test_homeassistant_addon.py` fails when it differs from `VERSION`). The tag exists only
  once the `docker` workflow has pushed it, so an update can fail for the minutes between the release commit and the end of that build.
- **The options are the variables of `.env.example`**, not a second configuration: a variable that must be settable in Home Assistant is added to `config.yaml`
  (`options` + `schema`), `run.py` (`settings()`), and both `translations/` files in one change; the test checks them against each other. Secrets that `.env`
  would hold are made once by `run.py` and kept in `/data/secrets.json`; never log one except the generated setup code.
- `/data` is `DATA_PATH` with the layout of `docker-compose.yml` (`db/`, `uploads/`, and an old `postgres/`): the data rules of section 1 hold here too, and the PostgreSQL major
  version in the Dockerfile follows `docker-compose.yml` for as long as the importer exists. `backup: cold` stays: a SQLite file that is being written (its `-wal` file) is not a consistent copy.
- No Ingress (passkeys are bound to the domain the app is served on). `arch` follows the platforms `docker.yml` builds; today that is amd64 only.
- The `docker-build` job builds the app on the fresh image and starts it; keep that step working when the Dockerfile, `run.py` or the entrypoint changes.

## 6h. The database (SQLite)

`backend/app/db.py`; schema in `backend/app/migrations_sqlite/` (the baseline `0001_init.sql`, then forward-only `NNNN_*.sql`, checksum-guarded; the PostgreSQL migrations of the earlier releases
are kept in `migrations_legacy/` only for `pg_import.py` and its test). Never edit an applied file.

- **A transaction that may write is `BEGIN IMMEDIATE`** (`pool().connection()`) and holds the file's single write lock from its first statement, so a read-then-write sequence cannot lose a race. That is why there is no `SELECT ... FOR UPDATE`,
  advisory lock or `SKIP LOCKED` here: claiming a number, a row or a name is simply done inside the transaction. Keep transactions short and **never hold one across a call to another service** (Spoolman, OpenAI,
  the push services, LibreOffice): other requests wait for it (`PRINTPRICING_DB_BUSY_MS`, 15 s), then fail with *database is locked*. Never open a second writing block while one is open in the same thread
  (it would wait for the first; `issue_session(response, user_id, conn)` takes the open one). A long job that needs mutual exclusion takes `db.named_lock(pool, name)` (a row in `app_state` with an expiry) around
  its *non*-transactional work; work that must be claimed row by row uses a lease: `UPDATE ... SET deliver_after/claimed_until = <later> WHERE id IN (SELECT ... LIMIT n) RETURNING ...` (`push.run_outbox_once`,
  `spoolman._claim_use`).
- **A block that only reads is `pool().read()`**: a snapshot (WAL) that takes no lock a writer waits for and waits for no writer, so a list is not held up by a save and a backup of every picture holds up nobody
  (`test_concurrency.py`). It cannot write (`query_only`: SQLite refuses, and the test of that route fails), so it is never used to read *in order to write*: checking and then inserting, or claiming, belongs in
  `connection()`. Inside a `connection()` block of the same thread it does not see what that block has not committed. The session lookup of every request, the lists, the editors' reads and the backup's read are
  `read()`; a new handler that only reads uses it too, and one that might write (also rarely: `invoice_template._content` moves an old file into the database) stays `connection()` or checks `conn.read_only`.
- **A thread keeps its two connections** (one that writes, one that only reads) between blocks, because a new connection parses the whole schema before its first statement (1.2 ms, more than most queries). No transaction and
  none of the app's data outlives a block; a block inside a block of the same kind gets a connection of its own; `Database.close()` closes them all. Gunicorn runs threads (`--worker-class gthread`, `WEB_THREADS`), so
  anything kept in the process is shared between requests that run at once: give it a lock (`http.RateLimiter`, `static_files.Assets`) or keep it per thread.
- **The settings of a connection are chosen** (`db._open` says why; `test_db.py` pins them): `synchronous = FULL` (a printed invoice number must survive a power cut), SQLite's default `cache_size`, no `mmap_size`
  (`DATA_PATH` may be a network or FUSE folder). A stored moment is read with `fromisoformat`, never `strptime`.
- **An index is justified and guarded by a plan.** `tests/test_query_plans.py` records the statements a request really sends and asserts the plan of each (`EXPLAIN QUERY PLAN`), with the indexes it relies on by name
  (`EXPECTED_INDEXES`). A new query on a table that grows gets a line there; a partial index is only usable when the query's own `WHERE` implies its condition (`barcode = ?` does not imply `barcode <> ''`), and a
  function around the column (`lower(...)`, `CAST`) needs an index on that expression. Add an index in a new migration, never by editing one. The numbers and how the scans were found: `docs/performance.md`.
- **Types are declared in the schema** and come back as Python types: `UUID TEXT`, `TIMESTAMP TEXT` (UTC, fixed width: compare and sort it as text), `DATE TEXT`, `JSON TEXT`, `BOOLEAN`, `NUM1`..`NUM4` (a `Decimal`
  with that many digits behind the point; money is `NUM2`). Only bare columns are converted: an expression (`SUM(price)`, `EXISTS(...)`, a scalar sub-select) comes back as SQLite computed it, so add the amounts in Python and wrap an
  `EXISTS` in `bool()`. A new column picks one of these types; an id default and a timestamp default are in the schema, so an `INSERT` without them works.
- **Write SQL once, for SQLite**, with `%s` placeholders and `now()` as everywhere in the code. `db.translate` turns `%s` into `?` and rewrites `ILIKE`, `lower(` (a Unicode-aware `lower_u`) and `::jsonb`; the rest has to be
  SQLite (`json_each` for an `IN` list: `db.id_list`; `INSERT ... ON CONFLICT`; `RETURNING`). The unique indexes on names use `lower_u`, which only the app's own connection registers.
- **Project and order numbers** come from `db.next_number(conn, "project" | "order")` (the `counters` table): never reused, also after a delete, as the sequences were. A restore carries them on with `backup._restart_numbers`.
- **The About page** (`app/about.py`, `GET /api/about` and `POST /api/about/check`, administrators only: `access.ADMIN_ONLY`; `aboutCards(part)` in `frontend/js/settings.js`) feeds two pages. Settings → Beheer → Over shows a summary of four labelled facts (version, database health, last backup, updates; the second and third link to their pages), the update check card and the app. Settings → Beheer → Systeem shows the health of the database (a list of cheap checks, each `ok`, `warn` or `error`, plus `Database.check()` on request on a connection of its own) and the active link with it (the technical rows folded away), above the factory reset; the health card has a *Copy diagnostics* button whose text, built in `diagnosisText()`, has fixed English keys and no secrets. Backup and restore have a page of their own, Settings → Beheer → Back-up (`#/instellingen/backup`). The last backup is the newer of the copies in `DATA_PATH/backups` and the moment `backup.export()` writes to `app_state` (`last_backup`); a backup older than 30 days is flagged in the card, not in the health word. The server sends facts and keys, the screen the words; a new check is an entry in `about.about()` **and** in `HEALTH_CHECKS` with its texts in both languages (`test_about.py` checks that every named text exists). Nothing secret goes in: the old PostgreSQL address is shown without its login.
- **The one-off import** (`app/pg_import.py`, called by `migrate.py`; the address is `LEGACY_DATABASE_URL`, or `DATABASE_URL` when it names a PostgreSQL, so a docker-compose.yml that was never replaced still works) goes away, with `psycopg`, `migrations_legacy/`, the `db` service and `POSTGRES_*`, in the release after the one that introduced it.

## 6i. Performance and what a browser may keep

Performance work follows App-Guidance's [`shared/guidelines/performance-playbook.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/performance-playbook.md):
a number first, on data of a stated size, then the smallest fix, a test that fails when the fix is undone, and the number again. **The measured numbers live in
[`docs/performance.md`](docs/performance.md)** (dated, with the data size and what was only estimated) and are made by `python scripts/perf_baseline.py` (the demo data of
`generate_screenshots.py` grown to size, Gunicorn started with the flags of `deploy/entrypoint.sh`, a real browser; needs `playwright`). A change made for speed adds its before and after there,
measured on one machine on one day, and names its test. The plan-assertion test is `backend/tests/test_query_plans.py` (section 6h).

- **The app's own files** (`backend/app/static_files.py`). Every script, style sheet, PNG icon and language file is asked for with `?v=<version>-<commit>`; a URL of the *running* release is
  `immutable`, everything else is `no-cache`: index.html and `sw.js` (how a new release is noticed), a URL without a release, a URL of another release (an app that stayed open during an update)
  and every file of a `dev` build. Never give a plain URL a `max-age` (it left the previous release's scripts in the browser), and load a new kind of file with the release in its URL
  (`BUILD` in `js/build.js`) or it is revalidated at every launch. Stamping and compressing happen once per process and file, checked against the file's size and modification time; a path is
  resolved with `safe_join`, never joined by hand.
- **The service worker** answers a URL of its own release from its cache and nothing else: the page always comes from the network, so a new release shows on the very next load. Its cache is
  named after the release, so activating a new worker removes the older ones. `SHELL` in `frontend/sw.js` lists every module under `frontend/js` and both language files
  (`test_static_build.py` compares it with the folder): add a new module there.
- **Nothing under `/api/` is kept** (`no-store`, set in `create_app` after the handler, also over Flask's own header for a file), with one way past it: `http.keep_forever(response)`, for an
  answer whose bytes can never change under its URL. Today that is a stored product image and its thumbnail (`ai_images._kept`: `private`, the id is the ETag), which holds only while
  `project_images.content` is written once (`test_ai_images.py` lists every `UPDATE` of that table), a photo of a listing (`listings.photo_file`, written once in the same way), and the picture of a packaging item when it is asked for by its version
  (`/api/packaging-images/<id>?v=<hash>`: the address changes with the picture; any other address is `no-store`). A kept answer can be shown without a session on the device that kept it: decide that on purpose.
- **A list sends what a list shows, and a screen asks once.** `GET /api/projects` gives a calculation's four prices (`api.LIST_PRICES`, read out of the stored totals by SQLite), not its lines; a screen
  that needs the lines asks for that calculation (`GET /api/projects/<id>`), as the order editor does when a model is picked. `GET /api/orders` reads only the columns a row shows. The screen of a calculation opens
  with one request, `GET /api/model-editor`: every part of its answer is made by the function that answers that part's own address (`api.LISTS`, `_stock`, `_project`; `test_payloads.py` compares them), so add a
  list the screen needs to that answer, not as another request. Paging the lists was measured and left out on purpose (`docs/performance.md`, section 3): the lists filter and sort in the browser.
- **Compression is the app's own** (gzip: its files once, a JSON answer of 1 kB or more per request, `http.compressed`), because the app also runs without a proxy. A download is left alone.

## 6j. Other applications: API keys, `/api/v1` and webhooks

`backend/app/api_keys.py`, `public_api.py`, `webhooks.py`; migration `0007`; `frontend/js/integrations.js` (Settings → Beheer → Koppelingen); tests `tests/test_integrations.py`.
The user-facing description, with the fields and the retry schedule, is `docs/handleiding.md`, section *Koppelingen*.

- **A key is not a person and not a session.** `ppk_` + 32 random bytes, shown once, only its SHA-256 kept (as an invitation). It is accepted on `/api/v1` and nowhere else,
  and a session cookie is not accepted there: `public_api._guard` calls `api_keys.authenticate()` and nothing else does, and `auth.load_session` knows nothing of keys. So a key
  never reaches a write, an administrator route or a confirmation. Never let a key set `g.user_id`, and never accept one on another blueprint; a key that must do more gets its
  own surface and a decision.
- **`/api/v1` is a promise to someone else; `/api/orders` and the rest are not.** It is read-only (no route there has another method than GET; a test tries them all), versioned
  in its path, and holds what is on an invoice: **never `cost_price`, `margin_pct` or a note of the business** (`order_view`, `customer_view` name every field; do not serialise
  a whole row). Adding a field is fine; removing or renaming one is a `/api/v2`. Its errors carry `code` (the message key) next to the sentence (`http.error_response`).
- **Making and taking away needs a fresh confirmation bound to the thing** (`password_api._confirm`, `auth._purpose`: `api-key-create`, `api-key-revoke`, `webhook-create`,
  `webhook-delete`, `webhook-rotate`). Everything under `/api/integrations` is administrator-only (`access.ADMIN_ONLY`, with its lines in `ADMIN_ONLY_CALLS`).
- **A webhook message is written in the transaction of what it reports**: `webhooks.emit(conn, event, data)` takes the open connection, never one of its own, so there is no
  message without the change and no change without its message. A new event is a name in `webhooks.EVENTS` (a past-tense fact, added at the end, never renamed), an `emit` in
  the transaction, a label in `integrations.js` and both language files, and a line in the guide. The message stays small (`orders._event`): which order, its numbers and total,
  and the `/api/v1` address of the rest. No customer details, no lines.
- **Signed by the standard, from a module** (baseline §19): Standard Webhooks through the `standardwebhooks` package. Do not write the signature here. The signing key is sealed
  (`passwords.seal`, `KEY_INFO`), never returned after it was shown once, and unreadable after `SESSION_SECRET` changes: then nothing is sent until it is rotated.
- **Sending** (`webhooks.run_once`, a worker in every web process, off with `WEBHOOK_WORKER=off` and in tests): the lease of `push.run_outbox_once` (`UPDATE ... RETURNING` moves
  `next_attempt_at` ahead and counts the attempt), **no connection held while a message is on its way**, then `_settle`. At least once; `BACKOFF` then `dead`; an address that
  takes nothing for `GIVE_UP_AFTER` or answers 410 is switched off. The body is serialised once (`webhook_deliveries.body`) and a retry sends those bytes with the same `webhook-id`.
- **The address is an administrator's and may be on the own network** (the owner chose this, as for Spoolman). `check_url` and `send` refuse only what is never an application
  (link-local, multicast, unspecified), on the resolved address at the moment of sending; redirects are not followed, the answer is not read, and only a status and a reason key
  are kept. Never store or show what the other side answered. Tests never reach a network: `Net` in `test_integrations.py` replaces `webhooks.requests.request` and `_resolve`.
- **None of it is in a backup** (keys and signing keys are credentials, the addresses describe one network), a restore leaves them alone, and a factory reset removes them.
  `test_integrations.py` checks the backup for them; each guard there was checked by breaking it (the confirmation, the binding to one key, a session on `/api/v1`, a cost price in
  the view, redirects, a message outside the transaction, the lease, the link-local check, the key in the list).

## 6k. What a model is for sale as (listings)

`backend/app/listings.py`; migration `0010`; `frontend/js/listing.js` (the card *Verkoopitem* under a saved 3D model, saved with the model's own button, and opened with the model: `listing` in `GET /api/model-editor`); `/api/v1/items` in
`public_api.py`; tests `tests/test_listings.py`. The user-facing description is `docs/handleiding.md`, section *Verkoopitem*.

- **One listing per model, and it is what every channel is given.** Today by hand (title, text and a ZIP of the photos are put ready, and the address of the advertisement goes
  into the model's `links`), later by a connector, which reads this same row. Do not give a channel fields of its own on the model; a channel that needs more gets a column
  here or a table that points at the listing.
- **The price is typed, never derived.** `listings.price` (VAT included, may be empty) is what was agreed with the outside world; the calculation only advises
  (`listing.js` shows `sell_price_incl_vat` and warns under the cost price). Nothing that recalculates a model (a new filament price, a restore) may write it.
- **An EAN is checked, not trusted** (`listings.ean`: GTIN-8/12/13/14 with its GS1 check digit; kept as digits). It is optional until a channel needs it.
- **Photos are copies and are written once.** An own upload or a product picture taken over both go into `listing_photos`, through `ai_images._clean` for an upload
  (untrusted: decoded, turned upright, scaled, written again as a JPEG). A photo's bytes never change under its id, which is why the browser may keep it
  (`http.keep_forever`): the only `UPDATE` of that table sets `position`, and `test_listings.py` lists them. At most `MAX_PHOTOS`; the order is the `photos` list of the `PUT`.
- **`/api/v1/items` holds what an advertisement shows** (`item_view` names every field): never `cost_price`, `margin_pct`, the model's notes or its print files. A model without
  a listing does not exist there, and neither do its photos.
- **Listings and their photos are in the backup** (`backup.py`: `listings`, photos inline in their order), read again with `listings.fields` and `listings.clean`;
  `test_listings.py` has the round trip.

## 7. Work done in one client leaves the other clients correct

A change to a working convention goes in this file, never in a client's entry file. If a client
surface is added (a skill, an MCP server), add its row to the client-surface table above in the
same commit. `agent-instructions-lint` checks this.

## 8. Commit checklist

- [ ] `VERSION` is untouched (the promotion to `main` raises it; label the promotion pull request `version:minor` / `version:major` if it must not be a patch).
- [ ] The branch is based on `beta` and the pull request targets `beta`; it is current with it (`python scripts/update_branch.py`).
- [ ] No secrets or `.env` files are staged.
- [ ] The operational guide (`docs/handleiding.md`) is updated when run/deploy/backup behaviour changed.
- [ ] `README.md` and `README.nl.md` stay in sync (same sections, same order, same screenshots from `docs/assets/`).
- [ ] Tests added or updated; `pytest` passes.
