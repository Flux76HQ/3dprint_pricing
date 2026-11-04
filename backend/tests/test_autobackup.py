"""Automatic backups: a gzipped copy of the database in DATA_PATH/backups, on a schedule, the oldest removed."""
import gzip
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import autobackup, db
from tests.test_auth_api import H
from tests.test_domain_api import owner  # noqa: F401  (fixture)

START = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)


def settings(owner, **body):
    res = owner.put("/api/backup/auto", json=body, headers=H)
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def run(app, now=START, **kwargs):
    with app.app_context():
        return autobackup.run_once(now, **kwargs)


def folder(app) -> Path:
    return Path(app.config["APP_CONFIG"].database_path).parent.parent / "backups"


def names(app):
    return sorted(p.name for p in folder(app).iterdir()) if folder(app).exists() else []


def test_the_defaults_are_on_every_half_day_and_the_fourteen_newest(owner):
    body = owner.get("/api/backup/auto").get_json()
    assert body["settings"] == {"enabled": True, "keep": 14, "every_days": 0.5} and body["last"] is None
    assert body["options"] == {"every_days": [0.5, 1, 2, 7, 14], "max_keep": 60} and body["files"] == {"count": 0, "newest": None}


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
    assert "0 tot en met 60" in owner.put("/api/backup/auto", json={"keep": 61}, headers=H).get_json()["error"]
    assert "0,5, 1, 2, 7 of 14" in owner.put("/api/backup/auto", json={"every_days": 3}, headers=H).get_json()["error"]


def test_the_first_look_makes_a_backup_that_is_a_whole_database(owner, app):
    made = run(app)
    assert made["ok"] is True and made["name"] == "auto-2026-11-04-120000.sqlite3.gz" and made["size_bytes"] > 0
    path = folder(app) / made["name"]
    raw = path.parent / "restored.sqlite3"
    raw.write_bytes(gzip.decompress(path.read_bytes()))
    copy = db._open(str(raw))
    assert copy.execute("SELECT count(*) AS n FROM users").fetchone()["n"] == 1                # the signed-in owner is in it
    assert copy.execute("PRAGMA integrity_check").fetchone()["integrity_check"] == "ok"
    assert [n for n in names(app) if n.startswith(".")] == []                                   # no half-made files left behind
    assert owner.get("/api/backup/auto").get_json()["last"]["name"] == made["name"]


@pytest.mark.parametrize("every,gap,due", [(0.5, timedelta(hours=11), False), (0.5, timedelta(hours=12), True), (1, timedelta(hours=23), False), (1, timedelta(days=1), True),
                                           (2, timedelta(days=1, hours=23), False), (2, timedelta(days=2), True), (7, timedelta(days=6), False), (7, timedelta(days=7), True),
                                           (14, timedelta(days=13), False), (14, timedelta(days=14), True)])
def test_a_backup_is_due_when_the_chosen_time_has_passed(owner, app, every, gap, due):
    settings(owner, every_days=every)
    assert run(app, START) is not None
    again = run(app, START + gap)
    assert (again is not None) is due


def test_only_the_newest_ones_are_kept_and_other_files_are_left_alone(owner, app):
    settings(owner, keep=3, every_days=0.5)
    folder(app).mkdir(exist_ok=True)
    (folder(app) / "pre-update-2026-10-01-100000.sqlite3.gz").write_bytes(b"from update.sh")
    (folder(app) / "my-own-copy.sqlite3").write_bytes(b"by hand")
    for n in range(6):
        assert run(app, START + timedelta(hours=12 * n)) is not None
    auto = [n for n in names(app) if n.startswith("auto-")]
    assert auto == ["auto-2026-11-06-000000.sqlite3.gz", "auto-2026-11-06-120000.sqlite3.gz", "auto-2026-11-07-000000.sqlite3.gz"]
    assert "pre-update-2026-10-01-100000.sqlite3.gz" in names(app) and "my-own-copy.sqlite3" in names(app)


def test_lowering_the_number_removes_the_surplus_at_once(owner, app):
    for n in range(5):
        run(app, START + timedelta(hours=12 * n))
    assert owner.get("/api/backup/auto").get_json()["files"]["count"] == 5
    assert settings(owner, keep=2)["files"]["count"] == 2


def test_keeping_none_removes_them_and_makes_no_more(owner, app):
    run(app)
    run(app, START + timedelta(days=1))
    assert settings(owner, keep=0)["files"] == {"count": 0, "newest": None}
    assert run(app, START + timedelta(days=9)) is None and [n for n in names(app) if n.startswith("auto-")] == []
    res = owner.post("/api/backup/auto/run", json={}, headers=H)
    assert res.status_code == 409 and "0" in res.get_json()["error"]


def test_switched_off_nothing_is_made_and_what_is_there_stays(owner, app):
    run(app)
    settings(owner, enabled=False)
    assert run(app, START + timedelta(days=30)) is None
    assert len([n for n in names(app) if n.startswith("auto-")]) == 1


def test_a_backup_on_request_ignores_the_schedule(owner, app):
    run(app)
    made = owner.post("/api/backup/auto/run", json={}, headers=H).get_json()
    assert made["made"]["ok"] is True and made["files"]["count"] >= 1


def test_a_failure_is_recorded_leaves_nothing_behind_and_is_tried_again_after_an_hour(owner, app, monkeypatch):
    def broken(self, target):
        Path(target).write_bytes(b"half")
        raise OSError("disk exploded")
    monkeypatch.setattr(db.Database, "backup_to", broken)
    failed = run(app)
    assert failed["ok"] is False and "disk exploded" in failed["error"]
    assert names(app) == [] and owner.get("/api/backup/auto").get_json()["last"]["ok"] is False
    assert run(app, START + timedelta(minutes=30)) is None                                      # not every minute
    monkeypatch.undo()
    again = run(app, START + timedelta(minutes=61))                                             # after an hour, not after twelve
    assert again["ok"] is True and len(names(app)) == 1


def test_too_little_free_space_is_a_recorded_failure_not_a_half_file(owner, app, monkeypatch):
    class Usage:
        free = 1024
    monkeypatch.setattr(autobackup.shutil, "disk_usage", lambda path: Usage)
    failed = run(app)
    assert failed["ok"] is False and "free disk space" in failed["error"] and names(app) == []


def test_two_workers_at_the_same_moment_make_one_backup(owner, app):
    results = []

    def go():
        results.append(run(app))

    threads = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(r is not None for r in results) == 1 and len([n for n in names(app) if n.startswith("auto-")]) == 1


def test_the_app_can_go_on_writing_while_the_copy_is_made(owner, app, monkeypatch):
    original, wrote = db.Database.backup_to, []

    def copy_while_writing(self, target):
        with app.extensions["pool"].connection() as conn:                                          # would fail if the backup held the write lock
            conn.execute("INSERT INTO app_state (key, value) VALUES ('during-backup', 'y')")
        wrote.append(True)
        return original(self, target)

    monkeypatch.setattr(db.Database, "backup_to", copy_while_writing)
    assert run(app)["ok"] is True and wrote == [True]


# --- who may, and what the About page makes of it ----------------------------------------------------------------

def test_the_about_page_counts_the_automatic_copies_and_warns_about_a_failed_attempt(owner, app, monkeypatch):
    run(app, datetime.now(timezone.utc))
    about = owner.get("/api/about").get_json()
    assert about["backups"]["copies"]["latest"]["name"].startswith("auto-") and about["backups"]["old"] is False
    assert about["backups"]["auto"]["settings"]["keep"] == 14 and about["backups"]["auto"]["last"]["ok"] is True
    states = {c["key"]: c for c in about["health"]["checks"]}
    assert states["auto_backup"]["state"] == "ok" and states["auto_backup"]["value"] is None

    monkeypatch.setattr(db.Database, "backup_to", lambda self, target: (_ for _ in ()).throw(OSError("no space left")))
    run(app, datetime.now(timezone.utc) + timedelta(days=3))
    states = {c["key"]: c for c in owner.get("/api/about").get_json()["health"]["checks"]}
    assert states["auto_backup"]["state"] == "warn" and states["auto_backup"]["detail"] == "no space left"


def test_switched_off_is_a_choice_not_a_warning(owner, app):
    settings(owner, enabled=False)
    check = {c["key"]: c for c in owner.get("/api/about").get_json()["health"]["checks"]}["auto_backup"]
    assert check["state"] == "ok" and check["value"] == "off"


def test_a_factory_reset_is_the_same_as_new_settings(owner, app):
    settings(owner, keep=5, enabled=False)
    with app.extensions["pool"].connection() as conn:
        conn.execute("DELETE FROM app_state")                                                       # what a reset does to every table
    assert owner.get("/api/backup/auto").get_json()["settings"] == {"enabled": True, "keep": 14, "every_days": 0.5}
