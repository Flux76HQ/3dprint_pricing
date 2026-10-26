#!/usr/bin/env python3
"""Tests for apply_library_contribution: what a contribution may add to library/filaments.json, and what it is refused for."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import apply_library_contribution as contribution

LIBRARY = Path(__file__).resolve().parents[1] / "library" / "filaments.json"
NEW = {"brand": "Sunlu", "product_type": "Basic", "material": "PETG", "colour": "Zwart", "roll_weight_g": 1000, "diameter_mm": 1.75,
       "barcode": "8712345678901", "price": 14.5, "notes": "mijn eigen tekst"}


def issue(*filaments, **extra) -> str:
    """The text of an issue as the form makes it: a heading and the field in a code fence."""
    doc = {"format": "printpricing-filament-library", "format_version": 1, "filaments": list(filaments), **extra}
    return "### Bijdrage\n\n```json\n" + json.dumps(doc) + "\n```\n"


class ContributionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.library = self.dir / "filaments.json"
        shutil.copy(LIBRARY, self.library)

    def run_main(self, body: str) -> tuple[int, str, str]:
        path = self.dir / "body.txt"
        path.write_text(body, encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = contribution.main(["x", str(self.library), str(path)])
        return code, out.getvalue(), err.getvalue()

    def filaments(self) -> list[dict]:
        return json.loads(self.library.read_text(encoding="utf-8"))["filaments"]


class Adding(ContributionTestCase):
    def test_a_new_filament_goes_at_the_end_in_the_layout_of_the_export_without_notes(self):
        before = self.filaments()
        code, out, _ = self.run_main(issue(NEW))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"added": 1, "completed": 0, "skipped": 0, "names": ["Sunlu · Basic · Zwart · PETG"], "completed_names": []})
        after = self.filaments()
        self.assertEqual(after[:-1], before)
        self.assertEqual(list(after[-1]), list(before[0]))                               # the same fields in the same order
        self.assertEqual((after[-1]["notes"], after[-1]["price"], after[-1]["barcode"]), ("", 14.5, "8712345678901"))
        text = self.library.read_text(encoding="utf-8")
        self.assertEqual(text, json.dumps(json.loads(text), ensure_ascii=False, indent=1) + "\n")

    def test_a_filament_that_is_there_already_is_left_alone_whatever_the_contribution_says(self):
        known = self.filaments()[0]
        offer = {**known, "colour": "Andere naam", "price": 1, "notes": "x"}              # the same SKU under another name and price
        code, out, _ = self.run_main(issue(offer))
        self.assertEqual((code, json.loads(out)["added"], json.loads(out)["skipped"]), (0, 0, 1))
        self.assertEqual(self.filaments()[0], known)

    def test_a_known_filament_only_gets_the_blank_fields_filled_in(self):
        known = {**self.filaments()[0], "print_temp_c": None, "bed_temp_c": None, "colour_hex": "#111111", "price": 19.32}
        doc = json.loads(self.library.read_text(encoding="utf-8"))
        doc["filaments"][0] = known
        self.library.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        offer = {**known, "print_temp_c": 220, "bed_temp_c": 55, "colour_hex": "#999999", "price": 25, "colour": "Andere naam", "notes": "x"}
        code, out, _ = self.run_main(issue(offer))
        summary = json.loads(out)
        self.assertEqual((code, summary["added"], summary["completed"], summary["skipped"]), (0, 0, 1, 0))
        self.assertIn("print_temp_c, bed_temp_c", summary["completed_names"][0])
        after = self.filaments()[0]
        self.assertEqual((after["print_temp_c"], after["bed_temp_c"]), (220, 55))                    # blanks are filled
        self.assertEqual((after["colour_hex"], after["price"], after["colour"], after["notes"]), ("#111111", 19.32, known["colour"], ""))  # the rest stays
        self.assertEqual(list(after), list(known))                                                   # in the layout of the file

    def test_a_completion_that_would_make_a_copy_is_left_out(self):
        a = {**NEW, "colour": "A", "barcode": "A-1", "sku": ""}
        b = {**NEW, "colour": "B", "barcode": "", "sku": "S-2"}
        doc = {"format": "printpricing-filament-library", "format_version": 1, "filaments": [contribution.entry(a), contribution.entry(b)]}
        self.library.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        code, out, _ = self.run_main(issue({**a, "sku": "S-2"}))                           # A, with the SKU that is B's: A would become a copy of B
        self.assertEqual((code, json.loads(out)["completed"], json.loads(out)["skipped"]), (0, 0, 1))
        self.assertEqual(self.filaments()[0]["sku"], "")

    def test_the_same_filament_twice_in_one_contribution_is_added_once(self):
        code, out, _ = self.run_main(issue(NEW, {**NEW, "colour": " zwart "}))
        self.assertEqual((code, json.loads(out)["added"], json.loads(out)["skipped"]), (0, 1, 1))

    def test_an_entry_without_the_defaults_the_app_leaves_out_gets_them_back(self):
        slim = {key: value for key, value in NEW.items() if key not in ("roll_weight_g", "diameter_mm")}      # as the app writes a 1000 g, 1.75 mm roll
        code, _, _ = self.run_main(issue(slim))
        self.assertEqual(code, 0)
        self.assertEqual((self.filaments()[-1]["roll_weight_g"], self.filaments()[-1]["diameter_mm"]), (1000.0, 1.75))

    def test_names_that_end_up_in_a_pull_request_are_one_line_without_backticks(self):
        _, out, _ = self.run_main(issue({**NEW, "brand": "Evil `@owner`\nSecond line", "barcode": ""}))
        [name] = json.loads(out)["names"]
        self.assertNotIn("`", name)
        self.assertNotIn("\n", name)

    def test_the_file_is_not_written_when_nothing_is_new(self):
        before = self.library.read_bytes()
        self.run_main(issue(self.filaments()[0]))
        self.assertEqual(self.library.read_bytes(), before)

    def test_the_result_is_still_a_library_the_app_accepts(self):
        self.run_main(issue(NEW))
        doc = json.loads(self.library.read_text(encoding="utf-8"))
        self.assertIsNone(contribution.lib.first_clash(contribution.parse(doc)))


class Refusing(ContributionTestCase):
    def refused(self, body: str, fragment: str) -> None:
        before = self.library.read_bytes()
        code, out, err = self.run_main(body)
        self.assertEqual((code, out), (1, ""))
        self.assertIn(fragment, err)
        self.assertEqual(self.library.read_bytes(), before)

    def test_text_without_json(self):
        self.refused("### Bijdrage\n\nhallo", "Geen JSON")

    def test_json_that_is_not_valid(self):
        self.refused("{ nope }", "geen geldige JSON")

    def test_a_file_that_is_not_a_library(self):
        self.refused('{"format": "printpricing-backup"}', "geen filamentbibliotheek")

    def test_an_entry_the_app_would_refuse_names_its_line_and_the_reason(self):
        self.refused(issue(NEW, {"brand": "x", "roll_weight_g": 0}), "Regel 2")

    def test_too_many_entries(self):
        many = [{**NEW, "colour": f"Kleur {n}", "barcode": ""} for n in range(contribution.MAX_ENTRIES + 1)]
        self.refused(issue(*many), "hoogstens")

    def test_a_body_that_is_too_large(self):
        self.refused(issue(NEW, padding="x" * contribution.MAX_BODY_BYTES), "te groot")

    def test_a_newer_format(self):
        self.refused(issue(NEW).replace('"format_version": 1', '"format_version": 99'), "nieuwer")


if __name__ == "__main__":
    unittest.main()
