<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/icon.png">
  <img src="docs/assets/icon.png" alt="3D Print Pricing logo" width="128">
</picture>

# 3D Print Pricing

**The self-hosted cost calculator for 3D-print businesses.**

Work out what a print really costs, keep track of your filament stock, and turn customer orders into invoices: from your phone or your desk, on a server of your own.

🇬🇧 **English** · 🇳🇱 [Nederlands](README.nl.md)

[![Platform](https://img.shields.io/badge/platform-iOS%20%7C%20Android%20%7C%20Web-blue)](#getting-started)
[![Self-hosted](https://img.shields.io/badge/self--hosted-Docker-2496ED?logo=docker&logoColor=white)](#installation-self-hosted)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-app-41BDF5?logo=homeassistant&logoColor=white)](#installation-as-a-home-assistant-app)
[![Languages](https://img.shields.io/badge/languages-NL%20%7C%20EN-lightgrey)](#features)
[![Status](https://img.shields.io/badge/status-in%20development-orange)](#)

[![Last commit](https://img.shields.io/github/last-commit/Flux76HQ/3dprint_pricing/beta)](https://github.com/Flux76HQ/3dprint_pricing/commits/beta)
[![Commit activity](https://img.shields.io/github/commit-activity/m/Flux76HQ/3dprint_pricing)](https://github.com/Flux76HQ/3dprint_pricing/graphs/commit-activity)
[![Forks](https://img.shields.io/github/forks/Flux76HQ/3dprint_pricing?style=social)](https://github.com/Flux76HQ/3dprint_pricing/forks)
[![Stars](https://img.shields.io/github/stars/Flux76HQ/3dprint_pricing?style=social)](https://github.com/Flux76HQ/3dprint_pricing/stargazers)
[![Issues](https://img.shields.io/github/issues/Flux76HQ/3dprint_pricing)](https://github.com/Flux76HQ/3dprint_pricing/issues)
[![Contributors](https://img.shields.io/github/contributors/Flux76HQ/3dprint_pricing)](https://github.com/Flux76HQ/3dprint_pricing/graphs/contributors)

[![Release](https://img.shields.io/github/v/release/Flux76HQ/3dprint_pricing)](https://github.com/Flux76HQ/3dprint_pricing/releases/latest)
[![Buy me a coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-flux76-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/flux76)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-flux76-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/flux76)

[Documentation (Dutch)](docs/handleiding.md) · [Release notes](https://github.com/Flux76HQ/3dprint_pricing/releases) · [Report a bug](https://github.com/Flux76HQ/3dprint_pricing/issues/new/choose)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/desktop-calculation-dark.png">
  <img src="docs/assets/desktop-calculation.png" alt="3D Print Pricing on the desktop: a calculation with the cost price summary" width="900">
</picture>

</div>

---

## Contents

- [Why 3D Print Pricing?](#why-3d-print-pricing)
- [Features](#features)
- [Screenshots](#screenshots)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Running it](#running-it)
- [Data and backups](#data-and-backups)
- [Architecture](#architecture)
- [Stable and beta](#stable-and-beta)
- [Contributing](#contributing)
- [Privacy and security](#privacy-and-security)
- [Support 3D Print Pricing](#support-3d-print-pricing)
- [Third-party data and code](#third-party-data-and-code)
- [License](#license)

## Why 3D Print Pricing?

Selling 3D prints means knowing what each one costs: filament by the gram, machine time, electricity, packaging and a fair share of the printer's purchase price. A spreadsheet gets you there, until the prices change, the stock runs out unnoticed, or a customer wants an invoice. 3D Print Pricing keeps the prices, the stock and the orders in one place that you host yourself, and works from your phone as well as your desk.

## Features

- **Cost price in seconds**: filament, parts, accessories (cables, chargers), printer depreciation and energy add up to a cost price, with an optional margin for a recommended selling price. Every line is rounded to the cent first, so the lines on screen add up to the total, and a saved calculation keeps the prices of the moment you saved it, so changing a roll price later never rewrites your history.
- **Straight from the slicer**: attach a `.3mf` or `.stl` file. A sliced 3MF (Bambu Studio / Orca) gives the real grams per filament and the print time, which go into the calculation automatically; an STL gives a weight estimate.
- **Filament library**: the specs of the filaments you buy (brand, type, colour, supplier filament ID, weight, diameter, temperatures, indicative price), so a new roll fills itself in. Fill it without typing (import a Bambu Lab invoice or a JSON file, add the rolls of your filament list, sync the shared library from GitHub, or contribute yours to it) and export it as JSON; an import or sync only adds and updates, never deletes, never holds the same filament twice, and leaves your stock alone.
- **Filament stock with barcode scanning**: your rolls with price, remaining weight, colour and temperatures, grouped per kind. Create a roll by hand, by scanning its barcode (one the app does not know yet: pick the brand and filament from [SpoolmanDB](https://github.com/Donkie/SpoolmanDB) and only the price is left), from the library or, for Bambu Lab, from the web shop's products and colours, duplicate a roll to add one or more of the same, or add a whole delivery at once by scanning the rolls one after the other; search by name, barcode or material as you type; get a notification when a kind is nearly out, and book the usage of a calculation off the stock with one click.
- **Business-ready**: VAT on the selling price, a margin and a price rounding per order (to 5/10/50 cents, whole euros, or ending in ,95/,99, with your margin as the minimum), and a button to blur the costs when a customer looks over your shoulder.
- **Every overview works the same**: 3D models, orders, customers, filament, packaging, parts and printers are shown as tiles or as a list; you search while you type, filter, sort on a column and group rolls per kind. A 3D model keeps several links: the page of the model and the places where it is for sale (Marktplaats, Bol.com, your web shop).
- **Put a model up for sale**: every 3D model can have a listing: the title and text of the advertisement, your asking price (with the price the calculation advises next to it), an EAN and the photos in your order, your own or taken over from the product pictures. One click puts the title, the text and the photos ready to place an advertisement on Marktplaats, and another application reads what is for sale through the API.
- **Customers, orders and invoices**: customers with a customer number, orders with several prints each, a status from *new* to *completed*, and a PDF invoice with your logo, a unique invoice number and a SEPA payment QR code. Bring your own Word or PDF letterhead if you like.
- **Connect your other applications**: with an API key your bookkeeping or finance app reads orders, invoice details and the invoice PDF, and a sales channel reads your listings with their photos (read-only, without cost prices), and a signed webhook gives a sign as soon as you make an invoice or an order changes.
- **Passkey login**: no password to leak. Or a password where a passkey cannot work (an IP address on your own network), optionally with two-step verification, and recovery codes for emergencies.
- **More than one person**: an administrator invites people with a one-time link, and each chooses their own passkey or password, so nobody ever knows anyone else's. Regular users do the daily work; an administrator also manages users, the company details, backups and updates, and can promote a regular user to administrator.
- **A real app on every device**: installs on the iPhone and Android home screen and on the desktop, works with the camera and with notifications, and speaks Dutch and English.
- **Your data, your server**: everything runs in your own container, your data stays in one folder on your own host, and you back up and restore all of it from within the app, which also backs everything up by itself every 12 hours.

The full description of every feature is in the [operations guide](docs/handleiding.md) (Dutch).

## Screenshots

### Desktop

| 3D Models | Filament stock | Orders |
|:---:|:---:|:---:|
| <img src="docs/assets/desktop-calculations.png" width="290" alt="Overview of calculations"> | <img src="docs/assets/desktop-filament.png" width="290" alt="Filament stock per kind"> | <img src="docs/assets/desktop-orders.png" width="290" alt="Orders with their status"> |

### iPhone: the iOS-style look

The floating, glass-like navigation bar. Installed on the home screen it runs full screen under the status bar.

| 3D Models | Cost price | Orders | Filament |
|:---:|:---:|:---:|:---:|
| <img src="docs/assets/ios-calculations.png" width="200" alt="iOS: calculations"> | <img src="docs/assets/ios-calculation.png" width="200" alt="iOS: cost price of a calculation"> | <img src="docs/assets/ios-orders.png" width="200" alt="iOS: orders"> | <img src="docs/assets/ios-filament.png" width="200" alt="iOS: filament stock"> |

### Android: the Android-style look

The full-width navigation bar with a pill behind the active icon.

| 3D Models | Cost price | Orders | Filament |
|:---:|:---:|:---:|:---:|
| <img src="docs/assets/android-calculations.png" width="200" alt="Android: calculations"> | <img src="docs/assets/android-calculation.png" width="200" alt="Android: cost price of a calculation"> | <img src="docs/assets/android-orders.png" width="200" alt="Android: orders"> | <img src="docs/assets/android-filament.png" width="200" alt="Android: filament stock"> |

### Settings and your own colour

*Settings* is grouped into *Personal*, *Data* and *Administration*, each part with an icon (what you see depends on your role). On a phone the parts form a row you swipe. Under *Display* you choose the language, light or dark, and your **accent colour**: eleven presets, bordeaux and graphite among them, or any colour of your own. The whole interface follows it, not only the buttons. On *Filaments*, the Spoolman and *Import and share* blocks fold away.

| Display: light, with the default violet | Display: dark, with teal |
|:---:|:---:|
| <img src="docs/assets/desktop-settings.png" width="440" alt="Desktop: Settings, Display, light with the violet accent colour"> | <img src="docs/assets/desktop-settings-dark.png" width="440" alt="Desktop: Settings, Display, dark with the teal accent colour"> |

| iPhone: settings | Android: settings |
|:---:|:---:|
| <img src="docs/assets/ios-settings.png" width="200" alt="iOS: Settings with the swipeable menu"> | <img src="docs/assets/android-settings.png" width="200" alt="Android: Settings with the swipeable menu"> |

### Filament: library, import and new rolls

*Settings → Filaments* holds the filament library: add a filament, import a Bambu Lab invoice, add the rolls of your filament list, import or export the library as JSON, sync it from GitHub, or contribute your filaments to the central library through a pre-filled GitHub issue. Under *Filament → New roll* you create a roll, either by hand, by scanning its barcode or by picking a filament from the library. For a filament that is not in the library yet, *Pick from SpoolmanDB* offers the brands and filaments of that community list (the snapshot that ships with the app, so it works offline): one pick fills in the material, colour, weight, diameter and temperatures, and what you type is the price. A filament you already have under a Dutch name (*Geel*) is offered under that name when you pick its English twin (*Yellow*), so it is never added twice; the density and the empty-spool weight go to Spoolman when a roll made from it is pushed there. *Filament → Scan* adds a delivery: scan every roll (camera or barcode scanner), and the rolls with a known barcode are added in one go, each starting full.

| Library: import, export and sync | New roll |
|:---:|:---:|
| <img src="docs/assets/desktop-library.png" width="440" alt="Desktop: the filament library with invoice import, sync, JSON export and import"> | <img src="docs/assets/desktop-new-roll.png" width="440" alt="Desktop: creating a new roll, with the SpoolmanDB and library pick-lists on top"> |

| iPhone: library | iPhone: new roll | Android: library | Android: new roll |
|:---:|:---:|:---:|:---:|
| <img src="docs/assets/ios-library.png" width="200" alt="iOS: the filament library"> | <img src="docs/assets/ios-new-roll.png" width="200" alt="iOS: creating a new roll"> | <img src="docs/assets/android-library.png" width="200" alt="Android: the filament library"> | <img src="docs/assets/android-new-roll.png" width="200" alt="Android: creating a new roll"> |

Under *Settings → Display → Navigation bar*, choose iOS-style or Android-style, or leave it on *Automatic*: the app detects the device and defaults to Android-style on Android and iOS-style elsewhere. Your choice is saved with your account and applies on all your devices. Light, dark and system themes and your own accent colour are included.

<sub>The screenshots show demo data.</sub>

## Getting started

- 🌐 **Web:** open the address of your own installation. Passkeys need https and a domain name.
- 📱 **iPhone / iPad** and 🤖 **Android:** see [Install as an app](#install-as-an-app).
- 🐳 **Self-hosted:** see [Installation](#installation-self-hosted), or [as a Home Assistant app](#installation-as-a-home-assistant-app).

### Install as an app

- **Android (Chrome, Edge, Samsung Internet) and desktop:** open the https address and choose *Install app* in the prompt, or under *Settings → General → Install app*. Long-press the icon for shortcuts (new calculation, filament).
- **iPhone / iPad:** open the https address in **Safari → Share → Add to Home Screen**. The app then starts full screen with its own icon and launch screen, without pinch-zoom or sideways swiping, like a native app.

### Installation (self-hosted)

```bash
git clone https://github.com/Flux76HQ/3dprint_pricing.git
cd 3dprint_pricing
python scripts/init_env.py --port 6090 --domain print.example.com   # creates .env with fresh secrets
docker compose up -d
```

`init_env.py` is the easy route; copying `.env.example` to `.env` and editing it works just as well. A server only needs `docker-compose.yml` and `.env`: the image is pulled from `ghcr.io/flux76hq/3dprint_pricing`. Without `--domain`, `RP_ID` and `RP_ORIGINS` stay empty and the app follows the address you open it on (also an IP address), enough to try it out.

Then open the address and go through the onboarding:

1. Enter the **setup code** and your name. The setup code is the value after `SETUP_CODE=` in the `.env` file on your server (`init_env.py` printed it too; `grep SETUP_CODE .env` shows it again). Type or paste it into the *Setup code* field of the first screen; you only need it for this first setup, afterwards you sign in with your passkey or password. The onboarding screen explains this as well.
2. Choose how you sign in: create a **passkey** (fingerprint, face or device code), or choose **a password** (at least 12 characters). Where a passkey cannot work (an IP address, no https) the screen says so and the password is already open.
3. **Save the 8 recovery codes.** They are shown once and each works once.

A password works on any address, also on your own network. For passkeys, installing, the camera and notifications put a reverse proxy with TLS in front of the app and set `RP_ID` and `RP_ORIGINS` to that domain: they only work over https (except on `localhost`).

### Installation as a Home Assistant app

On Home Assistant OS or Supervised, add `https://github.com/Flux76HQ/3dprint_pricing` under **Settings > Apps > Install app > Repositories** and install *3D Print Pricing*: the app keeps its data (one SQLite database and the uploads) in the app's folder, which Home Assistant backs up. Passkeys still need a domain with https in front of the app's port, so set `rp_id` on the Configuration tab for them; with a password the app also works on `http://<address of Home Assistant>:6080`. The steps are on the app's Documentation tab ([`homeassistant/DOCS.md`](homeassistant/DOCS.md)). Runs on amd64 and aarch64 (Raspberry Pi 4/5, ARM mini PCs).

## Configuration

Set in `.env`; [`.env.example`](.env.example) documents every value. Never commit `.env`: it holds the secrets.

| Variable | Required | Default | Description |
|---|:---:|---|---|
| `DATA_PATH` | ✅ | - | Host folder for all data: the database (`db/`, one SQLite file) and the uploaded files (`uploads/`). Plain folders, not Docker volumes. Must be an **absolute** folder of the Docker host on a local disk (e.g. `/srv/printpricing`, on Unraid the pool itself, `/mnt/<pool>/appdata/printpricing`, not `/mnt/user/...` unless appdata is an exclusive share: SQLite does not belong on a network share or FUSE mount), never `./data`; data that ended up elsewhere is moved by `scripts/migrate_data.sh` |
| `PRINTPRICING_TAG` | ❌ | `latest` | Which build runs: `latest` (stable), `beta` (the development version) or a version number such as `0.26.15`. `docker-compose.yml` pulls `ghcr.io/flux76hq/3dprint_pricing:<tag>` and passes the same value to the app, which shows a **beta** label next to its name on `beta`. Replaces `APP_IMAGE` |
| `WEB_PORT` | ✅ | - | Port of the app; compose publishes it and the app listens on it |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | ✅ | - | Only for the PostgreSQL of the releases before SQLite, which the app reads once to move your data over when it starts without a SQLite file (see the [operations guide](docs/handleiding.md), *Overstap naar SQLite*). Keep them as they are; the next release drops them. Letters and digits only in the password |
| `RP_ID` | ❌ | empty | Domain the app runs on, without scheme or port. Passkeys are bound to it, so set it once you use them. Empty: the address the app is opened on |
| `RP_ORIGINS` | ❌ | empty | Full origin(s), comma separated, for example `https://print.example.com`. When set, writes from any other origin are refused, and invitation links use the address the administrator is signed in on when it is listed here, otherwise the first one. Empty: the address the app is opened on |
| `SETUP_CODE` | ✅ | - | One-time code for the onboarding, so the first visitor cannot take over the app |
| `SESSION_SECRET` | ✅ | - | Signs session cookies, at least 32 characters |
| `RP_NAME` | ❌ | `3D Print Pricing` | Name shown in the passkey prompt |
| `SESSION_HOURS` | ❌ | `24` | Lifetime of a session |
| `MAX_UPLOAD_MB` | ❌ | `50` | Largest STL/3MF upload in MB |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | ❌ | empty | Key pair for push notifications (`python scripts/generate_vapid.py`); empty means notifications are off |
| `VAPID_SUBJECT` | ❌ | `mailto:admin@<RP_ID>` (`mailto:admin@localhost` without `RP_ID`) | Contact address for the push services |
| `AI_IMAGES_ENABLED` | ❌ | `FALSE` | Set to `TRUE` to show the optional *AI images* feature (product pictures from a photo, made with OpenAI GPT Image). The API key is entered in the app under Settings, not in `.env` |
| `FILAMENT_LIBRARY_URL` | ❌ | this repository's `library/filaments.json` | Where *Settings → Filaments → Sync* reads the shared filament library from: a JSON file in the format of the library export, on `raw.githubusercontent.com`. Empty switches the Sync button off |
| `SPOOLMAN_URL` | ❌ | empty (type it in the app) | The address of your [Spoolman](https://github.com/Donkie/Spoolman) as the app's container reaches it, e.g. `http://spoolman:8000` (no login). With it, *Settings → Integrations → Spoolman → Sync* reads the rolls and what is left on them from Spoolman (a roll you already had here is linked, so it does not appear twice), Spoolman keeps track of what is used (booking it out from a 3D Model is then off), and the library and your own rolls can be pushed to it. Leave it empty to type the address in the app instead (administrators, *Settings → Integrations*); when it is set here, it wins and the app shows it read-only |
| `HASPELSYNC_URL` | ❌ | empty (type it in the app) | The address of your [HaspelSync](https://github.com/Rdiger-36/HaspelSync) as the app's container reaches it, e.g. `http://haspelsync:4000` (no login). With it, the *Printers* page shows what each printer is printing now and which filament is in it (the app only reads from HaspelSync, it changes nothing there). A name that does not end in `.local` has to be listed under *Allowed host names* in HaspelSync; an IP address does not. Leave it empty to type the address in the app instead (administrators, *Settings → Integrations*); when it is set here, it wins and the app shows it read-only |
| `HASPELSYNC_API_KEY` | ❌ | empty (type it in the app) | An API key made in HaspelSync under *Network access* (it starts with `ams_`). A HaspelSync key can do everything there, so make one for this app only. It needs `HASPELSYNC_URL` here as well and is only ever sent to that address. Leave it empty to type the key in the app instead: it is then kept encrypted, never shown again and not part of a backup |
| `PROXY_HOPS` | ❌ | `0` | Number of reverse proxies in front of the app |
| `WEB_CONCURRENCY` | ❌ | `2` | Number of Gunicorn workers |
| `WEB_THREADS` | ❌ | `4` | Threads per worker; workers x threads requests are handled at once, so one long request (a large 3MF, an invoice, a backup) does not hold up the rest |
| `PRINTPRICING_UPDATE_CHECK` | ❌ | `true` | The update check: the app asks GitHub whether a newer stable release exists and tells the owner with a banner and under *Settings → Administration → About → Update check*. It sends nothing about your installation and never updates anything. `false` (also `0`, `no`, `off`) switches it off, for an installation that must not call out. A beta build only sees stable releases |

## Running it

| Task | Command |
|---|---|
| Start | `docker compose up -d` |
| Stop | `docker compose down` (the data stays in `DATA_PATH`) |
| Update | `sh scripts/update.sh`, which copies the database to `DATA_PATH/backups` first; or by hand `docker compose pull && docker compose up -d` |
| Roll back | set `PRINTPRICING_TAG` to the previous version number, then `docker compose up -d`; the copy `scripts/update.sh` made is in `DATA_PATH/backups` |
| Logs | `docker compose logs -f app` |

- **Health check:** `GET /healthz` answers `200` with `{"status": "ok", "version": …, "commit": …}` while the process lives; `GET /readyz` also checks the database and answers `503` when it does not respond.
- **Largest upload:** 50 MB per STL/3MF file (`MAX_UPLOAD_MB`). Whatever runs in front of the app (a reverse proxy, a CDN) must allow at least `MAX_UPLOAD_MB` + 1 MB, and as much as your backup when you restore one with print files (up to 2 GB). Every limit outside the repository is listed in the [operations guide](docs/handleiding.md), *Limieten buiten de repository*.
- **Update check:** the app tells the owner when a newer stable release exists. It asks GitHub for the latest stable release of this repository, sends nothing about your installation, shows a banner and *Settings → Administration → About → Update check*, and never updates itself. `PRINTPRICING_UPDATE_CHECK=false` switches it off.

Notifications and everything else about running the app are in the [operations guide](docs/handleiding.md) (Dutch).

## Data and backups

Everything lives under `DATA_PATH`:

| Folder | What is in it |
|---|---|
| `db/` | the database, `printpricing.sqlite3` (with a `-wal` and `-shm` file next to it while the app runs) |
| `uploads/` | the uploaded STL and 3MF files |
| `backups/` | the copies of the database that `scripts/update.sh` makes before an update, and in `backups/auto/` the app's automatic backups |
| `postgres/` | the database of the releases before SQLite, only when you come from one; read once to move the data over, then yours to remove |

Back up from within the app (*Settings → Administration → Backup*): one JSON file, or a ZIP when you include the print files. That backup never contains credentials (passkeys, recovery codes, passwords, push subscriptions), users or invitations. For the whole server, copy the database with `docker compose exec -T app python backup_db.py /data/backups/backup-$(date +%F).sqlite3` and back up `uploads/` too, or stop the stack and copy `DATA_PATH`; a plain `cp` of the database while the app runs is not a consistent copy. Keep `.env` apart, in your password manager.

The app also backs up by itself: by default every 12 hours it makes the same ZIP (with the print files, the orders and their invoices) in `DATA_PATH/backups/auto` and keeps the newest 14, a week; a new one replaces the oldest. An administrator can switch it off, choose how often (every 0.5, 1, 2, 7 or 14 days) and how many to keep (0 to 60) in *Settings → Administration → Backup*. *Settings → Administration → Backup* lists them together with every backup made with *Make backup*, which is kept there (not downloaded) and never removed by the rotation, to download, restore or delete (deleting asks for your passkey, or your password and code). They sit on the same disk as the data they protect, so copy one off the server now and then, and count on about 14 times the size of `uploads/` plus the database. Details: [operations guide](docs/handleiding.md), *Automatische back-ups*.

Restoring: *Restore from backup…* checks the whole file first, shows what comes back, and after you confirm replaces everything in one go; if something fails, nothing changes. A database copy is put back with the app stopped, in place of `db/printpricing.sqlite3`, after removing its `-wal` and `-shm` files; the commands are in the [operations guide](docs/handleiding.md), *Back-up en herstel*.

*Settings → System → Clean-up → Reset to factory settings…* puts the app back to a new installation: it deletes everything in the database and the uploads (the passkeys too) after a typed word and a fresh passkey (or password and code) confirmation, and leaves `.env`, the image and `DATA_PATH/backups` (the automatic backups too) alone. Make a backup first if you are not sure.

## Architecture

```mermaid
flowchart LR
    A[Phone or desktop<br/>installed PWA] -->|https| P[Reverse proxy<br/>TLS]
    P --> B[App container<br/>Flask API + PWA files]
    B --> C[(SQLite file)]
    B --> D[/Uploaded STL and 3MF files/]
    B -.->|optional web push| E[Push services]
    B -.->|one-off import| F[(PostgreSQL of<br/>earlier releases)]
```

| Component | Purpose | Data |
|---|---|---|
| `app` | Gunicorn serving the Flask API and the PWA files; runs the database migrations before it takes traffic | `DATA_PATH/db`, `DATA_PATH/uploads` |
| `db` | the PostgreSQL 17 of the releases before SQLite, only read once to move the data over; it goes away in the next release | `DATA_PATH/postgres` |

- **App / frontend:** a Progressive Web App in plain JavaScript, no build step, with a service worker for the offline shell
- **Backend:** Python, Flask and Gunicorn; passkeys through the open-source `py_webauthn` library (`webauthn` package)
- **Database:** SQLite (one file, WAL mode), with forward-only, checksum-guarded migrations
- **Infrastructure:** Docker Compose, an image published to GHCR by CI

## Stable and beta

| | Stable | Beta |
|---|---|---|
| Branch | `main` | `beta` |
| Image | `ghcr.io/flux76hq/3dprint_pricing:latest` (and `X.Y.Z`) | `ghcr.io/flux76hq/3dprint_pricing:beta` |
| GitHub release | `vX.Y.Z` | none |

Every change lands in `beta` first, and every push to `beta` builds a new beta image. Only when the beta proves itself is it promoted to `main`, which raises `VERSION` and builds `latest` and the release. To try the beta, set `PRINTPRICING_TAG=beta` in `.env` (the app then shows a **beta** label next to its name) and run `docker compose pull && docker compose up -d`; use a separate data folder for it.

## Contributing

Contributions are welcome. Pull requests go to the `beta` branch, never directly to `main`; `main` is the stable line and only receives a promotion pull request from `beta`. The working conventions for people and AI assistants alike are in [`AGENTS.md`](AGENTS.md): versioning, local checks, tests and the pull request workflow. For bugs and ideas, open an [issue](https://github.com/Flux76HQ/3dprint_pricing/issues/new/choose).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-dev.txt
python scripts/setup_hooks.py
cd backend && PYTHONPATH=. python -m pytest -q
```

The screenshots above are generated from a demo instance: after a change that alters how a screen looks, run `pip install playwright && python scripts/generate_screenshots.py` and commit the updated images in `docs/assets/`.

## Privacy and security

- Everything is stored on your own server: there is no account with us, no analytics and no tracking.
- Signing in uses passkeys or, where a passkey cannot work, a password (hashed with argon2id), optionally with two-step verification.
- A backup from the app never contains credentials (passkeys, recovery codes, passwords, push subscriptions) or invitations. An invitation link is shown once and only its hash is stored.
- Report a vulnerability privately, through a [private security advisory](https://github.com/Flux76HQ/3dprint_pricing/security/advisories/new) or to the maintainers ([@Flux76HQ](https://github.com/Flux76HQ)) directly, never in a public issue.

## Support 3D Print Pricing

3D Print Pricing is free. If it is useful to you, a coffee keeps the development going.

<a href="https://buymeacoffee.com/flux76"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy me a coffee" height="40"></a>
<a href="https://ko-fi.com/flux76"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support me on Ko-fi" height="40"></a>

## Third-party data and code

- **[SpoolmanDB](https://github.com/Donkie/SpoolmanDB)** (MIT, Copyright (c) 2024 Donkie): the community list of filaments that *Pick from SpoolmanDB* offers. A snapshot ships with the app in `backend/app/spoolmandb_data/`, with its licence next to it; the app never contacts the project. A roll or library entry made from it keeps the filament's SpoolmanDB id as the reference to the source. Refresh it with `python scripts/sync_spoolmandb.py`.
- Everything else that is copied in keeps its licence next to it: the barcode scanner (`frontend/vendor/zxing/`, Apache-2.0), the icons (`frontend/vendor/mdi/`) and the typefaces (`backend/app/fonts/`).

## License

No licence has been chosen yet: all rights reserved.

---

<div align="center">
<sub>Made with ❤️ in the Netherlands by <a href="https://flux76.com">Flux76</a></sub>
</div>
