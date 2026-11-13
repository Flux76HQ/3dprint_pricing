"""SpoolmanDB: the snapshot that ships with the app, the picker's routes, and what picking from it does to the library, the scan list and Spoolman.

The names are real ones: Bambu Lab's colours as the Dutch web shop spells them ("Geel", "Pompoenoranje") and as SpoolmanDB does ("Yellow", "Pumpkin Orange")."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest
import requests

from app import filament_library, spoolman, spoolmandb
from app.spoolmandb import from_upstream
from tests.test_auth_api import H
from tests.test_domain_api import make, owner  # noqa: F401  (fixture)
from tests.test_spoolman import push, server, stand_in  # noqa: F401  (fixtures)
from tests.test_users import join_with_passkey, sql

YELLOW = "bambulab_pla_yellow_1000_175_n"
CHARCOAL = "bambulab_pla_mattecharcoal_1000_175_n"
GEEL = {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Geel", "roll_weight_g": 1000, "diameter_mm": "1.75", "price": "19.32",
        "print_temp_c": 215}
ROLL = {"brand": "Bambu Lab", "material": "PLA", "colour": "Yellow", "roll_weight_g": 1000, "diameter_mm": "1.75", "price": "20", "remaining_g": 1000,
        "spoolmandb_id": YELLOW, "add_to_library": True}


def rows(owner, brand="Bambu Lab", material="PLA"):
    return {r["id"]: r for r in owner.get(f"/api/spoolmandb/filaments?brand={brand}&material={material}").get_json()["filaments"]}


def library(owner):
    return owner.get("/api/filament-library").get_json()


@pytest.fixture(autouse=True)
def fresh_snapshot():
    """Nothing a test synced or loaded is left in the process for the next one (the copy in use is kept per process, the database is per test)."""
    spoolmandb.reset()
    yield
    spoolmandb.reset()


# --- the snapshot ------------------------------------------------------------------------------------------------

def test_the_shipped_snapshot_is_valid_and_names_its_source(fresh_snapshot):
    data = spoolmandb.load()
    source = data["source"]
    assert len(data["rows"]) > 9000 and len({r["brand"] for r in data["rows"]}) > 80
    assert source["name"] == "SpoolmanDB" and source["licence"] == "MIT" and source["url"].startswith("https://github.com/Donkie/SpoolmanDB")
    assert source["copyright"].startswith("Copyright") and source["fetched"][:2] == "20"
    licence = (spoolmandb.DATA_DIR / "LICENSE").read_text(encoding="utf-8")                  # the MIT licence asks for its text to travel with the data
    assert licence.startswith("MIT License") and source["copyright"] in licence and "Permission is hereby granted" in licence
    assert spoolmandb.find(YELLOW)["density"] == 1.24 and spoolmandb.find("no such id") is None


def test_a_row_is_checked_and_cut_to_size():
    good = {"id": "x_pla_black_1000_175_n", "manufacturer": "X", "name": "Black", "material": "PLA", "weight": 1000.0, "diameter": 1.75, "density": 1.24,
            "color_hex": "1A1A1AFF", "spool_weight": 220, "extruder_temp": 215, "bed_temp": 60}
    assert from_upstream(good) == ["x_pla_black_1000_175_n", "X", "Black", "PLA", 1000, 1.75, "1a1a1a", 1.24, 220, 215, 60]       # the alpha channel goes, 1000.0 is 1000
    assert from_upstream({**good, "color_hex": None, "color_hexes": ["00ff00", "ff0000"]})[6] == "00ff00"              # a multi-colour filament shows its first colour
    assert from_upstream({**good, "color_hex": "zz"})[6] == "" and from_upstream({**good, "name": "A\x00B\n" + "c" * 200})[2] == "A B " + "c" * 76
    assert from_upstream({**good, "spool_weight": None, "extruder_temp": "hot", "bed_temp": 9999})[8:] == [None, None, None]     # optional values that make no sense are left out
    for broken in ({**good, "id": "has a space"}, {**good, "id": ""}, {**good, "weight": 0}, {**good, "diameter": 9}, {**good, "density": None},
                   {**good, "manufacturer": ""}, {**good, "material": 5}, "text", None, []):
        assert from_upstream(broken) is None


def test_a_snapshot_that_is_not_what_is_expected_is_refused(owner, monkeypatch, tmp_path, fresh_snapshot):
    bad = tmp_path / "snapshot.json"
    bad.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    monkeypatch.setattr(spoolmandb, "SNAPSHOT", bad)
    spoolmandb.reset()
    with pytest.raises(ValueError):
        spoolmandb.load()
    assert spoolmandb.find(YELLOW) is None                                              # the library and Spoolman push then just have no SpoolmanDB
    assert owner.get("/api/spoolmandb").status_code == 503 and owner.get("/api/spoolmandb/filaments?brand=X").status_code == 503


def test_a_snapshot_is_only_read_when_every_row_is_clean_and_unique(monkeypatch, tmp_path, fresh_snapshot):
    """What is in the file is what `from_upstream` would have made of it, and no id is there twice: the file is checked, not trusted."""
    row = ["a_pla_black_1000_175_n", "A", "Black", "PLA", 1000, 1.75, "000000", 1.24, 220, 215, 60]

    def attempt(*rows):
        path = tmp_path / "snapshot.json"
        path.write_text(json.dumps({"format": spoolmandb.FORMAT, "format_version": 1, "columns": list(spoolmandb.COLUMNS), "rows": list(rows),
                                    "source": {"name": "SpoolmanDB", "url": "https://github.com/Donkie/SpoolmanDB", "licence": "MIT",
                                               "copyright": "Copyright (c) 2024 Donkie", "fetched": "2026-11-13"}}), encoding="utf-8")
        monkeypatch.setattr(spoolmandb, "SNAPSHOT", path)
        spoolmandb.reset()
        return spoolmandb.load()

    assert attempt(row)["by_id"]["a_pla_black_1000_175_n"]["density"] == 1.24
    with pytest.raises(ValueError, match="row 2"):
        attempt(row, row)                                                                   # the same id twice
    with pytest.raises(ValueError, match="row 1"):
        attempt([*row[:6], "FFFFFF", *row[7:]])                                             # not as `from_upstream` writes it (upper case)
    with pytest.raises(ValueError, match="row 1"):
        attempt(row[:-1])                                                                   # a column short


# --- the routes of the picker ------------------------------------------------------------------------------------

def test_the_routes_need_a_session(app):
    anonymous = app.test_client()
    assert anonymous.get("/api/spoolmandb").status_code == 401 and anonymous.get("/api/spoolmandb/filaments?brand=Bambu Lab").status_code == 401


def test_the_overview_names_the_source_and_lists_brands_with_their_materials(owner):
    overview = owner.get("/api/spoolmandb").get_json()
    assert overview["source"]["licence"] == "MIT" and overview["source"]["url"].startswith("https://")
    bambu = next(b for b in overview["brands"] if b["name"] == "Bambu Lab")
    assert "PLA" in bambu["materials"] and bambu["count"] > 200
    assert [b["name"].lower() for b in overview["brands"]] == sorted(b["name"].lower() for b in overview["brands"])


def test_a_filament_that_is_not_known_fills_in_what_spoolmandb_says(owner):
    row = rows(owner)[YELLOW]
    assert row["known"] is None and row["name"] == "Yellow" and row["spool_weight"] == 250
    assert row["fill"] == {"brand": "Bambu Lab", "product_type": "", "material": "PLA", "colour": "Yellow", "colour_hex": "#f4ee2a", "roll_weight_g": 1000,
                           "diameter_mm": 1.75, "print_temp_c": 220, "bed_temp_c": 60, "spoolmandb_id": YELLOW}      # no barcode (it was scanned) and no price (there is none)
    assert owner.get("/api/spoolmandb/filaments?brand=bambu%20lab&material=pla").get_json()["filaments"]           # case does not matter
    assert owner.get("/api/spoolmandb/filaments?brand=Nobody&material=PLA").get_json() == {"filaments": []}
    assert owner.get("/api/spoolmandb/filaments").get_json() == {"filaments": []}


def test_a_filament_the_library_has_in_dutch_keeps_its_dutch_name(owner):
    make(owner, "/api/filament-library", GEEL)
    shown = rows(owner)
    assert shown[YELLOW]["known"] == {"colour": "Geel", "product_type": "Basic", "origin": "library"}
    fill = shown[YELLOW]["fill"]
    assert (fill["colour"], fill["product_type"], fill["price"], fill["print_temp_c"], fill["spoolmandb_id"]) == ("Geel", "Basic", "19.32", 215, YELLOW)
    assert (fill["bed_temp_c"], fill["colour_hex"]) == (60, "#f4ee2a")                  # what the entry lacks comes from SpoolmanDB
    assert shown["bambulab_pla_black_1000_175_n"]["known"] is None                       # another colour is not it
    make(owner, "/api/filament-library", {**GEEL, "colour": "Zwart", "roll_weight_g": 750})
    assert rows(owner)["bambulab_pla_black_1000_175_n"]["known"] is None                 # nor is the same colour on another weight


def test_a_roll_without_a_library_entry_is_known_too(owner):
    make(owner, "/api/spools", {"brand": "Bambu Lab", "material": "PLA", "colour": "Zwart", "roll_weight_g": 1000, "price": 18, "remaining_g": 400})
    black = rows(owner)["bambulab_pla_black_1000_175_n"]
    assert black["known"]["origin"] == "roll" and black["fill"]["colour"] == "Zwart" and "price" not in black["fill"]       # what a roll cost is per roll


# --- adding a roll picked from SpoolmanDB ------------------------------------------------------------------------

def test_a_picked_roll_completes_the_dutch_entry_instead_of_adding_an_english_twin(owner):
    entry = make(owner, "/api/filament-library", GEEL)
    made = make(owner, "/api/spools", {**ROLL, "barcode": "6975337030015"})
    assert made["spoolmandb_id"] == YELLOW
    after = library(owner)
    assert len(after) == 1 and after[0]["id"] == entry["id"] and after[0]["colour"] == "Geel"          # not a second entry named "Yellow"
    assert (after[0]["spoolmandb_id"], after[0]["barcode"], after[0]["colour_hex"]) == (YELLOW, "6975337030015", "")      # it is given what it lacked
    assert after[0]["price"] == "19.32"


def test_the_english_name_matches_the_dutch_entry_even_when_typed_by_hand(owner):
    make(owner, "/api/filament-library", {**GEEL, "colour": "Pompoenoranje"})
    made = make(owner, "/api/spools", {**ROLL, "colour": "Pumpkin Orange", "spoolmandb_id": "", "barcode": "1"})
    assert len(library(owner)) == 1 and library(owner)[0]["barcode"] == "1" and made["colour"] == "Pumpkin Orange"       # the roll keeps what was typed


def test_without_a_dutch_entry_the_library_gets_the_filament_with_its_reference(owner):
    make(owner, "/api/spools", {**ROLL, "barcode": "42"})
    entry, = library(owner)
    assert (entry["colour"], entry["spoolmandb_id"], entry["barcode"], entry["price"]) == ("Yellow", YELLOW, "42", None)
    again = make(owner, "/api/spools", {**ROLL, "barcode": "42"})
    assert len(library(owner)) == 1 and again["spoolmandb_id"] == YELLOW                  # the same filament is not added again


def test_the_same_spoolmandb_id_is_the_same_filament_whatever_it_is_called(owner):
    """A name the app cannot read ("Houtskool") is still the entry of that id: the roll completes it instead of adding "Matte Charcoal" next to it."""
    entry = make(owner, "/api/filament-library", {**GEEL, "colour": "Houtskool", "spoolmandb_id": CHARCOAL})
    make(owner, "/api/spools", {**ROLL, "colour": "Matte Charcoal", "spoolmandb_id": CHARCOAL, "barcode": "99"})
    after = library(owner)
    assert len(after) == 1 and after[0]["id"] == entry["id"] and after[0]["barcode"] == "99"


def test_an_entry_keeps_the_reference_it_has(owner):
    make(owner, "/api/filament-library", {**GEEL, "spoolmandb_id": "bambulab_pla_gray_1000_175_n"})
    make(owner, "/api/spools", {**ROLL, "colour": "Geel", "barcode": ""})
    assert library(owner)[0]["spoolmandb_id"] == "bambulab_pla_gray_1000_175_n"          # an entry is only ever completed, never overwritten


def test_the_reference_goes_with_a_scan_and_with_the_bulk_add(owner):
    make(owner, "/api/filament-library", {**GEEL, "barcode": "777", "spoolmandb_id": YELLOW})
    scan = owner.get("/api/spools/from-barcode?barcode=777").get_json()
    assert scan["source"] == "library" and scan["roll"]["spoolmandb_id"] == YELLOW
    done = owner.post("/api/spools/bulk", json={"items": [{"barcode": "777", "count": 2, "price": "19"}]}, headers=H)
    assert done.status_code == 201 and [r["spoolmandb_id"] for r in done.get_json()["rolls"]] == [YELLOW, YELLOW]


def test_the_library_file_keeps_the_reference_and_a_file_without_it_still_imports(owner):
    make(owner, "/api/filament-library", {**GEEL, "spoolmandb_id": YELLOW})
    exported = json.loads(owner.get("/api/filament-library/export").data)
    assert exported["filaments"][0]["spoolmandb_id"] == YELLOW and exported["format_version"] == 1
    older = {"format": filament_library.FORMAT, "format_version": 1, "filaments": [{k: v for k, v in GEEL.items() if k != "price"} | {"colour": "Rood"}]}
    assert owner.post("/api/filament-library/import", json=older, headers=H).get_json()["added"] == 1


def test_a_restore_still_sees_two_spellings_as_two_entries(owner):
    """`keys` stays exact: a backup that holds both "Geel" and "Yellow" must still restore. Only adding something is loose."""
    dutch, english = {**filament_library.BLANK, **filament_library.DEFAULTS, **GEEL}, {**filament_library.BLANK, **filament_library.DEFAULTS, **GEEL, "colour": "Yellow"}
    assert filament_library.first_clash([dutch, english]) is None
    assert filament_library.first_clash([dutch, dict(dutch)]) is not None


# --- what goes to Spoolman ---------------------------------------------------------------------------------------

def entry(**values):
    return {"brand": "Bambu Lab", "product_type": "", "material": "PLA", "colour": "Matte Charcoal", "colour_hex": "", "sku": "", "barcode": "", "notes": "",
            "price": None, "diameter_mm": 1.75, "roll_weight_g": 1000, "print_temp_c": None, "bed_temp_c": None, **values}


def test_a_filament_from_spoolmandb_brings_what_spoolmandb_measured():
    body = spoolman.filament_of(entry(spoolmandb_id=CHARCOAL))
    assert (body["density"], body["spool_weight"], body["external_id"]) == (1.31, 250, CHARCOAL)       # the density is not the rough 1.24 of PLA
    plain = spoolman.filament_of(entry())
    assert plain["density"] == 1.24 and "spool_weight" not in plain and "external_id" not in plain
    stale = spoolman.filament_of(entry(spoolmandb_id="gone_from_the_snapshot"))
    assert stale["external_id"] == "gone_from_the_snapshot" and stale["density"] == 1.24 and "spool_weight" not in stale       # the reference stays, the values cannot be looked up


def test_a_dutch_library_does_not_make_second_filaments_next_to_spoolmans_english_ones(owner, server):
    server.vendors = [{"id": 5, "name": "Bambu Lab"}]
    server.filaments = [{"id": 9, "name": "Yellow", "material": "PLA", "article_number": "", "vendor": server.vendors[0]},
                        {"id": 10, "name": "Whatever", "material": "PLA", "external_id": CHARCOAL, "vendor": server.vendors[0]}]
    make(owner, "/api/filament-library", GEEL)                                                              # "Basic" + "Geel" is Spoolman's "Yellow"
    make(owner, "/api/filament-library", {**GEEL, "colour": "Houtskool", "spoolmandb_id": CHARCOAL})        # a name Spoolman does not know, but the same SpoolmanDB id
    result = push(owner).get_json()
    assert (result["created"], result["existing"]) == (0, 2) and server.created == []


def test_a_filament_spoolman_lacks_is_made_with_its_source(owner, server):
    server.vendors = [{"id": 5, "name": "Bambu Lab"}]
    make(owner, "/api/filament-library", {**GEEL, "colour": "Rood"})
    make(owner, "/api/filament-library", {**GEEL, "colour": "Matte Charcoal", "product_type": "", "spoolmandb_id": CHARCOAL})
    assert push(owner).get_json()["created"] == 2
    made = {body["name"]: body for path, body in server.created if path == "/filament"}
    assert "external_id" not in made["Basic Rood"] and made["Basic Rood"]["density"] == 1.24
    assert (made["Matte Charcoal"]["external_id"], made["Matte Charcoal"]["density"], made["Matte Charcoal"]["spool_weight"]) == (CHARCOAL, 1.31, 250)


# --- the sync button ---------------------------------------------------------------------------------------------

NOON = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
NEW = {"id": "bambulab_pla_newcolour_1000_175_n", "manufacturer": "Bambu Lab", "name": "New Colour", "material": "PLA", "weight": 1000, "diameter": 1.75,
       "density": 1.24, "color_hex": "123456", "spool_weight": 250, "extruder_temp": 220, "bed_temp": 60}
LICENCE = (spoolmandb.DATA_DIR / "LICENSE").read_text(encoding="utf-8")


def published(*, drop=(), add=(), change=None):
    """The shipped list as the project publishes it (compiled entries with their own key names), with some filaments left out, added or changed."""
    out = []
    for row in spoolmandb.load()["rows"]:
        if row["id"] in drop:
            continue
        entry = dict(zip(spoolmandb.UPSTREAM_KEYS, [row[c] for c in spoolmandb.COLUMNS]))
        out.append({**entry, **(change or {}).get(row["id"], {})})
    return out + list(add)


class Reply:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]


class Upstream:
    """The project's two addresses, as a stand-in: a test never reaches the real ones."""

    def __init__(self):
        self.calls, self.list, self.raw, self.licence, self.status, self.down = [], published(add=[NEW]), None, LICENCE, {}, False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.down:
            raise requests.ConnectionError("down")
        if url == spoolmandb.LICENSE_URL:
            return Reply(self.status.get(url, 200), self.licence.encode())
        if url == spoolmandb.SYNC_URL:
            body = self.raw if self.raw is not None else json.dumps(self.list).encode()
            return Reply(self.status.get(url, 200), body, {"Last-Modified": "Thu, 12 Nov 2026 10:28:11 GMT"})
        raise AssertionError(f"an address that is not one of the two fixed ones: {url}")


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(requests, "get", fake.get)
    return fake


@pytest.fixture
def clock(monkeypatch):
    now = {"at": NOON}
    monkeypatch.setattr(spoolmandb, "_now", lambda: now["at"])
    return now


def sync(client, lang="en"):
    return client.post("/api/spoolmandb/sync", json={}, headers={**H, "X-Lang": lang})


def overview(client):
    return client.get("/api/spoolmandb").get_json()


def test_the_two_addresses_are_fixed_and_https():
    assert {urlparse(u).hostname for u in (spoolmandb.SYNC_URL, spoolmandb.LICENSE_URL)} == {"donkie.github.io", "raw.githubusercontent.com"}
    assert all(u.startswith("https://") for u in (spoolmandb.SYNC_URL, spoolmandb.LICENSE_URL))
    with pytest.raises(spoolmandb.Refused):
        spoolmandb.fetch("http://donkie.github.io/SpoolmanDB/filaments.json", 1000)


def test_before_a_sync_the_shipped_list_is_in_use_and_a_sync_is_possible(owner, upstream, clock):
    first = overview(owner)
    assert (first["origin"], first["synced_at"], first["next_sync_at"], first["can_sync"]) == ("shipped", None, None, True)
    assert first["rows"] == len(spoolmandb.load()["rows"]) and upstream.calls == []                  # looking at it contacts nobody


def test_a_sync_replaces_the_list_in_use_and_says_what_changed(owner, upstream, clock):
    upstream.list = published(drop=[YELLOW], add=[NEW])
    done = sync(owner)
    assert done.status_code == 200
    assert done.get_json() == {"rows": len(upstream.list), "brands": 87, "added": 1, "removed": 1, "dropped": 0}
    assert sorted(u for u, _ in upstream.calls) == sorted([spoolmandb.LICENSE_URL, spoolmandb.SYNC_URL])
    assert all(k["allow_redirects"] is False and k["timeout"] and k["stream"] for _, k in upstream.calls)          # no redirect is followed, nothing waits for ever
    after = overview(owner)
    assert (after["origin"], after["rows"], after["source"]["fetched"], after["source"]["modified"]) == ("synced", len(upstream.list), "2026-11-13", "2026-11-12")
    assert after["source"]["licence"] == "MIT" and after["source"]["copyright"].startswith("Copyright") and after["synced_at"].startswith("2026-11-13T12:00")
    assert after["next_sync_at"].startswith("2026-11-14T12:00")                                       # a day after
    shown = rows(owner)
    assert "bambulab_pla_newcolour_1000_175_n" in shown and YELLOW not in shown                       # the picker offers the new list
    assert shown["bambulab_pla_newcolour_1000_175_n"]["fill"]["colour_hex"] == "#123456"


def test_a_sync_touches_no_roll_and_no_library_entry(owner, upstream, clock):
    entry = make(owner, "/api/filament-library", {**GEEL, "spoolmandb_id": YELLOW})
    roll = make(owner, "/api/spools", {**ROLL, "barcode": "5", "add_to_library": False})
    upstream.list = published(drop=[YELLOW])                                                          # the filament both were made from has left the list
    assert sync(owner).status_code == 200
    assert owner.get("/api/filament-library").get_json() == [entry]
    assert next(r for r in owner.get("/api/spools").get_json() if r["id"] == roll["id"]) == roll
    assert spoolman.filament_of({**entry, "spoolmandb_id": YELLOW})["external_id"] == YELLOW          # the reference stays; only what was looked up in the list is gone


def test_it_can_be_done_once_a_day(owner, upstream, clock):
    assert sync(owner).status_code == 200
    calls = len(upstream.calls)
    clock["at"] = NOON + timedelta(hours=5, minutes=30)
    again = sync(owner)
    assert again.status_code == 429 and "once a day" in again.get_json()["error"] and "19 hours" in again.get_json()["error"]
    assert "één keer per dag" in sync(owner, "nl").get_json()["error"] and len(upstream.calls) == calls          # refused before anybody is contacted
    assert overview(owner)["next_sync_at"].startswith("2026-11-14T12:00")
    clock["at"] = NOON + timedelta(hours=24, seconds=1)
    assert overview(owner)["next_sync_at"] is None
    upstream.list = published(add=[NEW, {**NEW, "id": "bambulab_pla_newcolour2_1000_175_n", "name": "New Colour 2"}])
    assert sync(owner).get_json()["added"] == 1 and overview(owner)["rows"] == len(upstream.list)           # "New Colour" came with the first sync, "New Colour 2" is new


def test_a_failed_attempt_does_not_use_up_the_day(owner, upstream, clock):
    upstream.down = True
    failed = sync(owner)
    assert failed.status_code == 502 and "does not use up your daily sync" in failed.get_json()["error"]
    assert overview(owner)["origin"] == "shipped" and overview(owner)["next_sync_at"] is None
    upstream.down = False
    assert sync(owner).status_code == 200


def break_licence(up):
    up.licence = "GNU GENERAL PUBLIC LICENSE\n\nVersion 3, 29 June 2007\n"


def break_status(up):
    up.status[spoolmandb.SYNC_URL] = 404


def break_redirect(up):
    up.status[spoolmandb.SYNC_URL] = 301


def break_json(up):
    up.raw = b"<html>not a list</html>"


def break_shape(up):
    up.raw = b'{"filaments": []}'


def break_few(up):
    up.list = up.list[:5]


def break_shrunk(up):
    up.list = up.list[:len(up.list) // 3]


@pytest.mark.parametrize("break_it, said", [(break_licence, "no longer the MIT licence"), (break_status, "answered with code 404"), (break_redirect, "answered with code 301"),
                                            (break_json, "did not return a valid list"), (break_shape, "does not have the expected format"),
                                            (break_few, "does not have the expected format"), (break_shrunk, "looks like a failed download")])
def test_what_cannot_be_trusted_is_not_taken_and_costs_no_day(owner, upstream, clock, break_it, said):
    before = overview(owner)
    break_it(upstream)
    refused = sync(owner)
    assert refused.status_code == 502 and said in refused.get_json()["error"] and "nothing was taken over" in refused.get_json()["error"].replace("Nothing", "nothing")
    assert overview(owner) == before and sql_rows(owner) == 0                                          # the list in use is as it was, and nothing is stored
    upstream.licence, upstream.status, upstream.raw, upstream.list = LICENCE, {}, None, published(add=[NEW])
    assert sync(owner).status_code == 200                                                              # and the day was not used up


def sql_rows(owner):
    with owner.application.extensions["pool"].connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM spoolmandb_sync").fetchone()["n"]


def test_what_would_not_be_read_back_is_not_stored(owner, upstream, clock, monkeypatch):
    monkeypatch.setattr(spoolmandb, "document_text", lambda rows, source: "not a snapshot")
    refused = sync(owner)
    assert refused.status_code == 502 and "does not have the expected format" in refused.get_json()["error"] and sql_rows(owner) == 0


def test_a_list_that_is_too_big_is_refused(owner, upstream, clock, monkeypatch):
    monkeypatch.setattr(spoolmandb, "MAX_DOWNLOAD_BYTES", 5000)
    refused = sync(owner)
    assert refused.status_code == 502 and "much larger than expected" in refused.get_json()["error"] and sql_rows(owner) == 0


def test_only_an_administrator_syncs_but_everybody_sees_the_list(app, owner, upstream, clock):
    member = join_with_passkey(app, owner)
    assert member.post("/api/spoolmandb/sync", json={}, headers=H).status_code == 403 and upstream.calls == []
    assert member.get("/api/spoolmandb").get_json()["can_sync"] is False and rows(member)
    assert sync(owner).status_code == 200 and "bambulab_pla_newcolour_1000_175_n" in rows(member)       # what the administrator fetched is what the member is offered


def test_another_worker_notices_a_sync_and_a_damaged_copy_is_not_used(app, owner, upstream, clock):
    assert sync(owner).status_code == 200
    spoolmandb.reset()                                                                                  # a worker that has not seen it yet
    assert overview(owner)["origin"] == "synced" and "bambulab_pla_newcolour_1000_175_n" in rows(owner)  # it reads the copy from the database
    upstream.list = published(add=[NEW, {**NEW, "id": "bambulab_pla_newcolour2_1000_175_n"}])
    clock["at"] += timedelta(days=2)
    assert sync(owner).status_code == 200
    spoolmandb._state = (1, spoolmandb._state[1])                                                       # this worker still holds the first version
    assert "bambulab_pla_newcolour2_1000_175_n" in rows(owner)                                         # the version in the database is newer: it is read again
    sql(app, "UPDATE spoolmandb_sync SET version = version + 1, document = 'not a snapshot'")
    assert overview(owner)["origin"] == "shipped" and YELLOW in rows(owner)                            # a damaged copy: the shipped list serves, nothing breaks


def test_a_synced_list_is_what_goes_to_spoolman(owner, upstream, clock, server):
    """The density and spool weight sent to Spoolman come from the list in use, also in a worker that has not seen the sync yet."""
    server.vendors = [{"id": 5, "name": "Bambu Lab"}]
    upstream.list = published(change={CHARCOAL: {"density": 9.99, "spool_weight": 111}})
    assert sync(owner).status_code == 200
    make(owner, "/api/filament-library", {**GEEL, "colour": "Matte Charcoal", "product_type": "", "spoolmandb_id": CHARCOAL})
    spoolmandb._state = (None, None)                                                                    # another worker pushes
    assert push(owner).get_json()["created"] == 1
    body = next(b for path, b in server.created if path == "/filament")
    assert (body["density"], body["spool_weight"], body["external_id"]) == (9.99, 111, CHARCOAL)


def test_a_synced_copy_is_not_part_of_a_backup(owner, upstream, clock):
    assert sync(owner).status_code == 200
    saved = owner.get("/api/backup", headers=H).data
    assert b"spoolmandb_sync" not in saved and b"spoolmandb-snapshot" not in saved
