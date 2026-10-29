"""Backup and restore: everything the owner entered goes into one file and comes back exactly; nothing that
unlocks the app is in the file; a file that is wrong, damaged or edited is refused before anything changes."""
import base64
import copy
import dataclasses
import io
import json
import os
import sqlite3
import zipfile
from decimal import Decimal

import pytest

from app import backup as backup_module
from tests import printfiles as pf
from tests.test_auth_api import H, onboard, post
from tests.test_domain_api import make, sheet_payload
from tests.test_orders import customer
from tests.conftest import connect

EN = {"X-Lang": "en"}


REAL_START = backup_module._start


@pytest.fixture(autouse=True)
def _inline(monkeypatch):
    """A restore runs in a thread; here it runs on the spot, so a test sees the outcome. One test uses the real thread."""
    monkeypatch.setattr(backup_module, "_start", lambda *args: backup_module._run_restore(*args))


@pytest.fixture
def owner(client):
    onboard(client)
    return client


def fill(owner):
    """A bit of everything, wired together the way the app does it."""
    printer = make(owner, "/api/printers", {"name": "X1C", "purchase_price": 1500, "lifetime_hours": 3000, "power_kw": "0.15"})
    tariff = make(owner, "/api/tariffs", {"name": "Thuis", "price_per_kwh": "0.22"})
    box = make(owner, "/api/packaging", {"name": "Doos 20x15", "price": "0.45"})
    part = make(owner, "/api/parts", {"name": "JST-connector", "price": "0.12", "unit": "stuks", "notes": "2-pins"})
    cable = make(owner, "/api/accessories", {"name": "USB-C-kabel", "price": "1.80", "unit": "m"})
    make(owner, "/api/filament-library", {"brand": "Bambu Lab", "product_type": "Basic", "material": "PLA", "colour": "Grijs", "filament_id": "10103",
                                          "sku": "A00-D0-1.75-1000-SPLFREE", "refill": True, "roll_weight_g": 1000, "diameter_mm": "1.75",
                                          "print_temp_c": 220, "price": "19.32"})
    spool = make(owner, "/api/spools", {"brand": "Bambu Lab", "product_type": "Matte", "material": "PLA", "colour": "Black",
                                         "roll_weight_g": 1000, "price": "19.99", "remaining_g": 640, "barcode": "6975337030001",
                                         "print_temp_c": 220, "colour_hex": "#222222", "notes": "kast"})
    make(owner, "/api/spools", {"brand": "Bambu Lab", "product_type": "Matte", "roll_weight_g": 1000, "price": 25, "remaining_g": 1000,
                                "barcode": "6975337030001"})
    payload = sheet_payload(spool["id"])
    payload["vat_pct"], payload["price_rounding"], payload["margin_pct"] = "21", "x.95", "40"
    payload["data"]["parts"] = [{"group": "verpakking", "packaging_id": box["id"], "label": "Doos", "quantity": 1, "unit": "stuks", "unit_price": "0.45"},
                                {"group": "onderdeel", "part_id": part["id"], "label": "JST-connector", "quantity": 2, "unit": "stuks", "unit_price": "0.12"},
                                {"group": "oplader", "accessory_id": cable["id"], "label": "USB-C-kabel", "quantity": 1.5, "unit": "m", "unit_price": "1.80"}]
    project = make(owner, "/api/projects", payload)
    owner.put("/api/preferences", json={"theme": "dark", "language": "en", "vat_pct": "9", "blur_costs": True}, headers=H)
    return {"printer": printer, "tariff": tariff, "box": box, "part": part, "cable": cable, "spool": spool, "project": project}


def snapshot(client):
    def money(row):                                         # '40' and '40.00' are the same margin; the prices must match to the cent
        out = {k: v for k, v in row.items() if k not in ("updated_at", "totals")}
        if "totals" in row:
            out["prices"] = {k: row["totals"][k] for k in ("cost_price", "sell_price", "sell_price_incl_vat", "vat_amount")}
        return out
    keep = lambda rows: sorted((money(r) for r in rows), key=lambda r: r["id"])
    return {"printers": keep(client.get("/api/printers").get_json()), "tariffs": keep(client.get("/api/tariffs").get_json()),
            "packaging": keep(client.get("/api/packaging").get_json()), "parts": keep(client.get("/api/parts").get_json()),
            "accessories": keep(client.get("/api/accessories").get_json()), "spools": keep(client.get("/api/spools").get_json()),
            "library": keep(client.get("/api/filament-library").get_json()), "projects": keep(client.get("/api/projects").get_json()), "preferences": client.get("/api/preferences").get_json()}


def backup(client, files=False):
    res = client.get("/api/backup" + ("?files=1" if files else ""), headers=H)
    assert res.status_code == 200
    return res


def wipe(client):
    for path in ("projects", "spools", "filament-library", "packaging", "parts", "accessories", "printers", "tariffs"):
        for row in client.get(f"/api/{path}").get_json():
            client.delete(f"/api/{path}/{row['id']}", headers=H)
    client.put("/api/preferences", json={"theme": "light", "language": "nl", "blur_costs": False}, headers=H)


def archive_of(res):
    assert res.mimetype == "application/zip", res.mimetype
    return zipfile.ZipFile(io.BytesIO(res.data))


def inline(res):
    """A backup with files as the one-JSON-file form it had before the ZIP: every model back inside as base64."""
    archive = archive_of(res)
    doc = json.loads(archive.read("backup.json"))
    for entry in doc["files"]:
        entry["content_b64"] = base64.b64encode(archive.read(entry.pop("archive_path"))).decode()
    return doc


def make_zip(doc, members=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("backup.json", json.dumps(doc))
        for name, data in (members or {}).items():
            archive.writestr(name, data)
    return out.getvalue()


def stage(client, data, headers=None):
    return client.post("/api/backup/stage", data=data, headers=headers or {**H, "X-Lang": "nl"}, content_type="application/octet-stream")


def restore_job(client, token, headers=None):
    """Start the restore of a staged backup and return the job as it stands afterwards."""
    res = client.post("/api/backup/jobs", json={"token": token}, headers=headers or {**H, "X-Lang": "nl"})
    assert res.status_code == 202, res.get_json()
    return client.get("/api/backup/jobs/latest", headers={**H, "X-Lang": "nl"}).get_json()["job"]


def staged_files(app):
    return [n for n in os.listdir(app.config["APP_CONFIG"].upload_dir) if n.startswith(".restore-")]


# --- who may, and what is in it ----------------------------------------------------------------------------------

def test_backup_and_restore_need_a_session(client):
    assert client.get("/api/backup").status_code == 401
    assert client.post("/api/backup/restore", json={}, headers=H).status_code == 401


def test_the_download_is_a_json_attachment_with_every_section(owner):
    fill(owner)
    res = backup(owner)
    assert "attachment" in res.headers["Content-Disposition"] and res.headers["Content-Disposition"].endswith('.json"')
    doc = res.get_json()
    assert doc["format"] == "printpricing-backup" and doc["format_version"] == 5 and doc["app_version"]
    assert [len(doc[k]) for k in ("printers", "tariffs", "packaging", "parts", "accessories", "filament_library", "spools", "projects")] == [1, 1, 1, 1, 1, 1, 2, 1]
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
            raise sqlite3.IntegrityError("boom")
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
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        passkeys = conn.execute("SELECT count(*) FROM webauthn_credentials").fetchone()[0]
        codes = conn.execute("SELECT count(*) FROM recovery_codes").fetchone()[0]
    post(owner, "/api/backup/restore", doc)
    with connect(app.config["APP_CONFIG"].database_path) as conn:
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


def test_with_print_files_the_backup_is_a_zip_with_every_model_loose_and_a_json_for_the_rest(owner):
    meta, project = with_file(owner)
    upload(owner, pf.stl_binary(), name="part.stl")                         # a second model with the same name
    res = backup(owner, files=True)
    assert res.headers["Content-Disposition"].endswith('.zip"') and int(res.headers["Content-Length"]) == len(res.data)      # the size is known up front
    archive = archive_of(res)
    assert sorted(archive.namelist()) == ["backup.json", "files/part (2).stl", "files/part.stl"]
    assert archive.read("files/part.stl") == pf.stl_binary()                  # the model as it is, not wrapped in anything
    doc = json.loads(archive.read("backup.json"))
    assert doc["includes_files"] and len(doc["files"]) == 2 and all("content_b64" not in f and f["archive_path"] in archive.namelist() for f in doc["files"])
    assert "printers" in doc and len(doc["projects"]) == 2                  # the rest is the same JSON as ever
    assert backup(owner).mimetype == "application/json"                     # without the models it stays one JSON file


def test_a_zip_is_sent_once_checked_and_restored_from_the_server(owner, app):
    meta, project = with_file(owner)
    res = backup(owner, files=True)
    old_names = set(os.listdir(app.config["APP_CONFIG"].upload_dir))
    wipe(owner)
    answer = stage(owner, res.data)
    assert answer.status_code == 200, answer.get_json()
    assert answer.get_json()["summary"]["files"] == 1 and answer.get_json()["summary"]["projects"] == 2
    assert len(staged_files(app)) == 1                                       # waiting for the owner to confirm
    assert owner.get("/api/projects").get_json() == []                       # staging changes nothing
    job = restore_job(owner, answer.get_json()["token"])
    assert job["status"] == "done" and job["phase"] == "done" and job["step"] == job["steps"] == 1 and job["summary"]["files"] == 1
    assert job["checking_seconds"] >= 0 and job["replacing_seconds"] >= 0           # how long each part took, so a slow restore says where
    restored = owner.get(f"/api/projects/{project['id']}").get_json()
    assert restored["file_id"] == meta["id"]
    download = owner.get(f"/api/print-files/{meta['id']}/download")
    assert download.status_code == 200 and download.data == pf.stl_binary()
    assert owner.get(f"/api/print-files/{meta['id']}").get_json()["analysis"]["volume_cm3"] == pytest.approx(1.0, rel=0.01)
    new_names = set(os.listdir(app.config["APP_CONFIG"].upload_dir))
    assert len(new_names) == 1 and new_names != old_names                   # the replaced file is gone, the staged ZIP too
    assert post(owner, "/api/backup/jobs", {"token": answer.get_json()["token"]}).status_code == 400      # a token is used once


def test_a_json_backup_from_before_the_zip_is_staged_and_restored_too(owner, app):
    meta, project = with_file(owner)
    doc = inline(backup(owner, files=True))
    wipe(owner)
    answer = stage(owner, json.dumps(doc).encode())
    assert answer.status_code == 200 and answer.get_json()["summary"]["files"] == 1
    assert restore_job(owner, answer.get_json()["token"])["status"] == "done"
    assert owner.get(f"/api/print-files/{meta['id']}/download").data == pf.stl_binary()
    post(owner, "/api/backup/restore", doc)                                  # and the JSON can still be posted straight to /restore
    assert owner.get(f"/api/print-files/{meta['id']}/download").data == pf.stl_binary()


def test_a_restore_that_fails_says_why_changes_nothing_and_leaves_no_file(owner, app, monkeypatch):
    fill(owner)
    token = stage(owner, backup(owner, files=True).data).get_json()["token"]
    before = snapshot(owner)
    def broken(*args, **kwargs):
        raise RuntimeError("the disk is full")
    monkeypatch.setattr(backup_module, "_write", broken)
    job = restore_job(owner, token)
    assert job["status"] == "failed" and "mislukt" in job["message"] and "niets veranderd" in job["message"]
    assert "disk" not in job["message"]                                      # what went wrong inside is for the log, not for the screen
    assert staged_files(app) == [] and snapshot(owner) == before


def test_a_file_that_is_refused_while_restoring_is_reported_by_the_job(owner, app):
    fill(owner)
    token = stage(owner, backup(owner).data).get_json()["token"]
    path = os.path.join(app.config["APP_CONFIG"].upload_dir, f".restore-{token}")
    doc = json.loads(open(path, "rb").read())
    doc["printers"][0]["power_kw"] = "banana"                                # it was fine when staged; the file on disk changed since
    open(path, "wb").write(json.dumps(doc).encode())
    before = snapshot(owner)
    job = restore_job(owner, token)
    assert job["status"] == "failed" and "Printers, regel 1" in job["message"] and snapshot(owner) == before


def test_only_one_restore_runs_at_a_time_and_a_finished_one_is_dismissed_by_the_screen(owner, app):
    with_file(owner)
    data = backup(owner, files=True).data
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        conn.execute("INSERT INTO backup_jobs (status) VALUES ('running')")
        conn.commit()
    token = stage(owner, data).get_json()["token"]
    assert post(owner, "/api/backup/jobs", {"token": token}).status_code == 409
    assert owner.get("/api/backup/jobs/latest").get_json()["job"]["status"] == "running"
    with connect(app.config["APP_CONFIG"].database_path) as conn:    # its thread is gone and nothing has moved for a long time
        conn.execute("UPDATE backup_jobs SET updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now', '-1 hours')")
        conn.commit()
    job = owner.get("/api/backup/jobs/latest", headers={**H, "X-Lang": "nl"}).get_json()["job"]
    assert job["status"] == "failed" and "onderbroken" in job["message"]
    job = restore_job(owner, token)
    assert job["status"] == "done"
    assert owner.delete(f"/api/backup/jobs/{job['id']}", headers=H).status_code == 200
    assert owner.get("/api/backup/jobs/latest").get_json() == {"job": None}


def test_the_restore_goes_on_in_the_background_whatever_the_browser_does(owner, app, monkeypatch):
    meta, project = with_file(owner)
    token = stage(owner, backup(owner, files=True).data).get_json()["token"]
    wipe(owner)
    threads = []
    monkeypatch.setattr(backup_module, "_start", lambda *args: threads.append(REAL_START(*args)) or threads[-1])
    res = post(owner, "/api/backup/jobs", {"token": token})
    assert res.status_code == 202 and res.get_json()["job"]["status"] in ("running", "done")      # answered at once; the work is the thread's
    threads[0].join(30)
    assert not threads[0].is_alive()
    assert owner.get("/api/backup/jobs/latest").get_json()["job"]["status"] == "done"
    assert owner.get(f"/api/projects/{project['id']}").get_json()["file_id"] == meta["id"]


def test_cancelling_removes_the_staged_backup(owner, app):
    with_file(owner)
    token = stage(owner, backup(owner, files=True).data).get_json()["token"]
    assert owner.delete(f"/api/backup/stage/{token}", headers=H).status_code == 200 and staged_files(app) == []


def test_old_staged_backups_are_cleared_when_the_next_one_arrives(owner, app):
    with_file(owner)
    data = backup(owner, files=True).data
    first = stage(owner, data).get_json()["token"]
    old = os.path.join(app.config["APP_CONFIG"].upload_dir, f".restore-{first}")
    os.utime(old, (0, 0))                                                    # an hour is long gone
    stage(owner, data)
    assert not os.path.exists(old) and len(staged_files(app)) == 1


def test_staging_needs_a_session_and_a_token_must_look_like_one(client, owner):
    assert post(owner, "/api/backup/jobs", {"token": "../../etc/passwd"}).status_code == 400
    assert post(owner, "/api/backup/jobs", {"token": "0" * 32}).status_code == 400
    assert post(owner, "/api/backup/jobs", {}).status_code == 400
    client.post("/api/auth/logout", json={}, headers=H)
    assert stage(client, b"{}").status_code == 401
    assert client.post("/api/backup/jobs", json={"token": "0" * 32}, headers=H).status_code == 401
    assert client.get("/api/backup/jobs/latest").status_code == 401


def test_something_that_is_no_backup_is_refused_and_not_kept(owner, app):
    fill(owner)
    before = snapshot(owner)
    for junk in (b"just some text", b"PK\x03\x04 not really a zip", b"", make_zip({"format": "something-else"}), b"\xff\xfe\x00"):
        res = stage(owner, junk)
        assert res.status_code == 400, junk
    assert staged_files(app) == [] and snapshot(owner) == before


def test_a_zip_with_a_damaged_edited_or_missing_model_is_refused(owner, app):
    meta, project = with_file(owner)
    res = backup(owner, files=True)
    archive = archive_of(res)
    doc = json.loads(archive.read("backup.json"))
    model = archive.read("files/part.stl")
    names = set(os.listdir(app.config["APP_CONFIG"].upload_dir))
    before = snapshot(owner)
    raw = bytearray(model)
    raw[100] ^= 0xFF
    cases = {
        "edited": make_zip(doc, {"files/part.stl": bytes(raw)}),             # no longer fits its checksum
        "missing": make_zip(doc, {}),
        "no name": make_zip({**doc, "files": [{**doc["files"][0], "archive_path": 7}]}, {"files/part.stl": model}),
    }
    for name, data in cases.items():
        answer = stage(owner, data)
        assert answer.status_code == 400, name
        assert "Printbestanden, regel 1" in answer.get_json()["error"], (name, answer.get_json())
    wrong = {**doc, "files": [{k: v for k, v in doc["files"][0].items() if k != "sha256"}]}
    answer = stage(owner, make_zip(wrong, {"files/part.stl": b"this is not a model"}))       # no checksum to hide behind: it is read and rejected
    assert answer.status_code == 400 and "Printbestanden, regel 1" in answer.get_json()["error"]
    assert set(os.listdir(app.config["APP_CONFIG"].upload_dir)) == names and snapshot(owner) == before      # nothing left behind, nothing changed


def test_a_model_in_the_zip_that_unpacks_bigger_than_an_upload_may_be_is_refused(owner, app, monkeypatch):
    with_file(owner)
    archive = archive_of(backup(owner, files=True))
    real = app.config["APP_CONFIG"]
    monkeypatch.setattr("app.backup.config", lambda: dataclasses.replace(real, max_upload_mb=0))        # nothing may be bigger than 0 MB
    answer = stage(owner, make_zip(json.loads(archive.read("backup.json")), {"files/part.stl": archive.read("files/part.stl")}))
    assert answer.status_code == 400


def test_without_files_a_calculation_keeps_its_file_only_if_that_file_is_still_here(owner):
    meta, project = with_file(owner)
    doc = backup(owner).get_json()
    assert "files" not in doc
    post(owner, "/api/backup/restore", doc)
    assert owner.get(f"/api/projects/{project['id']}").get_json()["file_id"] == meta["id"]       # still on the server
    owner.delete(f"/api/projects/{project['id']}", headers=H)
    with connect(owner.application.config["APP_CONFIG"].database_path) as conn:
        conn.execute("DELETE FROM print_files")
        conn.commit()
    post(owner, "/api/backup/restore", doc)
    assert owner.get(f"/api/projects/{project['id']}").get_json()["file_id"] is None               # gone: let go, not an error


def test_a_damaged_or_edited_print_file_is_refused_in_the_json_form(owner, app):
    meta, project = with_file(owner)
    doc = inline(backup(owner, files=True))
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


# --- orders, the invoice template and numbers (format version 2) ---------------------------------------------------------

def fill_orders(owner):
    from docx import Document
    from pypdf import PdfWriter
    project = make(owner, "/api/projects", sheet_payload())
    order = owner.post("/api/orders", headers=H, json={
        "customer_id": customer(owner, name="Jan Jansen", number="K9999", phone="0612345678", notes="Betaalt altijd op tijd")["id"], "subject": "Rack-houders voor oktober", "order_date": "2026-10-01", "delivery_date": "2026-10-15", "status": "verwerkt",
        "notes": "Graag in doos", "price_rounding": "0.50",
        "lines": [{"description": "Rack-houder", "quantity": 2, "cost_price": "10.00", "margin_pct": "25", "vat_pct": "21", "project_id": project["id"]},
                                            {"description": "Verzending", "quantity": 1, "unit_price": "5.00", "vat_pct": "0", "optional": True}]}).get_json()
    owner.put("/api/preferences", json={"business": {"name": "Flux76 Prints", "kvk": "12345678", "payment_days": 30}}, headers=H)
    assert post(owner, f"/api/orders/{order['id']}/invoice").status_code == 200           # gets its invoice number
    order = owner.get(f"/api/orders/{order['id']}").get_json()
    paper = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    writer.write(paper)
    res = owner.post("/api/invoice-template", data={"file": (io.BytesIO(paper.getvalue()), "paper.pdf"), "margin_top_mm": "62"}, headers=H,
                     content_type="multipart/form-data")
    assert res.status_code == 201
    from PIL import Image
    logo = io.BytesIO()
    Image.new("RGB", (300, 100), (10, 120, 200)).save(logo, "PNG")
    assert owner.post("/api/invoice-logo", data={"file": (io.BytesIO(logo.getvalue()), "logo.png")}, headers=H, content_type="multipart/form-data").status_code == 201
    return project, order, paper.getvalue()


def order_snapshot(client):
    orders = [client.get(f"/api/orders/{o['id']}").get_json() for o in client.get("/api/orders").get_json()]
    customers_ = client.get("/api/customers").get_json()
    for order in orders:
        order.pop("updated_at")
        for line in order["lines"]:
            line.pop("id")                                   # a line has no identity of its own outside its order
    return {"orders": orders, "customers": [{k: v for k, v in c.items() if k != "updated_at"} for c in customers_], "numbers": {p["id"]: p["number"] for p in client.get("/api/projects").get_json()},
            "template": {k: v for k, v in (client.get("/api/invoice-template").get_json()["template"] or {}).items() if k != "uploaded_at"},
            "logo": {k: v for k, v in (client.get("/api/invoice-logo").get_json()["logo"] or {}).items() if k != "uploaded_at"},
            "logo_bytes": client.get("/api/invoice-logo/file").data if client.get("/api/invoice-logo").get_json()["logo"] else None, "business": client.get("/api/preferences").get_json()["business"]}


def test_orders_numbers_and_the_template_come_back_exactly(owner):
    project, order, paper = fill_orders(owner)
    before = order_snapshot(owner)
    doc = backup(owner).get_json()
    assert doc["orders"][0]["invoice_number"] and len(doc["orders"][0]["lines"]) == 2 and doc["invoice_template"]["kind"] == "pdf"
    assert doc["orders"][0]["price_rounding"] == "0.50" and doc["orders"][0]["lines"][0]["cost_price"] == "10.00" and doc["orders"][0]["lines"][0]["margin_pct"] == "25.00"
    assert [l["optional"] for l in doc["orders"][0]["lines"]] == [False, True]          # an accessory line stays optional
    assert order["lines"][0]["unit_price"] == "15.50"                                   # 10,00 + 25% + 21% = 15,125, up to 50 cents
    assert base64.b64decode(doc["invoice_template"]["content_b64"]) == paper
    kept_pdf = owner.get(f"/api/orders/{order['id']}/invoice").data
    assert len(doc["invoice_pdfs"]) == 1 and base64.b64decode(doc["invoice_pdfs"][0]["content_b64"]) == kept_pdf
    owner.delete(f"/api/orders/{order['id']}", headers=H)
    owner.delete("/api/invoice-template", headers=H)
    owner.delete("/api/invoice-logo", headers=H)
    owner.delete(f"/api/projects/{project['id']}", headers=H)
    res = owner.post("/api/backup/restore", json=doc, headers=H)
    summary = res.get_json()["summary"]
    assert owner.get(f"/api/orders/{order['id']}/invoice").data == kept_pdf             # the invoice as it was made comes back with the order
    assert res.status_code == 200 and summary["orders"] == 1 and summary["template"] == 1 and summary["logo"] == 1
    assert order_snapshot(owner) == before and before["logo"]["kind"] == "png" and before["logo_bytes"].startswith(b"\x89PNG")
    assert doc["orders"][0]["customer_number"] == "K9999" and doc["orders"][0]["subject"] == "Rack-houders voor oktober"
    assert owner.get("/api/invoice-template/download").data == paper


def test_numbers_carry_on_after_a_restore(owner):
    project, order, _ = fill_orders(owner)
    doc = backup(owner).get_json()
    owner.post("/api/backup/restore", json=doc, headers=H)
    again = owner.post("/api/orders", json={"customer_id": customer(owner, name="Piet")["id"], "lines": [{"description": "x", "quantity": 1, "unit_price": "1", "vat_pct": "0"}]},
                       headers=H).get_json()
    assert again["number"] == order["number"] + 1
    assert make(owner, "/api/projects", sheet_payload())["number"] == project["number"] + 1
    third = post(owner, f"/api/orders/{again['id']}/invoice").headers["Content-Disposition"]
    assert order["invoice_number"][:4] in third and "-0002" in third                       # the invoice counter went on after the restored one


def test_a_restore_without_orders_empties_them_and_a_version_1_file_still_works(owner):
    project, order, _ = fill_orders(owner)
    old = backup(owner).get_json()
    for key in ("orders", "invoice_template", "invoice_logo"):
        old.pop(key)
    old["format_version"] = 1
    for row in old["projects"]:
        row.pop("number")
    res = owner.post("/api/backup/restore", json=old, headers=H)
    assert res.status_code == 200 and owner.get("/api/orders").get_json() == []
    assert owner.get("/api/invoice-template").get_json()["template"] is None and owner.get("/api/invoice-logo").get_json()["logo"] is None
    assert [p["number"] for p in owner.get("/api/projects").get_json()] == [1]               # numbered afresh


def test_a_backup_from_before_parts_and_accessories_still_restores_and_leaves_them_empty(owner):
    fill(owner)
    old = backup(owner).get_json()
    for key in ("parts", "accessories"):
        old.pop(key)
    old["format_version"] = 3
    assert owner.post("/api/backup/restore", json=old, headers=H).status_code == 200
    assert owner.get("/api/parts").get_json() == [] and owner.get("/api/accessories").get_json() == []
    assert len(owner.get("/api/packaging").get_json()) == 1


def test_a_backup_from_before_the_filament_library_still_restores_and_leaves_it_empty(owner):
    fill(owner)
    old = backup(owner).get_json()
    old.pop("filament_library")
    old["format_version"] = 4
    assert owner.post("/api/backup/restore", json=old, headers=H).status_code == 200
    assert owner.get("/api/filament-library").get_json() == [] and len(owner.get("/api/spools").get_json()) == 2


def test_a_part_with_an_unknown_unit_names_its_section_and_changes_nothing(owner):
    fill(owner)
    doc = backup(owner).get_json()
    doc["parts"][0]["unit"] = "liter"
    res = owner.post("/api/backup/restore", json=doc, headers=H)
    assert res.status_code == 400 and res.get_json()["error"].startswith("Parts, line 1")
    assert [p["name"] for p in owner.get("/api/parts").get_json()] == ["JST-connector"]


def test_a_calculation_without_a_number_gets_the_next_free_one(owner):
    first = make(owner, "/api/projects", sheet_payload())
    second = make(owner, "/api/projects", {**sheet_payload(), "name": "Tweede"})
    doc = backup(owner).get_json()
    doc["projects"][0].pop("number")                                                        # one without, one with (2)
    assert owner.post("/api/backup/restore", json=doc, headers=H).status_code == 200
    numbers = {p["name"]: p["number"] for p in owner.get("/api/projects").get_json()}
    assert numbers[second["name"]] == 2 and numbers[first["name"]] == 3


@pytest.mark.parametrize("change, expected", [
    (lambda d: d["orders"][0].update(customer_name=""), "Bestellingen"),
    (lambda d: d["orders"][0].update(status="klaar"), "Bestellingen"),
    (lambda d: d["orders"][0].update(number=0), "Bestellingen"),
    (lambda d: d["orders"].append(copy.deepcopy(d["orders"][0])), "Bestellingen"),
    (lambda d: d["orders"][0]["lines"][0].update(quantity=0), "Bestellingen"),
    (lambda d: d["invoice_template"].update(content_b64="!!geen base64!!"), "Factuursjabloon"),
    (lambda d: d["invoice_template"].update(kind="docx"), "Factuursjabloon"),
    (lambda d: d["invoice_pdfs"][0].update(content_b64=base64.b64encode(b"geen pdf").decode()), "Factuur-PDF"),
    (lambda d: d["invoice_pdfs"][0].update(content_b64="!!geen base64!!"), "Factuur-PDF"),
    (lambda d: d["invoice_pdfs"][0].update(order_id="geen-uuid"), "Factuur-PDF"),
    (lambda d: d.update(invoice_pdfs="geen lijst"), "Factuur-PDF"),
    (lambda d: d["invoice_logo"].update(content_b64="!!geen base64!!"), "Logo"),
    (lambda d: d["invoice_logo"].update(content_b64=base64.b64encode(b"geen plaatje").decode()), "Logo"),
    (lambda d: d["invoice_logo"].update(content_b64=base64.b64encode(b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 1)).decode()), "Logo"),
    (lambda d: d["projects"][0].update(number=5) or d["projects"].append({**d["projects"][0], "id": "11111111-1111-1111-1111-111111111111"}), "Berekeningen"),
])
def test_a_damaged_order_or_template_is_refused_before_anything_changes(owner, change, expected):
    fill_orders(owner)
    doc = backup(owner).get_json()
    change(doc)
    before = order_snapshot(owner)
    res = owner.post("/api/backup/restore", json=doc, headers=H)
    assert res.status_code == 400 and expected in res.get_json()["error"]
    assert order_snapshot(owner) == before


def test_the_backup_holds_the_template_but_no_credentials(owner):
    fill_orders(owner)
    text = backup(owner).get_data(as_text=True)
    assert '"invoice_template"' in text and "credential_id" not in text and "recovery" not in text


def test_a_backup_from_before_the_logo_and_the_new_order_fields_still_restores(owner):
    fill_orders(owner)
    old = backup(owner).get_json()
    old.pop("invoice_logo")
    for order in old["orders"]:
        order.pop("customer_number"), order.pop("subject")
    assert owner.post("/api/backup/restore", json=old, headers=H).status_code == 200
    (order,) = owner.get("/api/orders").get_json()
    detail = owner.get(f"/api/orders/{order['id']}").get_json()
    assert (detail["customer_number"], detail["subject"]) == ("", "") and owner.get("/api/invoice-logo").get_json()["logo"] is None


def test_a_kept_invoice_for_an_order_that_is_not_in_the_file_is_let_go(owner):
    fill_orders(owner)
    doc = backup(owner).get_json()
    stray = copy.deepcopy(doc["invoice_pdfs"][0])
    stray["order_id"] = "22222222-2222-2222-2222-222222222222"
    doc["invoice_pdfs"].append(stray)
    doc["invoice_pdfs"][0]["invoice_number"] = "ANDERS-1"                      # a number that is not the order's: not trusted either
    assert owner.post("/api/backup/restore", json=doc, headers=H).status_code == 200
    order_id = doc["orders"][0]["id"]
    assert owner.get(f"/api/orders/{order_id}/invoice").status_code == 404


def test_customers_travel_in_the_backup_with_their_numbers_and_links(owner):
    fill_orders(owner)
    extra = customer(owner, name="Zonder bestelling", number="Z1", notes="Nog geen order")
    doc = backup(owner).get_json()
    assert {c["number"] for c in doc["customers"]} == {"K9999", "Z1"} and doc["orders"][0]["customer_id"]
    before = order_snapshot(owner)
    owner.delete(f"/api/orders/{doc['orders'][0]['id']}", headers=H)
    owner.delete(f"/api/customers/{extra['id']}", headers=H)
    res = owner.post("/api/backup/restore", json=doc, headers=H)
    assert res.status_code == 200 and res.get_json()["summary"]["customers"] == 2
    assert order_snapshot(owner) == before and owner.get(f"/api/customers/{extra['id']}").get_json()["notes"] == "Nog geen order"


def test_a_backup_from_before_customers_gets_customers_made_from_its_orders(owner):
    fill_orders(owner)
    new_order_ = owner.get("/api/orders").get_json()[0]
    doc = backup(owner).get_json()
    old = copy.deepcopy(doc)
    old.pop("customers")
    second = copy.deepcopy(old["orders"][0])
    second.update(id="33333333-3333-3333-3333-333333333333", number=2, invoice_number=None, customer_number="", customer_name="Els")
    old["orders"].append(second)
    old["invoice_pdfs"] = []
    for order in old["orders"]:
        order.pop("customer_id")
    res = owner.post("/api/backup/restore", json=old, headers=H)
    assert res.status_code == 200, res.get_json()
    customers_ = {c["name"]: c for c in owner.get("/api/customers").get_json()}
    assert customers_["Jan Jansen"]["number"] == "K9999" and customers_["Els"]["number"] == "1"
    listed = {o["customer_name"]: o for o in owner.get("/api/orders").get_json()}
    assert listed["Jan Jansen"]["customer_id"] == customers_["Jan Jansen"]["id"] and listed["Els"]["customer_number"] == "1"
    assert new_order_["customer_name"] == "Jan Jansen"


@pytest.mark.parametrize("change", [
    lambda d: d["customers"][0].update(name=""), lambda d: d["customers"][0].update(number=""),
    lambda d: d["customers"].append(copy.deepcopy(d["customers"][0])), lambda d: d["customers"][0].update(id="geen-uuid"),
    lambda d: d["customers"][0].update(email="geen-adres"), lambda d: d.update(customers="geen lijst"),
])
def test_a_damaged_customer_is_refused_before_anything_changes(owner, change):
    fill_orders(owner)
    doc = backup(owner).get_json()
    change(doc)
    before = order_snapshot(owner)
    res = owner.post("/api/backup/restore", json=doc, headers=H)
    assert res.status_code == 400 and "Klanten" in res.get_json()["error"]
    assert order_snapshot(owner) == before
