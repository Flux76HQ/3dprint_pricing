# Performance: what was measured, what was changed, and what keeps it that way

This app's performance work follows App-Guidance's
[`shared/guidelines/performance-playbook.md`](https://github.com/Flux76HQ/App-Guidance/blob/main/shared/guidelines/performance-playbook.md):
measure the slow path on data of a stated size, fix it with the smallest technique that works, pin the fix with a test that fails
when it is undone, measure again, and write the numbers down with a date. This file is where the numbers are written down.
`AGENTS.md` section 6i points here.

## How the numbers are made

`python scripts/perf_baseline.py` builds a throwaway database from the demo data of `scripts/generate_screenshots.py`, copied until
it has the size asked for, starts Gunicorn with the flags of `deploy/entrypoint.sh` (read from that file) and measures:

- the API over one kept-alive connection;
- a real browser (Chromium through Playwright, service worker allowed) opening the app on the model list, with an empty cache and
  again with a filled one, and opening the model editor. Requests and bytes are counted in Gunicorn's access log, so a request made
  by the service worker counts like one made by the page;
- the server under load: eight clients at once, and a small read while backups are being downloaded.

Read the numbers with these limits in mind:

- **The data is synthetic, not the owner's.** 300 models, 600 orders, 200 rolls, 150 customers and 240 product images are a guess
  at a busy small business. A product image here is a 1024 pixel JPEG of about 179 kB; a real one may be up to 2048 pixels and
  several times that, so the image numbers are on the low side.
- **Everything runs on one machine over the loopback interface.** There is no network delay, so a time in milliseconds says little
  about a phone on mobile data; the *requests* and *bytes* are what carries over. The machine is a 4 CPU cloud container
  (Python 3.12.3, SQLite 3.45.1), not a home server.
- **"First request after a start" is not a cold disk**: the database had just been written, so the operating system had it in
  memory. A cold file cache was not measured.
- Timings move by 10 to 20 percent between runs. Compare a before and an after from the same machine and the same day only.

## Baseline, 2026-11-11

Commit `78b9ce2` (`beta` before any of this work), `gunicorn --workers 2 --timeout 120` (sync workers), database file 45.2 MB.

| What | Result |
|---|---|
| `GET /api/projects`, first request after a start | 24.5 ms, 389 kB (not compressed) |
| `GET /api/projects`, after that | median 17.3 ms, p95 31.2 ms |
| `GET /api/orders` | median 57.2 ms, p95 87.5 ms, 226 kB |
| Opening the app on the model list, empty browser cache | list visible after 405 ms; 87 requests reach the server, 5044 kB: 59 files (709 kB), 6 API (390 kB), 22 images (3945 kB) |
| Opening it again, filled cache and a service worker | list visible after 517 ms; 61 requests, 4340 kB: 35 files (34 answered 304), 4 API (390 kB), 22 images (3945 kB) |
| Opening the model editor from the list | visible after 115 ms; 12 API requests, 122 kB |
| The editor's 11 GETs replayed over 6 connections | median 37.2 ms, p95 48.2 ms, 121 kB |
| 8 clients asking for `/api/projects` at once | 61.5 requests/s, median 127.7 ms, p95 193.4 ms |
| `GET /api/printers` while 1 backup download (1.3 s) runs | median 5.5 ms, slowest 337 ms |
| `GET /api/printers` while 2 backup downloads run | median 5.4 ms, slowest 1218 ms |

What the baseline showed, against what reading the code had suggested:

- **The product images were the largest cost by far**, as expected: every visit to the list fetched every visible cover again in
  full (3.9 MB of the 4.3 MB of a repeat visit), because they were answered `no-store`.
- **Every launch revalidated 35 files** although each URL already named its release. Each revalidation is cheap for the server
  (5 kB in total) but is a round trip, and on the first visit the service worker fetched all the scripts a second time under URLs
  the page never uses (59 file requests for about 33 files).
- **Nothing was compressed**: 709 kB of files and 389 kB for the list of models.
- **The server itself is not slow.** The list of 300 models takes 17 ms and the editor's requests together 37 ms. Bundling the
  editor's requests and paging the lists are about round trips and bytes, not about server time.
- **`GET /api/orders` is slower than `GET /api/projects`** (57 ms against 17 ms). Reading the code had not suggested that.
- **One long request does block others**: a read waited up to 0.34 s behind one backup (the write lock every transaction takes) and
  up to 1.2 s behind two (both workers busy).

## 1. Files and pictures kept by the browser, compression (2026-11-11)

Same machine, same data, same day; the working tree of the pull request on top of `78b9ce2`.

| What | Before | After |
|---|---|---|
| Opening the app again (filled cache): requests that reach the server | 61 | **7** (the page, the worker, one icon, 4 API) |
| Opening the app again: bytes | 4340 kB | **23 kB** |
| Opening the app again: list visible (loopback) | 517 ms | 279 ms |
| First visit (empty cache): requests | 87 | 64 |
| First visit: bytes | 5044 kB | **377 kB** (files 709 to 187 kB, covers 3945 to 168 kB, API 390 to 22 kB) |
| First visit: list visible (loopback) | 405 ms | 352 ms |
| `GET /api/projects`: bytes | 389 kB | 22 kB (gzip) |
| `GET /api/projects`: time | median 17.3 ms | median 20.2 ms |
| Opening the model editor: API bytes | 122 kB | 20 kB |
| Serving all 28 script modules, in the app (no network) | 21.2 ms | 11.6 ms |

What changed:

- **A URL of the running release is `immutable`** (`backend/app/static_files.py`). Scripts, the style sheet, icons and now the
  language files carry `?v=<version>-<commit>`; such a URL is answered `public, max-age=31536000, immutable`. The page, `sw.js`, a
  URL without a release, a URL of another release and every file of a development build (`dev`) stay `no-cache`.
- **Stamping and compressing happen once per process and file**, not per request. The memo is checked against the file's size and
  modification time.
- **The service worker answers this release's files from its cache** and has one cache per release, so the caches of earlier
  releases are removed when a new worker activates. The page itself still always comes from the network, so a new release shows on
  the very next load. Its list now holds every module and is fetched under the URLs the page uses.
- **A stored product image is `private, max-age=31536000, immutable`** with its id as ETag (`http.keep_forever`); the list of
  models shows a 192 pixel version (`GET /api/project-images/<id>/thumb`) that is made when asked for and not stored.
- **Text is gzipped by the app**: its own files once (level 9), a JSON answer of 1 kB or more per request (level 4). The documented
  set-up names no particular proxy and the app also runs without one, so nothing in front of it could be relied on.

What it costs, and what was decided:

- **Compressing a JSON answer costs server time**: about 2 to 3 ms on the 389 kB list (level 4; level 9 saves 3 kB more for twice
  the time). On a local network that is a small loss, over the internet a large gain.
- **A thumbnail costs 4 ms to make from a 1024 pixel image and 9 ms from a 2048 pixel one** (measured), once per image and browser.
  A stored thumbnail (a column, a migration, backup handling) was therefore left out.
- **A kept picture can be shown without a session on the device that kept it**, until the browser drops it; it is `private`, so no
  proxy keeps it. A deleted picture likewise stays in that browser's cache. Nothing else under `/api/` may be kept.
- **A self-built image must be given its commit** (`GIT_COMMIT`): two different builds with the same version and commit would be
  mixed by a browser that kept the first. Without `GIT_COMMIT` the build is `dev` and nothing is kept, as before.

What guards it:

- `backend/tests/test_static_build.py`: only a URL of the running release is kept; the page and the worker never are; a development
  build never is; a file is stamped and compressed once and read again when it changes; text is compressed and has a validator per
  form; no path leaves the static folder; the worker's list equals the files on disk.
- `scripts/test_service_worker.mjs` (job `frontend-syntax`): runs the worker with a counting cache and network.
- `backend/tests/test_ai_images.py`: a stored picture is kept and everything else under `/api/` is not, a refusal is never kept,
  the thumbnail is small, and no code rewrites the bytes of a stored picture.
- `backend/tests/test_responses.py`: a JSON list is compressed, a short answer and a download are not, a download is never kept.

Each of these was checked by breaking what it guards (17 changes, each made a test fail).

**Checked by hand, not by a test in CI:** in a real browser, after the server was replaced by another build, the next load ran the
new build with no script of the old one, the old cache was gone after that load, and with the server stopped the shell still
started from the worker's cache.

## Not done yet

In the order of the work plan; each gets its own pull request with its own before and after.

- Gunicorn threads, read transactions that do not take the write lock, and the SQLite settings. The baseline's last two rows are
  what they are judged by.
- Indexes for the queries that scan, with a test that asserts their plans.
- Smaller answers for the lists, fewer requests for the model editor, and why `/api/orders` takes 57 ms.
- Paging the lists.
