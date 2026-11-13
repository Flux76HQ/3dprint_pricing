#!/usr/bin/env python3
"""Refresh the SpoolmanDB snapshot that ships with the app (backend/app/spoolmandb_data/).

    python scripts/sync_spoolmandb.py                 # fetch, check, write snapshot.json and LICENSE
    python scripts/sync_spoolmandb.py --out DIR       # write somewhere else (to look at it first)

SpoolmanDB (https://github.com/Donkie/SpoolmanDB, MIT, (c) Donkie) is community data. The app never reads the live site: this script is the
only thing that talks to it, by hand, and what it writes is committed and reviewed like any other change. Every value of the upstream file is
checked and cut to size by `app.spoolmandb.from_upstream` (a row that cannot be used is dropped and counted), the licence is fetched with the
data and refused when it is not the MIT licence of that project, and the output is deterministic (rows by id, one per line), so a refresh is
a readable diff. The upstream commit (`git ls-remote ... HEAD`) is recorded as the reference to the source; it is the head of the default
branch when the data was fetched, which is what the site is built from.
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import spoolmandb as db                                # noqa: E402  (after the path is set)

REPO = "https://github.com/Donkie/SpoolmanDB"
DATA_URL = "https://donkie.github.io/SpoolmanDB/filaments.json"
LICENSE_URL = "https://raw.githubusercontent.com/Donkie/SpoolmanDB/main/LICENSE"
COPYRIGHT = "Copyright (c) 2024 Donkie"
MAX_BYTES = 40 * 1024 * 1024                                   # the published file is about 6 MB
OUT = Path(__file__).resolve().parents[1] / "backend" / "app" / "spoolmandb_data"


class Refused(Exception):
    """Nothing is written; the text says why."""


def fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise Refused(f"not an https address: {url}")
    with urllib.request.urlopen(url, timeout=60) as response:   # noqa: S310 (https only, checked above)
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise Refused(f"{url} is larger than {MAX_BYTES} bytes")
    return body


def check_licence(text: str) -> str:
    """The licence is part of what is copied: it has to be the MIT licence of that project, or the snapshot is not ours to ship."""
    head = text.splitlines()[:5]
    if not text.startswith("MIT License") or not any("Copyright" in line and "Donkie" in line for line in head) or "Permission is hereby granted" not in text:
        raise Refused("the licence of SpoolmanDB is not the MIT licence this snapshot was reviewed under: check it before shipping the data")
    return text if text.endswith("\n") else text + "\n"


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
    if not isinstance(upstream, list):
        raise Refused("the upstream file is not a list of filaments")
    rows, dropped, seen = [], 0, set()
    for entry in upstream:
        row = db.from_upstream(entry)
        if row is None or row[0] in seen:
            dropped += 1
            continue
        seen.add(row[0])
        rows.append(row)
    if len(rows) < 100:
        raise Refused(f"only {len(rows)} usable rows: the upstream format has probably changed")
    rows.sort(key=lambda r: r[0])
    source = {"name": "SpoolmanDB", "url": REPO, "licence": "MIT", "copyright": COPYRIGHT, "fetched": fetched, **({"upstream_head": head} if head else {})}
    lines = ['{"format": ' + json.dumps(db.FORMAT) + ', "format_version": ' + str(db.FORMAT_VERSION) + ',',
             ' "source": ' + json.dumps(source, ensure_ascii=False) + ',',
             ' "columns": ' + json.dumps(list(db.COLUMNS)) + ',',
             ' "rows": [']
    lines += [json.dumps(row, ensure_ascii=False, separators=(",", ":")) + ("," if n < len(rows) else "") for n, row in enumerate(rows, 1)]
    lines.append(']}')
    return "\n".join(lines) + "\n", {"rows": len(rows), "dropped": dropped, "brands": len({r[1] for r in rows})}


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
