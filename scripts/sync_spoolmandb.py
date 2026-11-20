#!/usr/bin/env python3
"""Refresh the SpoolmanDB snapshot that ships with the app (backend/app/spoolmandb_data/).

    python scripts/sync_spoolmandb.py                 # fetch, check, write snapshot.json and LICENSE
    python scripts/sync_spoolmandb.py --out DIR       # write somewhere else (to look at it first)

SpoolmanDB (https://github.com/Donkie/SpoolmanDB, MIT, (c) Donkie) is community data. What this writes is the snapshot that ships with the app, committed
and reviewed like any other change; an installation can also refresh its own copy with the button in Settings -> Filaments (`spoolmandb.run_sync`), which
does not touch these files. Every value of the upstream file is checked and cut to size by `app.spoolmandb.from_upstream` (a row that cannot be used is
dropped and counted), the licence is fetched with the data and refused when it is not the MIT licence of that project, and the output is deterministic
(rows by id, one per line), so a refresh is a readable diff. The upstream commit (`git ls-remote ... HEAD`) is recorded as the reference to the source; it is the head of the default
branch when the data was fetched, which is what the site is built from.
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import spoolmandb as db                                # noqa: E402  (after the path is set)

Refused = db.Refused                                            # nothing is written; the text says why
REPO, DATA_URL, LICENSE_URL, COPYRIGHT, MAX_BYTES = db.REPO, db.SYNC_URL, db.LICENSE_URL, db.COPYRIGHT, db.MAX_DOWNLOAD_BYTES
OUT = Path(__file__).resolve().parents[1] / "backend" / "app" / "spoolmandb_data"
check_licence = db.check_licence


def fetch(url: str) -> bytes:
    """The body of one of the project's two addresses; https only, no redirect followed (the same code the app's own sync button uses)."""
    return db.fetch(url, MAX_BYTES)[0]


def upstream_head() -> str:
    """The commit the default branch points at, or '' when git cannot say (the snapshot then names the date only)."""
    try:
        out = subprocess.run(["git", "ls-remote", REPO + ".git", "HEAD"], capture_output=True, text=True, timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    sha = out.split()[0] if out.split() else ""
    return sha if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else ""


def build(upstream, *, head: str, fetched: str) -> tuple[str, dict]:
    """(the text of snapshot.json, a summary): the usable rows by id, one per line."""
    rows, dropped = db.rows_of(upstream)
    source = {"name": "SpoolmanDB", "url": REPO, "licence": "MIT", "copyright": COPYRIGHT, "fetched": fetched, **({"upstream_head": head} if head else {})}
    return db.document_text(rows, source), {"rows": len(rows), "dropped": dropped, "brands": len({r[1] for r in rows})}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help="the folder to write snapshot.json and LICENSE in")
    args = parser.parse_args(argv)
    try:
        licence = check_licence(fetch(LICENSE_URL).decode("utf-8"))
        text, summary = build(json.loads(fetch(DATA_URL)), head=upstream_head(), fetched=date.today().isoformat())
    except (Refused, OSError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "snapshot.json").write_text(text, encoding="utf-8")
    (args.out / "LICENSE").write_text(licence, encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
