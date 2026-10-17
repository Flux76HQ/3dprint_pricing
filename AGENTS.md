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
  round up, take the VAT out, and the margin becomes a minimum (the loop in `calculate` exists
  because cent-rounding the VAT can otherwise land a cent under that minimum).
- A saved project stores the prices as they were when saved (`projects.data`). Do not make a
  project read live prices from spools, printers or tariffs: that rewrites history.
- `backend/tests/test_calc.py` pins the owner's real spreadsheet example (total 2,74). If that test
  has to change, the calculation changed: say so in the pull request.
- WebAuthn is hand-rolled (`backend/app/webauthn.py`, ES256 only). Do not widen what is accepted
  without a test that fails first.
- Uploaded print files are untrusted. All parsing goes through `backend/app/printfile.py`
  (defusedxml, size caps, readable `PrintFileError`s); never open an upload with another parser. A
  sliced 3MF is exact, geometry is only an estimate, and print time is never derived from geometry.
  Test with the synthetic fixtures in `backend/tests/printfiles.py`; a real slicer file is the
  final check, since the 3MF/slice_info layout is the slicer's, not ours.
- Uploads live under `UPLOAD_DIR` (`/data/uploads`, mounted from `DATA_PATH/app`), never in the
  image. Stored names are generated; the original filename is only a download name.
- Third-party browser code is vendored under `frontend/vendor/` (unmodified, with its licence and a
  README saying how to update), never loaded from a CDN: the CSP only allows scripts from this origin.
  Currently only ZXing, for barcode scanning where the browser has no `BarcodeDetector`.
- UI text is Dutch. Build DOM with the `h()` helper and `textContent`; never `innerHTML` with data
  (the CSP also forbids inline script and style).

## 2. Versioning discipline

- Version source of truth is the `VERSION` file (`MAJOR.MINOR.PATCH`).
- Changes touching runtime/build/deploy/CI surfaces **must** bump it.
- Protected paths: `backend/`, `frontend/`, `deploy/`, `scripts/`, `.github/workflows/`,
  `.github/copilot-instructions.md`, `Dockerfile`, `docker-compose.yml`, `docker-compose.build.yml`, `.env.example`.
- Documentation-only edits (`*.md`, `*.txt`) are exempt.
- Bump with `python scripts/bump_version.py` (patch by default).

## 3. Local enforcement and CI controls

- Activate hooks once per clone: `python scripts/setup_hooks.py`.
- Every MUST rule needs an automated enforcement point (CI or hook).
- CI jobs on every pull request into `main`:

  | Job name | What it checks |
  |---|---|
  | `enforce-version-bump` | protected paths changed without a higher `VERSION` |
  | `enforce-version-bump-on-merge` | the same, at merge, against the previous tip of `main` |
  | `agent-instructions-lint` | that this file stays canonical and unduplicated |
  | `backend-tests` | calculator, WebAuthn, migrations, API; fails if any test was skipped |
  | `frontend-syntax` | every frontend module parses; the manifest is valid JSON |
  | `docker-build` | the image builds and both compose files are valid for `.env.example` |

- A control has to be findable on the pull request under the name a document cites it by.
- Migrations are forward-only: never edit an applied `NNNN_*.sql`; add a new one. The runner
  refuses to start on a changed checksum.

## 4. Secrets and configuration hygiene

- Never commit `.env` or real secrets; only `.env.example` is tracked.
- Keep `.env.example` complete and safe (placeholders only). A new environment variable is added
  to `backend/app/config.py`, `.env.example` and the README table in the same change.
- Rotate `SESSION_SECRET` and `SETUP_CODE` before any public release.

## 5. Branch topology and pull request workflow

- The **integration branch** for this repository is `main`. Set GitHub's Default branch to match.
- Develop on a feature branch off `main`; never commit directly to it.
- Give a new feature its own worktree and its own agent session.
- Check for an existing open PR before opening a new one; never push without a PR; never add
  commits to a branch whose PR is already merged — rebase and open a new one.
- Carry your own PR to merge: watch it, drive failing checks green, merge at all green without
  asking again.

## 6. Testing

- Backend: `cd backend && PYTHONPATH=. python -m pytest -q`. Database tests need PostgreSQL:
  set `TEST_DATABASE_URL`, or run as root with the system PostgreSQL installed and the fixtures
  start a throwaway cluster.
- `backend/tests/fake_authenticator.py` is a software passkey; use it for any auth test.
- Test a guard by breaking what it guards before trusting it.

## 7. Work done in one client leaves the other clients correct

A change to a working convention goes in this file, never in a client's entry file. If a client
surface is added (a skill, an MCP server), add its row to the client-surface table above in the
same commit. `agent-instructions-lint` checks this.

## 8. Commit checklist

- [ ] Non-doc changes to protected paths include a version bump.
- [ ] No secrets or `.env` files are staged.
- [ ] README operational sections are updated when run/deploy/backup behaviour changed.
- [ ] Tests added or updated; `pytest` passes.
