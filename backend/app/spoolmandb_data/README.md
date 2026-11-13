# SpoolmanDB snapshot

`snapshot.json` is a copy of [SpoolmanDB](https://github.com/Donkie/SpoolmanDB), the community-kept list of filaments (brand, name,
material, weight, diameter, colour, density, empty-spool weight, temperatures). `LICENSE` is its licence, copied verbatim: SpoolmanDB is
**MIT**, `Copyright (c) 2024 Donkie`, and that licence asks for the notice and the text to travel with every copy.

It is used by `backend/app/spoolmandb.py`: the picker of a new roll's form (*Kies uit SpoolmanDB*) fills in the form from a row, and
`backend/app/spoolman.py` sends the density and the empty-spool weight, with the row's id as `external_id`, when a roll or library entry that
came from here is pushed to Spoolman. The screen that offers it names the source and links to it.

This file is what the app starts with, so it works offline and from the first start. An administrator can fetch a newer list with the *Sync now*
button under *Settings → Filaments* (at most once a day, `spoolmandb.run_sync`); that copy is kept in the database (not in a backup) and is used instead of
this one. The button is the only moment the app contacts the project, at two fixed addresses, and it checks the licence and every row again.

## Refreshing the snapshot in the repository

```bash
python scripts/sync_spoolmandb.py
```

Fetches the published `filaments.json` and the licence, checks every value (`spoolmandb.from_upstream`), refuses a licence that is not the MIT
licence of that project, and rewrites `snapshot.json` and `LICENSE` deterministically (rows by id, one per line), so the change is a readable
diff. `source.upstream_head` is the commit the project's default branch pointed at when it was fetched; `source.fetched` is the date. Commit
the result in its own pull request.

A row that disappears from a refresh leaves the rolls and library entries made from it as they are (they keep the id as a reference); only
the density and spool weight sent to Spoolman can then no longer be looked up, and a rough density per material is used instead.
