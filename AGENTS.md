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
inventory those prices come from (filament rolls, printers, energy tariffs). One owner signs in
with passkeys. It is a single-tenant app: there is no per-user data scoping, because there is one
owner. If that ever changes, every query in `backend/app/api.py` needs a user filter first.

Stack: Flask + Gunicorn, PostgreSQL 17, a no-build vanilla-JS frontend served by the same
process, Docker Compose. Layout: `backend/` (API, auth, migrations, tests), `frontend/` (static
PWA), `deploy/` (container entrypoint), `scripts/` (repo tooling).

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
- A saved project stores the prices as they were when saved (`projects.data`). Do not make a
- Packaging, parts and accessories (`packaging_items`, `part_items`, `accessory_items`) are price lists a calculation line copies from, except packaging: that is added on the order (a normal line at cost price, margin 0, from `Verpakking toevoegen` in the order editor), because what is needed depends on the order, not on the model. The calculation editor no longer adds `verpakking` lines; one saved with them keeps them (the calculator still sums the `verpakking` group, so no saved price changes) and shows the section until they are removed. The line's `group` (`verpakking`, `onderdeel`, `oplader`) is what the calculator sums on and is stored in saved projects, so it is never renamed even though `oplader` is shown as *Accessoires*; the link (`packaging_id`, `part_id`, `accessory_id`) is only a convenience, an order line made from a calculation puts that calculation's `oplader` lines on lines of their own with `optional` set, at cost price (they are billed, but the invoice lists `optional` lines apart, after the others), and a unit is `stuks`, `m` or `g` (price per kg) everywhere.
  project read live prices from spools, printers or tariffs: that rewrites history.
- `backend/tests/test_calc.py` pins the owner's real spreadsheet example (total 2,74). If that test
  has to change, the calculation changed: say so in the pull request.
- WebAuthn is checked by the open-source `webauthn` package (py_webauthn); `backend/app/webauthn.py` is a thin adapter that
  fixes the policy (ES256 only, user presence required, user verification not, because password managers such as Enpass
  do not report it) and translates the library's errors. Do not write ceremony checks ourselves (baseline §19). Do not widen what is accepted
  without a test that fails first.
- Uploaded print files are untrusted. All parsing goes through `backend/app/printfile.py`
  (defusedxml, size caps, readable `PrintFileError`s); never open an upload with another parser. A
  sliced 3MF is exact, geometry is only an estimate, and print time is never derived from geometry.
  Test with the synthetic fixtures in `backend/tests/printfiles.py`; a real slicer file is the
  final check, since the 3MF/slice_info layout is the slicer's, not ours.
- All data lives in one host folder, `DATA_PATH`: the database in `DATA_PATH/postgres` (mounted by the `db` service only) and the uploads in `DATA_PATH/uploads` (the app sees `DATA_PATH` as `/data`). They are plain folders, never Docker volumes (`test_deploy_layout.py` fails on a named volume or a changed mount), and `DATA_PATH` is an absolute folder of the Docker host, never `./data` (a relative path is resolved by the tool that starts the stack; under Dockhand on Unraid it landed in the host's RAM disk). `docker-compose.yml` requires it, `deploy/entrypoint.sh` warns about a relative one, `scripts/init_env.py` refuses one, and `scripts/migrate_data.sh` (run by `scripts/update.sh`) moves data that sits in another folder than `DATA_PATH`; it never deletes the old folder and refuses when `DATA_PATH/postgres` already holds a database. `deploy/migrate_uploads.sh` moves the uploads of releases before this layout (`DATA_PATH/app/uploads`) on start; never remove it while such installations may exist, and never `chown` the whole of `/data` (it is the host's folder and holds `postgres/`). `scripts/update.sh` dumps the database to `DATA_PATH/backups` before an update. Changing where the database lives needs a migration of the existing folder first: pointing the `db` mount elsewhere makes a running installation start on an empty database.
- Uploads live under `UPLOAD_DIR` (`/data/uploads`, i.e. `DATA_PATH/uploads`), never in the
  image. Stored names are generated; the original filename is only a download name.
- Every page starts with a `.page-head` header: it is the sticky title bar (safe-area aware on phones) and holds the page's main button, so keep a page's intro text outside it (`.page-intro`). `html, body` use `overflow-x: clip`, not `hidden`: `hidden` makes the body a scroll container and breaks `position: sticky`. A roll's colour is `filament_spools.colour_hex` (`#rrggbb`, empty = guess from the colour name in `filament-ui.js`).
- The screenshots in `docs/assets/` (shown by `README.md` and `README.nl.md`) are generated, never edited by hand: `python scripts/generate_screenshots.py` (needs `playwright` and `pillow`; `CHROMIUM_PATH` if the browser is elsewhere) starts a throwaway app on a scratch database with Dutch demo data and re-takes them as desktop, iPhone (iOS-style bar) and Android (Android-style bar) frames. Re-run it, and commit the PNGs, when a change alters how a screen looks; it never touches a real installation.
- Navigation icons are the Material Design Icons (`frontend/js/mdi.js`, licence in `frontend/vendor/mdi/`); the bottom bar has two styles (`html[data-nav]`: `ios` floating glass: the slider value 0-100 is turned into plain `--nav-alpha` / `--nav-blur` values by `applyNavGlass` (`ui.js`, mirrored in `theme-boot.js`) because Safari drops a `backdrop-filter` or colour that has `calc()` / `color-mix()` around a variable, or `android`), both set from the account preferences `navbar_style` (`auto` = the device's: `theme-boot.js` sets `data-platform` before the first paint, `navStyle()` in `ui.js` resolves it) / `navbar_glass` and cached for `theme-boot.js`.
- Customers (`backend/app/customers.py`, migration 0014) own the klantnummer (unique, case-insensitive; empty = next free whole number, claimed under an advisory lock). An order always has a `customer_id` (required by the API) and keeps a copy of the customer's details; saving the order or editing the customer refreshes that copy, except in orders that already have an invoice number. A customer with orders cannot be deleted. Backups carry customers; an older file without them gets customers derived from its orders.
- Margin and rounding are decided per order, not in the calculation (the calculation editor saves `price_rounding` as `none`; the account preference `price_rounding` is
  only the default for new orders). An order has `price_rounding`; a line made from a calculation keeps that calculation's cost price (excl. VAT) and has its own
  `margin_pct`, and its price per piece is derived on the server by `calc.price_from_cost` (the same code the calculation uses), never in the browser. A line without a
  cost price (a free line, or one from before migration 0017) keeps its typed price. A loose accessory (picked from `accessory_items` in the order editor, no calculation) is an `optional` line with its cost price and margin 0; the sync button
  next to a model line re-reads the calculation's cost price in the browser (`modelLines`, the same rule that added it) and only changes the line's `cost_price`, never its margin, VAT or quantity.
- Orders (`backend/app/orders.py`) keep the price per piece *including* VAT (derived as above, or copied/typed when the line has no cost price), and
  work out the totals on the server per VAT rate (`compute_totals`); the browser only displays them. An invoice number
  (a template in the business preferences, default `{JJJJ}-{NNNN}`, see `invoice_numbers.py`; counted per year in `invoice_counters`, or under year 0 when the template has no year) is claimed atomically once per order and never reused. Invoice templates (`invoice_docs.py`,
  `invoice_template.py`) are untrusted uploads like print files: capped in size and unpacked size, parsed only by `python-docx` / `pypdf`,
  stored under `UPLOAD_DIR`, and part of the backup together with orders and calculation numbers. The invoice logo (`invoice_logo.py`) is an upload too (PNG/JPEG only, size and pixel caps). Template, logo and the made invoice PDFs (`invoice_pdfs`) are stored as `bytea` in the database, never as files under `UPLOAD_DIR` (a rebuilt container without its volume must not lose them); the invoice is always a PDF, a Word template is converted with LibreOffice (`docx_to_pdf`, `SOFFICE_BIN`, installed in the image). The built-in invoice follows the owner's example layout (`invoice_docs.py`); the payment QR is a SEPA/EPC code, not an iDEAL link, unless the owner sets an own https payment link (`invoice_qr_link`, fields from `invoice_docs.LINK_FIELDS`, validated on save and on restore) and it is off when `invoice_qr` is false; Open Sans lives in `backend/app/fonts/` with its licence.
- AI product images (`backend/app/ai_images.py`, `frontend/js/ai-images.js`) are optional and exist only with `AI_IMAGES_ENABLED=TRUE`: the flag is checked on the server for every route
  (404 when off) and the browser only follows `ai_images` in `/api/auth/status`. The OpenAI key is typed under Settings, kept sealed with `passwords.seal` (own `info` label) and never returned or
  put in a backup (`test_backup.py` and `test_ai_images.py` assert it); photos and results are re-encoded and live in the database (`project_images`), not under `UPLOAD_DIR`. One picture per
  picture, made by a background thread of the web worker that took the request (`ai_image_jobs` is the state the browser polls, so leaving the page stops nothing; a job that has not moved for 5 minutes is
  failed as interrupted when it is next read), every event and error goes to `ai_image_log` (message key + parameters, worded when read; text from OpenAI is scrubbed of anything key-like and cut short; never the key),
  neither is in a backup. The host is fixed, and `test_ai_images.py` mocks `requests.request` and runs the thread on the spot: never call OpenAI from a test. A frontend child that may be `null` goes through `fill()`, not a bare `replaceChildren`.
- The filament library (`filament_library`, migration 0021, `backend/app/filament_library.py`, `bambu_invoice.py`, `bambu_store.py`) is a standalone list of the filaments that *exist* (specs, reference price excl. VAT); it never touches `filament_spools`, and nothing done to it (invoice, sync, JSON import) ever creates, changes or deletes a roll. A roll is only made *from* an entry by copying (the roll form's picker), never linked, so editing the library never rewrites a roll; a roll typed in by hand may be added to the library (`add_roll`, the `add_to_library` flag of `POST /api/spools`) and may complete an existing entry.
  **One rule says what the same filament is** (`keys()`: SKU, barcode, supplier `filament_id` with `refill`, or brand/material/type/colour/refill/weight/diameter, case-insensitive) and every write goes through it under the advisory lock `LOCK`: the generic create/update (`before_create` / `before_update`), `_merge` (JSON import and sync), the invoice apply, `add_roll` and the backup restore (`first_clash`). Never add a way into the table that skips it. A copy is refused (409 `library.duplicate`); only a *new* clash counts (`Index.clash`), so entries that were already alike can still be edited. An existing entry is only ever *completed* (`complete`: the empty fields in `FILLABLE`, plus the reference price from an invoice), never overwritten; the JSON import and the sync overwrite only the fields the file lists, and never delete.
  A Bambu Lab invoice is an untrusted upload (pypdf only, size and page caps; `tests/bambu_invoices.py` is the synthetic fixture: never commit a real invoice, it holds a name and an address); its prices are incl. VAT and are turned into excl. VAT, and a discount is not part of the price. The sync address is `FILAMENT_LIBRARY_URL`, checked in `config.py` (https, a GitHub raw host), fetched by the server without following redirects and never taken from a request; `library/filaments.json` is the shared file that sync reads by default and must stay a valid library (tested). The roll form's Bambu Lab panel (`bambu_catalog.py`, `GET /api/bambu/products[/<slug>]`) lists the colours of one product of the fixed list `bambu_store.CATALOG` (a slug that is not in it is never fetched; a new product is one line). The invoice import also looks each filament up on the Bambu Lab web shop (`bambu_store.py`): the `id=` of its product address, which the owner uses as the *barcode*. Only `eu.store.bambulab.com` is ever contacted (a redirect to another host ends the lookup, because the other regions' IDs differ), the page's JSON-LD is the only thing read, a failure is a warning and never stops the import, and tests never reach the shop (`tests/bambu_invoices.py:Shop`).
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

## 2. Versioning discipline

- Version source of truth is the `VERSION` file (`MAJOR.MINOR.PATCH`).
- **A pull request never changes `VERSION`.** Two pull requests that each raise it collide as soon as the other one merges, so the
  pipeline raises it after the merge to `main`, i.e. when `beta` is promoted: the `docker` workflow runs `scripts/bump_version.py` on every push to `main`, commits the new
  number (`Release X.Y.Z`) and builds the image from that commit. `enforce-version-bump` fails a pull request (into `beta` or `main`) that touches `VERSION`.
  A push to `beta` never raises it and publishes no release, only the `beta` image (section 5).
- A promotion that changed protected paths raises the **patch** number; put the label `version:minor` or `version:major` on the
  **promotion pull request** (`beta` → `main`, the pull request the bump reads) to raise that part instead. A promotion of documentation only (`*.md`, `*.txt`) keeps the number.
- Protected paths: `backend/`, `frontend/`, `deploy/`, `scripts/`, `.github/workflows/`,
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
  | `frontend-syntax` | every frontend module parses, checked as an ES module (a copy named `.mjs`: `node --check` on a `.js` file that uses `import` reports nothing, even for a broken one); the manifest is valid JSON |
  | `docker-build` | the image builds, a Word invoice template is turned into a PDF inside it (LibreOffice, as the unprivileged user), and both compose files are valid for `.env.example` |

- A control has to be findable on the pull request under the name a document cites it by.
- Migrations are forward-only: never edit an applied `NNNN_*.sql`; add a new one. The runner
  refuses to start on a changed checksum.

## 4. Secrets and configuration hygiene

- Never commit `.env` or real secrets; only `.env.example` is tracked.
- Keep `.env.example` complete and safe (placeholders only). A new environment variable is added
  to `backend/app/config.py`, `.env.example` and the configuration table in `README.md` and `README.nl.md` in the same change.
- Rotate `SESSION_SECRET` and `SETUP_CODE` before any public release.

## 5. Branch topology and pull request workflow

- **Pull requests go to `beta`, never directly to `main`.** `beta` is the integration branch: feature branches start from it and
  merge into it. Set GitHub's Default branch to `beta` so a new pull request targets it.
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
- Keep a branch current with `python scripts/update_branch.py` (base `origin/beta`), not a hand-made `git merge origin/beta`: it merges the base and
  settles the conflicts that are only bookkeeping (a migration whose number `beta` took meanwhile is renumbered, a screenshot in
  `docs/assets/` becomes the base's, a stray `VERSION` change becomes the base's). Run it before the first
  push of a new branch, before opening the PR, and whenever the PR turns "dirty"; anything it leaves in conflict is a real one.
- Make a conflict less likely to start with: keep a PR to what it needs, do not reflow or reformat lines you are not changing, add
  language keys at their alphabetical place, and regenerate the screenshots only when a screen changed.
- Carry your own PR into `beta` to merge: watch it, drive failing checks green, merge at all green without
  asking again. The promotion to `main` is the exception: open and merge it only when the owner asks.

## 6. Testing

- Backend: `cd backend && PYTHONPATH=. python -m pytest -q`. Database tests need PostgreSQL:
  set `TEST_DATABASE_URL`, or run as root with the system PostgreSQL installed and the fixtures
  start a throwaway cluster.
- `backend/tests/fake_authenticator.py` is a software passkey; use it for any auth test.
- Test a guard by breaking what it guards before trusting it.

## 6a. Password login

Optional, off by default, always with TOTP (`backend/app/passwords.py`, `password_api.py`). Never create a session before
both factors pass, never weaken the lockout or the TOTP replay guard (`last_totp_step`), keep refusals generic
("Inloggen mislukt."), and keep changing/disabling/regenerating backup codes behind a fresh passkey confirmation or the full password-plus-code check (`_reauthenticate`: same lock, counter and replay guard as logging in) (enabling needs only the session, by design: it must work without a passkey on that device). The login view shows the
option only when `/api/auth/status` reports `password_login`.

## 6b. Texts

No user-visible sentence is written in the code. Screens use `t('key')` with the text in `frontend/lang/*.json`; the server
raises `ApiError(status, "key", name=value)` with the text in `backend/app/lang/*.json`. Add a key to every language file
in the same commit (`backend/tests/test_i18n.py` fails otherwise) and give `{placeholders}` the same names in each.

## 6c. Backup and restore

`backend/app/backup.py`. A backup never contains credentials (passkeys, recovery codes, the password and its TOTP secret,
push subscriptions): `tests/test_backup.py` greps the file for them. Restore validates the whole file with the same
validators as the normal endpoints, recalculates calculations, re-reads print files, and swaps everything in one
transaction. A new table or column that holds user data belongs in the backup and in its round-trip test.

With print files the download is a ZIP (`backup.json` plus every model under `files/`, referenced by `archive_path`); without them it is one JSON file, and a JSON
file with the models inline (`content_b64`) still restores. A ZIP is never extracted to disk: a member is read by name, capped at `MAX_UPLOAD_MB`, and stored under a generated name.
The screen sends the file once to `POST /api/backup/stage` (checked, kept as `UPLOAD_DIR/.restore-<token>`), and after the owner confirms `POST /api/backup/jobs` restores it in a
thread of the web worker, so leaving the page stops nothing; the state is `backup_jobs` (polled with `GET /api/backup/jobs/latest`, not in a backup, marked done in the same transaction as the swap).
Never make the restore depend on the request that started it, and never let a refused or finished restore leave its staged file behind.

## 6d. Factory reset

Follows App-Guidance's [`shared/guidelines/factory-reset.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/factory-reset.md).
`backend/app/system.py` (`POST /api/system/reset`, Settings → Systeem). It truncates *every* table in the schema except `schema_migrations`
(read from `pg_tables`, so a table added later is covered without a change here), restarts the sequences, removes the files under `UPLOAD_DIR` and the
session cookie. It is the only thing that also deletes the credentials, so it takes two things in the request itself, in this order: the typed word
(`CONFIRM_WORD`, `RESET`; `RESET_WORD` in `settings.js` is the same word and `tests/test_system.py` pins both), checked first so a missing word spends no passkey
confirmation and no attempt; then the same proof as turning off password login (`password_api._confirm`, action `factory-reset`, purpose `system:reset`): a fresh
passkey confirmation, or the password plus a code, counted against the same lockout as signing in. Never let it run without both, and never keep a table out of it unless
the app cannot start without it (`tests/test_system.py` checks that no row is left). The screen shows the warning (what goes, the owner's own passkeys too, what stays: `.env`, the image,
`DATA_PATH/backups`, accounts at other services) before the word field, asks one last question after it, and disables the form while it runs. **No restart**: unlike a
SQLite app nothing is held in the process (the database is PostgreSQL, the secrets are in `.env`), and a test sets the app up again in the same process. The only trace is one
warning in the process log: how many tables were emptied and how many files removed, with their names (never contents). This adds no variable and changes no deployment file.

## 6e. Update check

Follows App-Guidance's [`shared/guidelines/update-check.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/update-check.md).
`backend/app/updates.py` (`GET /api/update`, `POST /api/update/check`, signed in = the owner), `frontend/js/release.js` (banner, dot on the entries that lead to Settings,
dismissed per version in `localStorage`) and the *Updates* card in Settings → Algemeen. It reads the redirect of `github.com/Flux76HQ/3dprint_pricing/releases/latest`
(never `api.github.com`: 60 anonymous requests an hour per IP address), so it sees stable releases only, which `docker.yml` creates as `vX.Y.Z` at every promotion; a beta
never hears of a newer beta. It announces and nothing else: it never updates, restarts or downloads, and the request carries a fixed `User-Agent` and nothing about the installation.
**It is switched off with `PRINTPRICING_UPDATE_CHECK=false`** (default on; documented in `.env.example`, both READMEs and the handleiding; `docker-compose.yml` needs no change, it
passes `.env` through). The server answers with a reason *key* (`ERROR_KEYS`), never a sentence (section 6b); every key has a `release.err.*` text. This is not `frontend/js/updates.js`, which
notices that the *server* was updated since the page loaded and offers to reload.

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
