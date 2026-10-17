"""Backup and restore: everything the owner entered goes into one file and comes back exactly; nothing that
unlocks the app is in the file; a file that is wrong, damaged or edited is refused before anything changes."""
import base64
import copy
import io
import json
import os
from decimal import Decimal

import psycopg
import pytest

from tests import printfiles as pf
from tests.test_auth_api import H, onboard, post
from tests.test_domain_api import make, sheet_payload

EN = {"X-Lang": "en"}


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def fill(owner):
    """A bit of everything, wired together the way the app does it."""
    printer = make(owner, "/api/printers", {"name": "X1C", "purchase_price": 1500, "lifetime_hours": 3000, "power_kw": "0.15"})
    tariff = make(owner, "/api/tariffs", {"name": "Thuis", "price_per_kwh": "0.22"})
    box = make(owner, "/api/packaging", {"name": "Doos 20x15", "price": "0.45"})
    spool = make(owner, "/api/spools", {"brand": "Bambu Lab", "product_type": "Matte", "material": "PLA", "colour": "Black",
                                         "roll_weight_g": 1000, "price": "19.99", "remaining_g": 640, "barcode": "6975337030001",
                                         "print_temp_c": 220, "notes": "kast"})
    make(owner, "/api/spools", {"brand": "Bambu Lab", "product_type": "Matte", "roll_weight_g": 1000, "price": 25, "remaining_g": 1000,
                                "barcode": "6975337030001"})
    payload = sheet_payload(spool["id"])
    payload["vat_pct"], payload["price_rounding"], payload["margin_pct"] = "21", "x.95", "40"
    payload["data"]["parts"] = [{"group": "verpakking", "packaging_id": box["id"], "label": "Doos", "quantity": 1, "unit": "stuks", "unit_price": "0.45"}]
    project = make(owner, "/api/projects", payload)
    owner.put("/api/preferences", json={"theme": "dark", "language": "en", "vat_pct": "9", "blur_costs": True}, headers=H)
    return {"printer": printer, "tariff": tariff, "box": box, "spool": spool, "project": project}


def snapshot(client):
    def money(row):                                         # '40' and '40.00' are the same margin; the prices must match to the cent
        out = {k: v for k, v in row.items() if k not in ("updated_at", "totals")}
        if "totals" in row:
            out["prices"] = {k: row["totals"][k] for k in ("cost_price", "sell_price", "sell_price_incl_vat", "vat_amount")}
        return out
    keep = lambda rows: sorted((money(r) for r in rows), key=lambda r: r["id"])
    return {"printers": keep(client.get("/api/printers").get_json()), "tariffs": keep(client.get("/api/tariffs").get_json()),
            "packaging": keep(client.get("/api/packaging").get_json()), "spools": keep(client.get("/api/spools").get_json()),
            "projects": keep(client.get("/api/projects").get_json()), "preferences": client.get("/api/preferences").get_json()}


def backup(client, files=False):
    res = client.get("/api/backup" + ("?files=1" if files else ""), headers=H)
    assert res.status_code == 200
    return res


def wipe(client):
    for path in ("projects", "spools", "packaging", "printers", "tariffs"):
        for row in client.get(f"/api/{path}").get_json():
            client.delete(f"/api/{path}/{row['id']}", headers=H)
    client.put("/api/preferences", json={"theme": "light", "language": "nl", "blur_costs": False}, headers=H)


# --- who may, and what is in it ----------------------------------------------------------------------------------

def test_backup_and_restore_need_a_session(client):
    assert client.get("/api/backup").status_code == 401
    assert client.post("/api/backup/restore", json={}, headers=H).status_code == 401


def test_the_download_is_a_json_attachment_with_every_section(owner):
    fill(owner)
    res = backup(owner)
    assert "attachment" in res.headers["Content-Disposition"] and res.headers["Content-Disposition"].endswith('.json"')
    doc = res.get_json()
    assert doc["format"] == "printpricing-backup" and doc["format_version"] == 1 and doc["app_version"]
    assert [len(doc[k]) for k in ("printers", "tariffs", "packaging", "spools", "projects")] == [1, 1, 1, 2, 1]
    assert doc["preferences"]["theme"] == "dark" and doc["includes_files"] is False and "files" not in doc


def test_nothing_that_unlocks_the_app_is_in_a_backup(owner, app):
    fill(owner)
    owner.post("/api/push/subscribe", json={"endpoint": "https://push.example.test/x", "keys": {"p256dh": "a", "auth": "b"}}, headers=H)
    text = backup(owner).get_data(as_text=True).lower()
    for word in ("credential", "public_key", "recovery", "password", "totp", "secret", "salt", "code_hash", "endpoint", "p256dh"):
        assert word not in text, word


# --- the round trip ----------------------------------------------------------------------------------------------

def test_restoring_brings_back_exactly_what_was_backed_up_including_the_links_between_things(owner):
    fill(owner)
    before = snapshot(owner)
    doc = backup(owner).get_json()
    wipe(owner)
    assert snapshot(owner) != before
    res = post(owner, "/api/backup/restore", doc)
    assert res.status_code == 200 and res.get_json()["summary"]["projects"] == 1 and res.get_json()["dry_run"] is False
    assert snapshot(owner) == before
    project = owner.get("/api/projects").get_json()[0]
    full = owner.get(f"/api/projects/{project['id']}").get_json()
    assert full["data"]["filament"][0]["spool_id"] == before["spools"][0]["id"] or full["data"]["filament"][0]["spool_id"] in {s["id"] for s in before["spools"]}
    assert Decimal(full["totals"]["cost_price"]) > 0


def test_restoring_replaces_what_is_there_now(owner):
    fill(owner)
    doc = backup(owner).get_json()
    make(owner, "/api/printers", {"name": "Added later", "purchase_price": 1, "lifetime_hours": 1})
    make(owner, "/api/spools", {"brand": "Added later", "roll_weight_g": 1, "price": 1, "remaining_g": 1})
    post(owner, "/api/backup/restore", doc)
    assert [p["name"] for p in owner.get("/api/printers").get_json()] == ["X1C"]
    assert len(owner.get("/api/spools").get_json()) == 2


def test_a_dry_run_reports_what_would_come_back_and_changes_nothing(owner):
    fill(owner)
    doc = backup(owner).get_json()
    wipe(owner)
    now = snapshot(owner)
    res = post(owner, "/api/backup/restore?dry_run=1", doc).get_json()
    assert res["dry_run"] is True and res["summary"]["spools"] == 2 and res["summary"]["printers"] == 1
    assert snapshot(owner) == now


def test_calculations_are_recalculated_so_edited_totals_do_not_survive(owner):
    fill(owner)
    doc = backup(owner).get_json()
    honest = doc["projects"][0]["totals"]["cost_price"]
    doc["projects"][0]["totals"] = {"cost_price": "0.01"}
    post(owner, "/api/backup/restore", doc)
    project = owner.get("/api/projects").get_json()[0]
    assert project["totals"]["cost_price"] == honest


def test_at_most_one_tariff_stays_the_default(owner):
    fill(owner)
    doc = backup(owner).get_json()
    doc["tariffs"].append({**doc["tariffs"][0], "id": "11111111-1111-1111-1111-111111111111", "name": "Tweede", "is_default": True})
    assert post(owner, "/api/backup/restore", doc).status_code == 200
    assert sum(1 for t in owner.get("/api/tariffs").get_json() if t["is_default"]) == 1


# --- a file that is wrong is refused before anything changes -------------------------------------------------------

NL = {**H, "X-Lang": "nl"}                                                  # the saved language is English: ask for Dutch


def refuses(owner, doc, fragment=None, headers=NL):
    before = snapshot(owner)
    res = owner.post("/api/backup/restore", json=doc, headers=headers)
    assert res.status_code == 400, res.get_json()
    assert snapshot(owner) == before                                       # all or nothing
    if fragment:
        assert fragment in res.get_json()["error"], res.get_json()["error"]


def test_a_file_that_is_not_a_backup_or_is_too_new_is_refused(owner):
    fill(owner)
    refuses(owner, {"hello": "world"}, "geen back-upbestand")
    refuses(owner, [], None)
    refuses(owner, {"format": "printpricing-backup", "format_version": 99, "app_version": "9.9.9"}, "nieuwere versie")
    refuses(owner, {"format": "printpricing-backup", "format_version": "1"}, "geen back-upbestand")
    refuses(owner, {"format": "printpricing-backup", "format_version": True}, "geen back-upbestand")


def test_one_bad_line_stops_the_whole_restore_and_says_which_line(owner):
    fill(owner)
    doc = backup(owner).get_json()
    bad = copy.deepcopy(doc)
    bad["spools"][1]["price"] = "-5"
    refuses(owner, bad, "Filament, regel 2")
    bad = copy.deepcopy(doc)
    bad["printers"][0]["name"] = ""
    refuses(owner, bad, "Printers, regel 1: Naam is verplicht.")
    bad = copy.deepcopy(doc)
    bad["projects"][0]["data"]["filament"][0]["grams"] = "abc"
    refuses(owner, bad, "Berekeningen, regel 1")
    bad = copy.deepcopy(doc)
    bad["preferences"]["theme"] = "neon"
    refuses(owner, bad, "Instellingen")
    bad = copy.deepcopy(doc)
    bad["spools"][0]["id"] = "not-a-uuid"
    refuses(owner, bad, "Ongeldige id")
    bad = copy.deepcopy(doc)
    bad["tariffs"] = {"not": "a list"}
    refuses(owner, bad, "Energietarieven")
    bad = copy.deepcopy(doc)
    bad["printers"].append("just a string")
    refuses(owner, bad, "Printers, regel 2")
    bad = copy.deepcopy(doc)
    bad["spools"][0]["created_at"] = "yesterday-ish"
    refuses(owner, bad, "Ongeldige datum")


def test_the_messages_follow_the_language(owner):
    fill(owner)
    doc = backup(owner).get_json()
    doc["spools"][0]["price"] = "-5"
    refuses(owner, doc, "Filament, line 1", headers={**H, **EN})
    refuses(owner, {"x": 1}, "not a backup file", headers={**H, **EN})


def test_a_failure_halfway_leaves_everything_as_it_was(owner, monkeypatch):
    fill(owner)
    before = snapshot(owner)
    doc = backup(owner).get_json()
    from app import backup as module
    real = module._insert
    calls = {"n": 0}
    def flaky(conn, table, values):
        calls["n"] += 1
        if table == "projects":
            raise psycopg.errors.CheckViolation("boom")
        return real(conn, table, values)
    monkeypatch.setattr(module, "_insert", flaky)
    owner.application.testing = False
    res = owner.post("/api/backup/restore", json=doc, headers=H)
    assert res.status_code == 500 and calls["n"] > 3
    monkeypatch.undo()
    assert snapshot(owner) == before                                       # the deletes were rolled back with it


def test_restoring_leaves_passkeys_alone(owner, app):
    fill(owner)
    doc = backup(owner).get_json()
    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        passkeys = conn.execute("SELECT count(*) FROM webauthn_credentials").fetchone()[0]
        codes = conn.execute("SELECT count(*) FROM recovery_codes").fetchone()[0]
    post(owner, "/api/backup/restore", doc)
    with psycopg.connect(app.config["APP_CONFIG"].database_url) as conn:
        assert conn.execute("SELECT count(*) FROM webauthn_credentials").fetchone()[0] == passkeys >= 1
        assert conn.execute("SELECT count(*) FROM recovery_codes").fetchone()[0] == codes
    assert owner.get("/api/auth/status").get_json()["authenticated"] is True


# --- print files --------------------------------------------------------------------------------------------------

def upload(client, data, name="part.stl"):
    res = client.post("/api/print-files", data={"file": (io.BytesIO(data), name)}, headers=H, content_type="multipart/form-data")
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def with_file(owner):
    ids = fill(owner)
    meta = upload(owner, pf.stl_binary())
    payload = sheet_payload()
    payload["file_id"] = meta["id"]
    project = make(owner, "/api/projects", payload)
    return meta, project


def test_print_files_travel_along_when_asked_and_are_read_again_on_the_way_in(owner, app):
    meta, project = with_file(owner)
    doc = backup(owner, files=True).get_json()
    assert doc["includes_files"] and len(doc["files"]) == 1 and doc["files"][0]["content_b64"]
    old_names = set(os.listdir(app.config["APP_CONFIG"].upload_dir))
    wipe(owner)
    post(owner, "/api/backup/restore", doc)
    restored = owner.get(f"/api/projects/{project['id']}").get_json()
    assert restored["file_id"] == meta["id"]
    download = owner.get(f"/api/print-files/{meta['id']}/download")
    assert download.status_code == 200 and download.data == pf.stl_binary()
    assert owner.get(f"/api/print-files/{meta['id']}").get_json()["analysis"]["volume_cm3"] == pytest.approx(1.0, rel=0.01)
    new_names = set(os.listdir(app.config["APP_CONFIG"].upload_dir))
    assert len(new_names) == 1 and new_names != old_names                  # the replaced file is gone, no leftovers


def test_without_files_a_calculation_keeps_its_file_only_if_that_file_is_still_here(owner):
    meta, project = with_file(owner)
    doc = backup(owner).get_json()
    assert "files" not in doc
    post(owner, "/api/backup/restore", doc)
    assert owner.get(f"/api/projects/{project['id']}").get_json()["file_id"] == meta["id"]       # still on the server
    owner.delete(f"/api/projects/{project['id']}", headers=H)
    with psycopg.connect(owner.application.config["APP_CONFIG"].database_url) as conn:
        conn.execute("DELETE FROM print_files")
        conn.commit()
    post(owner, "/api/backup/restore", doc)
    assert owner.get(f"/api/projects/{project['id']}").get_json()["file_id"] is None               # gone: let go, not an error


def test_a_damaged_or_edited_print_file_is_refused(owner, app):
    meta, project = with_file(owner)
    doc = backup(owner, files=True).get_json()
    names = set(os.listdir(app.config["APP_CONFIG"].upload_dir))
    edited = copy.deepcopy(doc)
    raw = bytearray(base64.b64decode(edited["files"][0]["content_b64"]))
    raw[100] ^= 0xFF
    edited["files"][0]["content_b64"] = base64.b64encode(bytes(raw)).decode()
    refuses(owner, edited, "Printbestanden, regel 1")
    junk = copy.deepcopy(doc)
    junk["files"][0]["content_b64"] = "!!!not base64!!!"
    refuses(owner, junk, "Printbestanden, regel 1")
    wrong = copy.deepcopy(doc)
    wrong["files"][0].pop("sha256")
    wrong["files"][0]["content_b64"] = base64.b64encode(b"this is not a model").decode()
    refuses(owner, wrong, "Printbestanden, regel 1")                       # no checksum to hide behind: it is read and rejected
    kind = copy.deepcopy(doc)
    kind["files"][0]["kind"] = "exe"
    refuses(owner, kind, "Printbestanden, regel 1")
    assert set(os.listdir(app.config["APP_CONFIG"].upload_dir)) == names   # nothing was left on disk by the refusals
