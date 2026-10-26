#!/usr/bin/env python3
"""Put the filaments of a contribution (an issue made by *Settings -> Filaments -> Bijdragen*) in library/filaments.json.

    python scripts/apply_library_contribution.py library/filaments.json issue-body.txt

The issue text is untrusted: it is only ever read as data here (never executed or interpolated into a shell line), checked with the same rules as
typing a filament in or importing a file (`filament_library._parse_library`), and recognised against the library with the one rule that says what
the same filament is (`filament_library.keys`). A contribution only *adds* or *completes*: a filament that is already in the file (the same SKU, barcode
or filament ID, or the same name, weight and diameter) only gets the fields that are blank there and filled in by the contribution, and is never
overwritten; the notes are dropped. New entries go at the end, in the layout of the export. Prints a JSON summary (`added`, `completed`, `skipped`, `names`, `completed_names`); exits 1 with the reason in Dutch and English when it refuses.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import filament_library as lib                        # noqa: E402  (after the path is set)
from app.http import ApiError                                  # noqa: E402
from app.i18n import Localized, render                         # noqa: E402

MAX_BODY_BYTES = 512 * 1024
MAX_ENTRIES = 200                                             # a contribution is a handful of filaments, not a copy of someone's library


class Refused(Exception):
    """A contribution that is not taken; the text is what the person who sent it is told."""


def extract(body: str) -> dict:
    """The JSON of an issue-form field: from the first `{` to the last `}` (a code fence around it is not part of it)."""
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise Refused("De bijdrage is te groot. / The contribution is too large.")
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        raise Refused("Geen JSON gevonden in de bijdrage. / No JSON found in the contribution.")
    try:
        return json.loads(body[start:end + 1])
    except ValueError:
        raise Refused("De bijdrage is geen geldige JSON. / The contribution is not valid JSON.") from None


def plain(text: str, limit: int = 120) -> str:
    """Text that came from the contribution, made safe to show in a comment or pull request: one line, no backticks (so it can sit in a code span)."""
    return " ".join(str(text).replace("`", "'").split())[:limit]


def _both(message) -> str:
    return f"{render(message, 'nl')} / {render(message, 'en')}"


def parse(doc) -> list[dict]:
    """The entries of a contribution, checked as an import is."""
    try:
        items = lib._parse_library(doc)
    except (ApiError, Localized) as exc:
        raise Refused(plain(_both(exc.msg), 400)) from None
    if len(items) > MAX_ENTRIES:
        raise Refused(f"Een bijdrage heeft hoogstens {MAX_ENTRIES} filamenten. / A contribution has at most {MAX_ENTRIES} filaments.")
    return items


def entry(item: dict) -> dict:
    """An entry in the layout of the export: every field, numbers as numbers, without the notes."""
    full = {**lib.BLANK, **lib.DEFAULTS, **item, "notes": ""}
    return {key: lib._plain(full[key]) for key in lib.FIELDS}


def apply(library_doc: dict, items: list[dict]) -> dict:
    """Add what the library lacks to `library_doc` (changed in place); returns the summary. A filament that is there already (see `keys`) is
    only *completed*: the fields in `lib.FILLABLE` and the `price` that are blank in the file and filled in by the contribution; nothing that
    is filled in is overwritten, and a completion that would make the entry a copy of another one is left out."""
    filaments = library_doc["filaments"]
    full_rows = [{**lib.BLANK, **lib.DEFAULTS, **row} for row in filaments]
    index = lib.Index(full_rows)
    row_of = {id(full): row for full, row in zip(full_rows, filaments)}           # the entry of the file that an indexed one stands for
    names, completed, skipped = [], [], 0
    for item in items:
        full = {**lib.BLANK, **lib.DEFAULTS, **item}
        other = index.find(full)
        if other is None:
            new = entry(item)
            index.add({**lib.BLANK, **lib.DEFAULTS, **new})
            filaments.append(new)
            names.append(plain(lib.name_of(new)))
            continue
        fills = {key: full[key] for key in (*lib.FILLABLE, "price") if lib._blank(other[key]) and not lib._blank(full.get(key))}
        if not fills or index.clash(other, {**other, **fills}):
            skipped += 1
            continue
        index.drop(other)
        other.update(fills)
        index.add(other)
        row_of[id(other)].update({key: lib._plain(value) for key, value in fills.items()})
        completed.append(plain(f"{lib.name_of(other)} ({', '.join(fills)})"))
    return {"added": len(names), "completed": len(completed), "skipped": skipped, "names": names, "completed_names": completed}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    library_path, body_path = Path(argv[1]), Path(argv[2])
    try:
        items = parse(extract(body_path.read_text(encoding="utf-8", errors="replace")))
        library_doc = json.loads(library_path.read_text(encoding="utf-8"))
        summary = apply(library_doc, items)
    except Refused as exc:
        print(exc, file=sys.stderr)
        return 1
    if summary["added"] or summary["completed"]:
        library_path.write_text(json.dumps(library_doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
