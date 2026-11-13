#!/usr/bin/env python3
"""Tests for sync_spoolmandb: what goes in the snapshot, what is refused, and that the shipped files are what the script would write."""
import json
import unittest
from pathlib import Path

import sync_spoolmandb as sync
from app import spoolmandb

DATA = Path(__file__).resolve().parents[1] / "backend" / "app" / "spoolmandb_data"


def entry(n, **values):
    return {"id": f"brand_pla_colour{n}_1000_175_n", "manufacturer": "Brand", "name": f"Colour {n}", "material": "PLA", "weight": 1000, "diameter": 1.75,
            "density": 1.24, "color_hex": "ff0000", "spool_weight": 200, "extruder_temp": 210, "bed_temp": 60, **values}


class SnapshotTestCase(unittest.TestCase):
    def test_the_output_is_one_row_per_line_by_id_and_is_read_back_by_the_app(self):
        text, summary = sync.build([entry(n) for n in (3000, 1000, 2000)] + [entry(n) for n in range(1, 120)], head="a" * 40, fetched="2026-11-13")
        doc = json.loads(text)
        ids = [row[0] for row in doc["rows"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(text.splitlines()), len(ids) + 5)                                   # a diff of a refresh is a diff of rows
        self.assertEqual((doc["source"]["upstream_head"], doc["source"]["fetched"], doc["source"]["licence"]), ("a" * 40, "2026-11-13", "MIT"))
        self.assertEqual((summary["rows"], summary["dropped"]), (len(ids), 0))
        self.assertEqual(sync.build([entry(n) for n in range(1, 120)], head="", fetched="2026-11-13")[0],
                         sync.build(list(reversed([entry(n) for n in range(1, 120)])), head="", fetched="2026-11-13")[0])    # deterministic, whatever the order upstream
        self.assertNotIn("upstream_head", json.loads(sync.build([entry(n) for n in range(1, 120)], head="", fetched="2026-11-13")[0])["source"])

    def test_rows_that_cannot_be_used_are_dropped_and_counted(self):
        upstream = [entry(n) for n in range(1, 150)] + [entry(1), entry(500, density=None), entry(501, id="has space"), "text", None]
        _, summary = sync.build(upstream, head="", fetched="2026-11-13")
        self.assertEqual((summary["rows"], summary["dropped"]), (149, 5))                        # the repeated id counts too

    def test_an_upstream_that_changed_shape_is_refused(self):
        with self.assertRaises(sync.Refused):
            sync.build({"not": "a list"}, head="", fetched="2026-11-13")
        with self.assertRaises(sync.Refused):
            sync.build([entry(n, density=None) for n in range(1, 150)], head="", fetched="2026-11-13")       # nothing is usable: the format probably changed

    def test_only_the_mit_licence_of_that_project_is_accepted(self):
        licence = (DATA / "LICENSE").read_text(encoding="utf-8")
        self.assertEqual(sync.check_licence(licence), licence)
        self.assertTrue(sync.check_licence(licence.rstrip("\n")).endswith("\n"))
        for other in ("GNU GENERAL PUBLIC LICENSE\n\nVersion 3", licence.replace("Donkie", "Someone"), licence.replace("Permission is hereby granted", "All rights reserved")):
            with self.assertRaises(sync.Refused):
                sync.check_licence(other)

    def test_an_address_that_is_not_https_is_not_fetched(self):
        with self.assertRaises(sync.Refused):
            sync.fetch("http://donkie.github.io/SpoolmanDB/filaments.json")

    def test_the_shipped_snapshot_is_what_the_script_writes(self):
        """It is the script's own output: same columns and format, one row per line, sorted by id, each row exactly as `from_upstream` makes it."""
        text = (DATA / "snapshot.json").read_text(encoding="utf-8")
        doc = json.loads(text)
        self.assertEqual((doc["format"], doc["format_version"], tuple(doc["columns"])), (spoolmandb.FORMAT, spoolmandb.FORMAT_VERSION, spoolmandb.COLUMNS))
        ids = [row[0] for row in doc["rows"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(text.splitlines()), len(ids) + 5)
        data = spoolmandb.load()
        self.assertEqual(len(data["rows"]), len(ids))                                             # and the app accepts every row of it
        self.assertEqual(spoolmandb.document_text([list(r.values()) for r in data["rows"]], data["source"]), text)       # the app's own sync writes exactly this format
        self.assertTrue((DATA / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
