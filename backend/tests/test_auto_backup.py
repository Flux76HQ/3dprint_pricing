"""Automatic backups: every 12 hours a ZIP with everything (print files, orders with their invoices, template and logo) in
DATA_PATH/backups/auto, the newest 14 kept; listed, downloaded and restored from Settings -> Beheer -> Back-up, through the same check and job as an
uploaded backup."""
import base64
import json
import os
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app import auto_backup, backup as backup_module
from tests import printfiles as pf
from tests.conftest import connect
from tests.test_auth_api import H, onboard, post
from tests.test_backup import fill, fill_orders, order_snapshot, restore_job, snapshot, staged_files, wipe, with_file
from tests.test_password import PASSWORD, _reset_limits, code_for, enable  # noqa: F401  (_reset_limits: an autouse fixture)

T0 = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)
NL = {**H, "X-Lang": "nl"}


@pytest.fixture(autouse=True)
def _inline(monkeypatch):
    """A restore runs in a thread; here it runs on the spot (test_backup.py tests the thread)."""
    monkeypatch.setattr(backup_module, "_start", lambda *args: backup_module._run_restore(*args))


@pytest.fixture
def owner(client):
    client.passkey, _ = onboard(client)
    return client


def folder(app):
    return app.config["APP_CONFIG"].backup_dir


def kept(app):
    """The automatic backups in the folder, oldest first."""
    return sorted(n for n in os.listdir(folder(app)) if auto_backup.NAME.fullmatch(n)) if os.path.isdir(folder(app)) else []


def everything(owner):
    meta, project = with_file(owner)
    _project, order, paper = fill_orders(owner)
    return meta, project, order, paper


# --- making them ------------------------------------------------------------------------------------------------------

def test_a_backup_holds_everything_print_files_and_invoices_included(owner, app):
    meta, project, order, paper = everything(owner)
    path = auto_backup.run_once(app, T0)
    assert path is not None and kept(app) == ["printpricing-auto-2026-11-04-080000Z.zip"]
    archive = zipfile.ZipFile(path)
    assert archive.read("files/part.stl") == pf.stl_binary()                       # the model, loose, as in a download with print files
    doc = json.loads(archive.read("backup.json"))
    assert doc["format"] == backup_module.FORMAT and doc["includes_files"] and doc["files"][0]["archive_path"] == "files/part.stl"
    kept_pdf = owner.get(f"/api/orders/{order['id']}/invoice").data
    assert [o["invoice_number"] for o in doc["orders"]] == [order["invoice_number"]] and doc["invoice_pdfs"][0]["invoice_number"] == order["invoice_number"]
    assert base64.b64decode(doc["invoice_pdfs"][0]["content_b64"]) == kept_pdf
    assert base64.b64decode(doc["invoice_template"]["content_b64"]) == paper and doc["invoice_logo"]["kind"] == "png"
    assert len(doc["projects"]) == 3 and doc["printers"] and doc["spools"] and doc["customers"]
    assert doc["preferences"]["business"]["name"] == "Flux76 Prints"                # the owner's preferences and the business's
    assert not [n for n in os.listdir(folder(app)) if n.startswith(".")]             # no half-written file left behind


def test_nothing_that_unlocks_the_app_is_in_an_automatic_backup(owner, app):
    everything(owner)
    owner.post("/api/push/subscribe", json={"endpoint": "https://push.example.test/x", "keys": {"p256dh": "a", "auth": "b"}}, headers=H)
    text = zipfile.ZipFile(auto_backup.run_once(app, T0)).read("backup.json").decode().lower()
    for word in ("credential", "public_key", "recovery", "password", "totp", "secret", "salt", "code_hash", "endpoint", "p256dh"):
        assert word not in text, word


def test_one_every_12_hours(owner, app):
    assert auto_backup.run_once(app, T0) is not None
    assert auto_backup.run_once(app, T0 + timedelta(hours=11, minutes=59)) is None
    assert auto_backup.run_once(app, T0 + timedelta(hours=12)) is not None
    assert kept(app) == ["printpricing-auto-2026-11-04-080000Z.zip", "printpricing-auto-2026-11-04-200000Z.zip"]


def test_the_newest_14_are_kept_so_after_a_week_a_new_one_replaces_the_oldest(owner, app):
    os.makedirs(folder(app))
    for other in ("pre-update-2026-11-01-120000.sqlite3", "notes.txt"):                # not ours: left alone
        with open(os.path.join(folder(app), other), "w") as handle:
            handle.write("x")
    for n in range(16):
        assert auto_backup.run_once(app, T0 + n * auto_backup.INTERVAL) is not None
    names = kept(app)
    assert len(names) == 14
    assert names[0] == "printpricing-auto-2026-11-05-080000Z.zip"                    # the first two (11-04 08:00 and 20:00) made room
    assert names[-1] == "printpricing-auto-2026-11-11-200000Z.zip"
    assert {"pre-update-2026-11-01-120000.sqlite3", "notes.txt"} <= set(os.listdir(folder(app)))


def test_none_is_made_before_the_app_is_set_up(client, app):
    assert auto_backup.run_once(app, T0) is None and kept(app) == []


def test_none_is_made_while_a_restore_replaces_the_data(owner, app):
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        conn.execute("INSERT INTO backup_jobs DEFAULT VALUES")                         # running
    assert auto_backup.run_once(app, T0) is None
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        conn.execute("UPDATE backup_jobs SET status = 'done'")
    assert auto_backup.run_once(app, T0) is not None


def test_two_workers_at_once_make_one(owner, app):
    with_file(owner)
    start, results = threading.Barrier(3), []

    def worker():
        start.wait()
        results.append(auto_backup.run_once(app, T0))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert len([r for r in results if r]) == 1 and len(kept(app)) == 1


def test_a_worker_that_holds_the_lock_is_left_alone_until_its_lock_expires(owner, app):
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S.000")
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        conn.execute("INSERT INTO app_state (key, value) VALUES ('lock:auto-backup', %s)", (later,))
    assert auto_backup.run_once(app, T0) is None
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        conn.execute("UPDATE app_state SET value = '2000-01-01 00:00:00.000' WHERE key = 'lock:auto-backup'")     # its worker died
    assert auto_backup.run_once(app, T0) is not None


def test_a_failure_keeps_the_backups_there_are_says_why_and_is_tried_again_after_an_hour(owner, app, monkeypatch):
    assert auto_backup.run_once(app, T0) is not None
    before = {n: os.path.getsize(os.path.join(folder(app), n)) for n in kept(app)}

    def full(doc, attachments, handle):
        handle.write(b"half a backup")
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(backup_module, "write_zip", full)
    failed_at = T0 + timedelta(hours=12)
    assert auto_backup.run_once(app, failed_at) is None
    assert {n: os.path.getsize(os.path.join(folder(app), n)) for n in kept(app)} == before
    assert os.listdir(folder(app)) == list(before)                                     # the half-written file is gone
    state = owner.get("/api/backup/auto", headers=NL).get_json()
    assert state["error"]["at"] == failed_at.isoformat() and "No space left on device" in state["error"]["message"]
    assert "mislukt" in state["error"]["message"] and state["next_at"] == (failed_at + auto_backup.RETRY).isoformat()
    monkeypatch.undo()
    monkeypatch.setattr(backup_module, "_start", lambda *args: backup_module._run_restore(*args))
    assert auto_backup.run_once(app, failed_at + timedelta(minutes=59)) is None        # not every few minutes against a full disk
    assert auto_backup.run_once(app, failed_at + auto_backup.RETRY) is not None
    assert owner.get("/api/backup/auto").get_json()["error"] is None                   # a success clears it


def test_an_unexpected_failure_points_at_the_log(owner, app, monkeypatch):
    monkeypatch.setattr(backup_module, "document", lambda *args, **kw: 1 / 0)
    assert auto_backup.run_once(app, T0) is None and kept(app) == []
    message = owner.get("/api/backup/auto", headers={**H, "X-Lang": "en"}).get_json()["error"]["message"]
    assert "container's log" in message and "ZeroDivision" not in message


def test_a_backup_left_half_written_by_a_crash_is_cleared(owner, app):
    os.makedirs(folder(app))
    old, new = os.path.join(folder(app), ".tmp-old"), os.path.join(folder(app), ".tmp-new")
    for path in (old, new):
        with open(path, "wb") as handle:
            handle.write(b"PK")
    hours_ago = time.time() - 3 * 3600
    os.utime(old, (hours_ago, hours_ago))
    auto_backup.run_once(app, T0)
    assert not os.path.exists(old) and os.path.exists(new)                             # a recent one may be another worker's, being written now


def test_the_loop_makes_the_first_one_soon_after_the_start_and_not_again_before_it_is_due(owner, app):
    stop = threading.Event()
    thread = auto_backup.start_worker(app, first_seconds=0, every_seconds=0.05, stop=stop)
    try:
        deadline = time.monotonic() + 15
        while not kept(app) and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)                                                                 # a few more rounds
        assert len(kept(app)) == 1
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()


# --- the screen --------------------------------------------------------------------------------------------------------

def test_the_list_shows_them_newest_first_with_their_size_and_when_the_next_one_is_due(owner, app):
    state = owner.get("/api/backup/auto").get_json()
    assert state["backups"] == [] and state["keep"] == 14 and state["interval_hours"] == 12 and state["error"] is None
    assert abs(datetime.fromisoformat(state["next_at"]) - datetime.now(timezone.utc)) < timedelta(minutes=1)      # none yet: due now
    auto_backup.run_once(app, T0)
    auto_backup.run_once(app, T0 + auto_backup.INTERVAL)
    state = owner.get("/api/backup/auto").get_json()
    assert [b["name"] for b in state["backups"]] == ["printpricing-auto-2026-11-04-200000Z.zip", "printpricing-auto-2026-11-04-080000Z.zip"]
    assert state["backups"][0]["created_at"] == (T0 + auto_backup.INTERVAL).isoformat()
    assert state["backups"][0]["size"] == os.path.getsize(os.path.join(folder(app), state["backups"][0]["name"]))
    assert state["next_at"] == (T0 + 2 * auto_backup.INTERVAL).isoformat()


def test_a_backup_is_downloaded_as_the_zip_it_is(owner, app):
    with_file(owner)
    path = auto_backup.run_once(app, T0)
    res = owner.get(f"/api/backup/auto/{path.name}")
    assert res.status_code == 200 and res.mimetype == "application/zip"
    assert res.headers["Content-Disposition"] == f"attachment; filename={path.name}"
    assert int(res.headers["Content-Length"]) == os.path.getsize(path) and res.data == path.read_bytes()


@pytest.mark.parametrize("name", ["printpricing-auto-2026-01-01-000000Z.zip", "..%2Fdb%2Fprintpricing.sqlite3", "notes.txt", "printpricing-auto-x.zip"])
def test_only_a_backup_that_is_there_can_be_downloaded_or_staged(owner, app, name):
    os.makedirs(folder(app))
    with open(os.path.join(folder(app), "notes.txt"), "w") as handle:
        handle.write("not a backup")
    assert owner.get(f"/api/backup/auto/{name}").status_code == 404
    assert post(owner, f"/api/backup/auto/{name}/stage").status_code in (404, 405)      # a name with a slash in it never reaches the route


def test_a_kept_backup_is_restored_through_the_same_check_and_job_and_stays_where_it_is(owner, app):
    meta, project, order, paper = everything(owner)
    before, before_orders = snapshot(owner), order_snapshot(owner)
    path = auto_backup.run_once(app, T0)
    original = path.read_bytes()
    wipe(owner)
    owner.delete(f"/api/orders/{order['id']}", headers=H)
    owner.delete("/api/invoice-template", headers=H)
    assert snapshot(owner) != before
    answer = post(owner, f"/api/backup/auto/{path.name}/stage", headers=NL)
    assert answer.status_code == 200, answer.get_json()
    summary = answer.get_json()["summary"]
    assert summary["files"] == 1 and summary["orders"] == 1 and summary["template"] == 1 and summary["created_at"]
    assert owner.get("/api/orders").get_json() == []                                    # staging changes nothing
    job = restore_job(owner, answer.get_json()["token"])
    assert job["status"] == "done", job
    assert snapshot(owner) == before and order_snapshot(owner) == before_orders
    assert owner.get(f"/api/print-files/{meta['id']}/download").data == pf.stl_binary()
    assert path.read_bytes() == original and staged_files(app) == []                   # the kept one stays; its staged copy is gone


def test_a_damaged_kept_backup_is_refused_before_anything_changes_and_nothing_is_left_staged(owner, app):
    with_file(owner)
    before = snapshot(owner)
    os.makedirs(folder(app))
    damaged = os.path.join(folder(app), "printpricing-auto-2026-11-04-080000Z.zip")
    with open(damaged, "wb") as handle:
        handle.write(b"PK\x03\x04 not really a zip")
    res = post(owner, "/api/backup/auto/printpricing-auto-2026-11-04-080000Z.zip/stage", headers=NL)
    assert res.status_code == 400 and "beschadigd" in res.get_json()["error"]
    assert staged_files(app) == [] and os.path.exists(damaged) and snapshot(owner) == before


# --- the settings: on or off, how often, how many to keep ------------------------------------------------------------------------

def settings(owner, **body):
    res = owner.put("/api/backup/auto", json=body, headers=H)
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_the_defaults_are_on_every_half_day_and_the_fourteen_newest(owner):
    state = owner.get("/api/backup/auto").get_json()
    assert state["settings"] == {"enabled": True, "keep": 14, "every_days": 0.5}
    assert state["options"] == {"every_days": [0.5, 1, 2, 7, 14], "max_keep": 60}


def test_the_settings_are_saved_and_a_partial_change_keeps_the_rest(owner):
    assert settings(owner, enabled=False)["settings"] == {"enabled": False, "keep": 14, "every_days": 0.5}
    assert settings(owner, keep=60, every_days=14)["settings"] == {"enabled": False, "keep": 60, "every_days": 14.0}
    assert owner.get("/api/backup/auto").get_json()["settings"]["keep"] == 60


@pytest.mark.parametrize("every", [0.5, 1, 2, 7, 14])
def test_every_choice_of_frequency_is_accepted(owner, every):
    assert settings(owner, every_days=every)["settings"]["every_days"] == float(every)


@pytest.mark.parametrize("keep", [0, 1, 14, 60])
def test_the_number_to_keep_may_be_zero_to_sixty(owner, keep):
    assert settings(owner, keep=keep)["settings"]["keep"] == keep


@pytest.mark.parametrize("body", [{"keep": 61}, {"keep": -1}, {"keep": 1.5}, {"keep": "14"}, {"keep": True}, {"keep": None},
                                  {"every_days": 0.75}, {"every_days": 3}, {"every_days": 0}, {"every_days": "1"}, {"every_days": True},
                                  {"enabled": "yes"}, {"enabled": 1}])
def test_anything_else_is_refused_and_changes_nothing(owner, body):
    before = owner.get("/api/backup/auto").get_json()["settings"]
    res = owner.put("/api/backup/auto", json=body, headers=H)
    assert res.status_code == 400 and res.get_json()["error"]
    assert owner.get("/api/backup/auto").get_json()["settings"] == before


def test_the_refusals_say_what_is_allowed(owner):
    assert "0 tot en met 60" in owner.put("/api/backup/auto", json={"keep": 61}, headers=NL).get_json()["error"]
    assert "0,5, 1, 2, 7 of 14" in owner.put("/api/backup/auto", json={"every_days": 3}, headers=NL).get_json()["error"]


@pytest.mark.parametrize("every,gap,due", [(0.5, timedelta(hours=11), False), (0.5, timedelta(hours=12), True), (1, timedelta(hours=23), False), (1, timedelta(days=1), True),
                                           (2, timedelta(days=1, hours=23), False), (2, timedelta(days=2), True), (7, timedelta(days=6), False), (7, timedelta(days=7), True),
                                           (14, timedelta(days=13), False), (14, timedelta(days=14), True)])
def test_the_next_one_is_due_when_the_chosen_time_has_passed(owner, app, every, gap, due):
    settings(owner, every_days=every)
    assert auto_backup.run_once(app, T0) is not None
    assert (auto_backup.run_once(app, T0 + gap) is not None) is due
    if not due:
        assert owner.get("/api/backup/auto").get_json()["next_at"] == (T0 + timedelta(days=every)).isoformat()


def test_only_the_chosen_number_is_kept_and_other_files_are_left_alone(owner, app):
    settings(owner, keep=3)
    os.makedirs(folder(app), exist_ok=True)
    for name in ("pre-update-2026-10-01-100000.sqlite3.gz", "my-own-copy.zip"):
        with open(os.path.join(folder(app), name), "wb") as handle:
            handle.write(b"not an automatic backup")
    for n in range(6):
        assert auto_backup.run_once(app, T0 + n * auto_backup.INTERVAL) is not None
    assert kept(app) == ["printpricing-auto-2026-11-05-200000Z.zip", "printpricing-auto-2026-11-06-080000Z.zip", "printpricing-auto-2026-11-06-200000Z.zip"]
    assert "pre-update-2026-10-01-100000.sqlite3.gz" in os.listdir(folder(app)) and "my-own-copy.zip" in os.listdir(folder(app))


def test_lowering_the_number_removes_the_surplus_at_once(owner, app):
    for n in range(5):
        auto_backup.run_once(app, T0 + n * auto_backup.INTERVAL)
    assert len(kept(app)) == 5
    state = settings(owner, keep=2)
    assert len(kept(app)) == 2 and len(state["backups"]) == 2
    assert kept(app)[-1] == "printpricing-auto-2026-11-06-080000Z.zip"                  # the newest stay


def test_keeping_none_removes_them_and_makes_no_more(owner, app):
    auto_backup.run_once(app, T0)
    settings(owner, keep=0)
    assert kept(app) == []
    assert auto_backup.run_once(app, T0 + timedelta(days=9)) is None and kept(app) == []
    assert owner.get("/api/backup/auto").get_json()["next_at"] is None


def test_switched_off_none_is_made_and_the_ones_there_stay(owner, app):
    auto_backup.run_once(app, T0)
    settings(owner, enabled=False)
    assert auto_backup.run_once(app, T0 + timedelta(days=30)) is None and len(kept(app)) == 1
    assert owner.get("/api/backup/auto").get_json()["next_at"] is None
    settings(owner, enabled=True)
    assert auto_backup.run_once(app, T0 + timedelta(days=30)) is not None


def test_a_factory_reset_puts_the_defaults_back_and_keeps_the_backups(owner, app):
    settings(owner, keep=5, enabled=False)
    from app import db
    with app.extensions["pool"].connection() as conn:
        conn.execute("DELETE FROM app_state")                                           # what a reset does to every table
    assert owner.get("/api/backup/auto").get_json()["settings"] == {"enabled": True, "keep": 14, "every_days": 0.5}


# --- made by hand: *Maak back-up* keeps its backup on the server, and only there --------------------------------------------------

def make_now(owner, files, headers=H):
    return owner.post("/api/backup/auto", json={"files": files}, headers=headers)


def path_of(app, name):
    return os.path.join(folder(app), name)


def test_a_backup_made_by_hand_is_kept_on_the_server_with_or_without_the_print_files_and_listed(owner, app):
    with_file(owner)
    res = make_now(owner, True)
    assert res.status_code == 200, res.get_json()
    zipped = res.get_json()["backup"]
    assert auto_backup.MANUAL.fullmatch(zipped["name"]) and zipped["name"].endswith(".zip")
    assert zipped["kind"] == "manual" and zipped["with_files"] is True and zipped["size"] == os.path.getsize(path_of(app, zipped["name"]))
    archive = zipfile.ZipFile(path_of(app, zipped["name"]))
    assert archive.read("files/part.stl") == pf.stl_binary() and json.loads(archive.read("backup.json"))["includes_files"]
    assert owner.get("/api/about").get_json()["backups"]["downloaded"]["with_files"] is True        # Over still knows when the last one was made

    plain = make_now(owner, False).get_json()["backup"]
    assert plain["name"].endswith(".json") and plain["kind"] == "manual" and plain["with_files"] is False
    with open(path_of(app, plain["name"]), "rb") as handle:
        kept_bytes = handle.read()
    doc = json.loads(kept_bytes)
    assert doc["format"] == backup_module.FORMAT and doc["includes_files"] is False and doc["projects"] and "files" not in doc
    res = owner.get(f"/api/backup/auto/{plain['name']}")                                           # downloaded from the list as it is kept
    assert res.status_code == 200 and res.mimetype == "application/json" and res.data == kept_bytes
    assert res.headers["Content-Disposition"] == f"attachment; filename={plain['name']}"

    listed = owner.get("/api/backup/auto").get_json()["backups"]
    assert {b["name"]: (b["kind"], b["with_files"]) for b in listed} == {zipped["name"]: ("manual", True), plain["name"]: ("manual", False)}
    assert not [n for n in os.listdir(folder(app)) if n.startswith(".")]                           # no half-written file left behind


def test_the_list_shows_both_kinds_newest_first(owner, app):
    auto_backup.run_once(app, T0)
    with app.app_context():
        manual, _ = auto_backup.keep_manual(owner_id(app), False, T0 + timedelta(hours=1))
    auto_backup.run_once(app, T0 + auto_backup.INTERVAL)
    listed = owner.get("/api/backup/auto").get_json()["backups"]
    assert [(b["name"], b["kind"]) for b in listed] == [("printpricing-auto-2026-11-04-200000Z.zip", "auto"),
                                                       (manual.name, "manual"), ("printpricing-auto-2026-11-04-080000Z.zip", "auto")]
    assert manual.name == "printpricing-manual-2026-11-04-090000Z.json"


def owner_id(app):
    with connect(app.config["APP_CONFIG"].database_path) as conn:
        return conn.execute("SELECT id FROM users WHERE is_owner").fetchone()[0]


def test_two_in_the_same_second_never_overwrite_each_other(owner, app):
    with app.app_context():
        first, _ = auto_backup.keep_manual(owner_id(app), False, T0)
        second, _ = auto_backup.keep_manual(owner_id(app), False, T0)
    assert (first.name, second.name) == ("printpricing-manual-2026-11-04-080000Z.json", "printpricing-manual-2026-11-04-080001Z.json")
    assert first.exists() and second.exists()


def test_the_rotation_never_counts_or_removes_one_kept_by_hand(owner, app):
    made = make_now(owner, False).get_json()["backup"]["name"]
    settings(owner, keep=1)
    for n in range(3):
        assert auto_backup.run_once(app, T0 + n * auto_backup.INTERVAL) is not None                # the one by hand does not postpone them
    assert len(kept(app)) == 1 and os.path.exists(path_of(app, made))
    settings(owner, keep=0)                                                                        # keeping no automatic ones
    assert kept(app) == [] and os.path.exists(path_of(app, made))
    assert [b["name"] for b in owner.get("/api/backup/auto").get_json()["backups"]] == [made]


def test_when_the_server_cannot_keep_it_the_answer_says_why_and_nothing_half_written_stays(owner, app, monkeypatch):
    with_file(owner)

    def full(doc, attachments, handle):
        handle.write(b"half a backup")
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(backup_module, "write_zip", full)
    res = make_now(owner, True, NL)
    assert res.status_code == 507 and "No space left on device" in res.get_json()["error"] and "bewaard" in res.get_json()["error"]
    assert owner.get("/api/backup/auto").get_json()["backups"] == [] and os.listdir(folder(app)) == []     # nothing half-written stays


def test_one_kept_by_hand_is_restored_through_the_same_check_and_job_and_stays_where_it_is(owner, app):
    fill(owner)
    before = snapshot(owner)
    name = make_now(owner, False).get_json()["backup"]["name"]
    original = open(path_of(app, name), "rb").read()
    wipe(owner)
    assert snapshot(owner) != before
    answer = post(owner, f"/api/backup/auto/{name}/stage", headers=NL)
    assert answer.status_code == 200, answer.get_json()
    job = restore_job(owner, answer.get_json()["token"])
    assert job["status"] == "done", job
    assert snapshot(owner) == before
    assert open(path_of(app, name), "rb").read() == original and staged_files(app) == []


# --- removing one: only with a fresh confirmation, bound to that one backup ---------------------------------------------------------

def proof(owner, name, action="backup-delete"):
    options = post(owner, "/api/auth/stepup/options", {"action": action, "target": name}).get_json()
    return owner.passkey.assert_(options)


def delete(owner, name, body, headers=H):
    return owner.delete(f"/api/backup/auto/{name}", json=body, headers=headers)


def test_a_backup_is_removed_only_with_a_fresh_confirmation_for_exactly_that_one(owner, app):
    automatic = auto_backup.run_once(app, T0).name
    manual = make_now(owner, False).get_json()["backup"]["name"]
    assert delete(owner, manual, {}).status_code == 400                                            # no proof at all
    assert delete(owner, manual, {"credential": proof(owner, automatic)}).status_code == 403       # a confirmation for the other backup
    assert delete(owner, manual, {"credential": proof(owner, manual, "factory-reset")}).status_code == 403     # for another action
    assert delete(owner, manual, {"current_password": PASSWORD, "code": "000000"}).status_code == 409          # password login is not on
    assert os.path.exists(path_of(app, manual)) and os.path.exists(path_of(app, automatic))

    res = delete(owner, manual, {"credential": proof(owner, manual)})
    assert res.status_code == 200 and [b["name"] for b in res.get_json()["backups"]] == [automatic]
    assert not os.path.exists(path_of(app, manual))
    res = delete(owner, automatic, {"credential": proof(owner, automatic)})                         # an automatic one just the same
    assert res.status_code == 200 and res.get_json()["backups"] == [] and kept(app) == []


def test_a_confirmation_removes_one_backup_once(owner, app):
    name = make_now(owner, False).get_json()["backup"]["name"]
    credential = proof(owner, name)
    assert delete(owner, name, {"credential": credential}).status_code == 200
    with app.app_context():
        again, _ = auto_backup.keep_manual(owner_id(app), False, auto_backup._moment(name))       # the same name once more
    assert again.name == name
    assert delete(owner, name, {"credential": credential}).status_code == 403 and os.path.exists(again)


@pytest.mark.parametrize("name", ["printpricing-manual-2026-01-01-000000Z.json", "printpricing-manual-2026-01-01-000000Z.txt", "notes.txt",
                                  "..%2Fdb%2Fprintpricing.sqlite3"])
def test_only_a_backup_that_is_there_can_be_removed_and_a_wrong_name_spends_no_confirmation(owner, app, name):
    made = make_now(owner, False).get_json()["backup"]["name"]
    with open(path_of(app, "notes.txt"), "w") as handle:
        handle.write("not a backup")
    credential = proof(owner, made)
    assert delete(owner, name, {"credential": credential}).status_code in (404, 405)               # a name with a slash in it never reaches the route
    assert os.path.exists(path_of(app, "notes.txt"))
    assert delete(owner, made, {"credential": credential}).status_code == 200


def test_with_password_login_the_password_and_a_code_remove_it_and_a_wrong_one_counts(owner, app):
    secret, _ = enable(owner)
    name = make_now(owner, False).get_json()["backup"]["name"]
    assert delete(owner, name, {"current_password": "wrong wrong wrong wrong", "code": code_for(secret, 1)}).status_code == 401
    assert os.path.exists(path_of(app, name))
    assert delete(owner, name, {"current_password": PASSWORD, "code": code_for(secret, 1)}).status_code == 200
    assert not os.path.exists(path_of(app, name))
