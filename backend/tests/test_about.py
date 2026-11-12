"""Settings → Beheer → Over (what runs) and → Systeem (how healthy the database is, how the app is connected to it). For administrators only."""
import dataclasses
import json

import pytest

from app import about, db
from tests.test_auth_api import H
from tests.test_domain_api import owner  # noqa: F401  (fixture)


def get(owner):
    res = owner.get("/api/about")
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def states(body):
    return {c["key"]: c["state"] for c in body["health"]["checks"]}


def test_it_says_what_is_running(owner, app):
    body = get(owner)["app"]
    from app import VERSION
    assert body["name"] == "3D Print Pricing" and body["version"] == VERSION and body["channel"] in ("stable", "beta")
    assert body["python"].count(".") == 2 and body["flask"] and body["repository"].startswith("https://github.com/")
    assert body["uptime_seconds"] >= 0 and body["started_at"].endswith("+00:00")
    assert set(body["features"]) == {"push", "ai_images", "spoolman", "update_check"}


def test_a_healthy_database_is_ok_in_every_check(owner, app):
    body = get(owner)
    assert states(body) == {"reachable": "ok", "write_lock": "ok", "journal": "ok", "foreign_keys": "ok", "schema": "ok", "filesystem": "ok",
                            "disk_space": "ok", "wal_size": "ok", "auto_backup": "ok"}
    assert body["health"]["state"] == "ok"
    assert [c["key"] for c in body["health"]["checks"]][0] == "reachable"


def test_it_shows_the_active_link_with_the_database(owner, app):
    link, database = get(owner)["link"], get(owner)["database"]
    assert link["kind"] == "sqlite" and link["driver"] == "sqlite3" and link["path"] == app.config["APP_CONFIG"].database_path
    assert link["journal_mode"] == "wal" and link["foreign_keys"] is True and link["synchronous"] == 2 and link["busy_timeout_ms"] > 0
    assert link["worker_pid"] > 0
    assert database["engine"] == "SQLite" and database["version"].count(".") >= 2 and database["size_bytes"] > 0
    assert database["tables"] == len(database["rows"]) >= 25 and database["rows"]["users"] == 1
    assert database["migrations"]["applied"][0]["filename"] == "0001_init.sql" and database["migrations"]["pending"] == []


def test_the_old_postgresql_is_shown_without_its_login(owner, app):
    assert get(owner)["link"]["legacy"] == {"configured": False, "address": None, "imported_at": None, "old_data_folder": False, "state": "none"}
    app.config["APP_CONFIG"] = dataclasses.replace(app.config["APP_CONFIG"], legacy_database_url="postgresql://printpricing:s3cret-pw@db:5432/printpricing")
    res = owner.get("/api/about")
    legacy = res.get_json()["link"]["legacy"]
    assert legacy["configured"] is True and legacy["address"] == "db:5432/printpricing" and legacy["state"] == "unused"
    assert "s3cret-pw" not in res.get_data(as_text=True) and "printpricing:" not in legacy["address"]


def test_an_import_that_has_happened_is_reported(owner, app):
    with app.extensions["pool"].connection() as conn:
        conn.execute("INSERT INTO app_state (key, value) VALUES ('imported_from_postgres', %s)", (json.dumps({"at": "2026-10-29 08:20:00.000", "rows": {}}),))
    legacy = get(owner)["link"]["legacy"]
    assert legacy["state"] == "imported" and legacy["imported_at"] == "2026-10-29 08:20:00.000"


def test_a_network_or_fuse_file_system_is_a_warning(owner, monkeypatch):
    monkeypatch.setattr(about, "filesystem_of", lambda path: "fuse.shfs")
    body = get(owner)
    assert states(body)["filesystem"] == "warn" and body["health"]["state"] == "warn" and body["link"]["network_filesystem"] is True
    monkeypatch.setattr(about, "filesystem_of", lambda path: "ext4")
    assert states(get(owner))["filesystem"] == "ok"


@pytest.mark.parametrize("filesystem,network", [("nfs4", True), ("cifs", True), ("smb3", True), ("fuse", True), ("fuseblk", True), ("9p", True),
                                                 ("ext4", False), ("xfs", False), ("btrfs", False), ("zfs", False), ("overlay", False), ("tmpfs", False)])
def test_which_file_systems_count_as_unsafe_for_sqlite(owner, monkeypatch, filesystem, network):
    monkeypatch.setattr(about, "filesystem_of", lambda path: filesystem)
    assert get(owner)["link"]["network_filesystem"] is network


def test_the_file_system_comes_from_the_mount_table(tmp_path):
    assert about.filesystem_of(str(tmp_path)) not in (None, "")
    assert about.filesystem_of("/nonexistent/place/db.sqlite3") is not None            # the root file system


EVERY_MIGRATION = sorted(p.name for p in db.MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def test_a_database_that_is_behind_its_migrations_is_an_error(owner, app):
    with app.extensions["pool"].connection() as conn:
        conn.execute("DELETE FROM schema_migrations")
    body = get(owner)
    assert states(body)["schema"] == "error" and body["health"]["state"] == "error"
    assert body["database"]["migrations"]["pending"] == EVERY_MIGRATION


def test_a_migration_that_changed_after_it_was_applied_is_an_error(owner, app):
    with app.extensions["pool"].connection() as conn:
        conn.execute("UPDATE schema_migrations SET checksum = 'edited'")
    assert get(owner)["database"]["migrations"]["changed"] == EVERY_MIGRATION and states(get(owner))["schema"] == "error"


def test_a_migration_of_a_newer_release_is_a_warning(owner, app):
    with app.extensions["pool"].connection() as conn:
        conn.execute("INSERT INTO schema_migrations (filename, checksum) VALUES ('0099_from_the_future.sql', 'x')")
    assert states(get(owner))["schema"] == "warn" and get(owner)["database"]["migrations"]["unknown"] == ["0099_from_the_future.sql"]


def test_a_slow_write_lock_and_a_big_wal_file_are_warnings(owner, monkeypatch):
    monkeypatch.setattr(about, "SLOW_LOCK_SECONDS", -1)
    monkeypatch.setattr(about, "BIG_WAL_BYTES", -1)
    monkeypatch.setattr(about, "LOW_DISK_BYTES", 1 << 62)
    assert {k: v for k, v in states(get(owner)).items() if v != "ok"} == {"write_lock": "warn", "wal_size": "warn", "disk_space": "warn"}


def test_a_database_that_stops_answering_is_reported_not_crashed(owner, app, monkeypatch):
    """The sign-in check runs first and uses the database too, so this is about the page's own queries failing."""
    real = app.extensions["pool"]

    class Broken:
        path = real.path

        def connection(self):
            raise db.sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(about, "pool", lambda: Broken())
    res = owner.get("/api/about")
    assert res.status_code == 200 and res.get_json()["health"] == {"state": "error", "checks": [{"key": "reachable", "state": "error", "detail": "OperationalError"}]}


def test_the_thorough_check_passes_on_a_sound_database(owner):
    res = owner.post("/api/about/check", json={}, headers=H)
    body = res.get_json()
    assert res.status_code == 200 and body["ok"] is True and body["quick_check"] == ["ok"] and body["foreign_key_violations"] == [] and body["seconds"] >= 0


def test_the_thorough_check_finds_a_row_that_points_at_nothing(owner, app):
    import sqlite3
    raw = sqlite3.connect(app.config["APP_CONFIG"].database_path)
    raw.execute("PRAGMA foreign_keys = OFF")
    raw.execute("INSERT INTO webauthn_credentials (user_id, credential_id, public_key) VALUES ('00000000-0000-4000-8000-000000000000', x'01', x'02')")
    raw.commit()
    raw.close()
    body = owner.post("/api/about/check", json={}, headers=H).get_json()
    assert body["ok"] is False and body["foreign_key_violations"] == [{"table": "webauthn_credentials", "parent": "users"}]


def test_the_check_does_not_hold_up_a_writer(owner, app):
    """It reads on a connection of its own, so the app can write while it runs (the write lock is not taken)."""
    import threading
    done, result = [], {}
    thread = threading.Thread(target=lambda: result.update(app.extensions["pool"].check()))
    with app.extensions["pool"].connection() as conn:                  # we hold the write lock...
        thread.start()
        thread.join(5)                                                 # ...and the check finishes anyway
        done.append(not thread.is_alive())
        conn.execute("INSERT INTO app_state (key, value) VALUES ('x', 'y')")
    assert done == [True] and result["ok"] is True


def test_every_text_the_about_screen_names_exists_in_both_languages():
    """The screen picks some texts from tables (`HEALTH_CHECKS`, `SYNC_MODES`), which the usual check of `t('...')` calls cannot see."""
    import re
    from pathlib import Path
    front = Path(__file__).resolve().parents[2] / "frontend"
    source = (front / "js" / "settings.js").read_text(encoding="utf-8")
    start = source.index("// --- About:")
    named = set(re.findall(r"'(about\.\w+)'", source[start:source.index("// The parts of the settings")])) | {"settings.tab_about"}
    for language in ("nl", "en"):
        catalog = json.loads((front / "lang" / f"{language}.json").read_text(encoding="utf-8"))
        assert sorted(k for k in named if k not in catalog) == [], language
    assert len(named) > 60


# --- the last backup -------------------------------------------------------------------------------------------

def make_copy(app, name, days_ago, size=10):
    import os
    import time
    from pathlib import Path
    folder = Path(app.config["APP_CONFIG"].database_path).parent.parent / "backups"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(b"x" * size)
    stamp = time.time() - days_ago * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_no_backup_at_all_is_flagged_but_the_database_is_still_healthy(owner, app):
    body = get(owner)
    assert body["backups"]["newest_at"] is None and body["backups"]["age_days"] is None and body["backups"]["old"] is True
    assert body["backups"]["copies"] == {"count": 0, "latest": None} and body["backups"]["downloaded"] is None
    assert body["health"]["state"] == "ok"                             # a fresh installation has none yet: not a reason for "Let op"


def test_a_backup_made_in_the_app_is_remembered(owner):
    assert owner.get("/api/backup").status_code == 200
    first = get(owner)["backups"]
    assert first["downloaded"]["with_files"] is False and first["age_days"] == 0 and first["old"] is False
    assert owner.get("/api/backup?files=1").status_code == 200
    assert get(owner)["backups"]["downloaded"]["with_files"] is True


def test_the_copies_of_update_sh_count_and_the_newest_wins(owner, app):
    make_copy(app, "pre-update-2026-09-20-101500.sqlite3.gz", 40)
    make_copy(app, "pre-update-2026-10-30-101500.sqlite3.gz", 3, size=2048)
    make_copy(app, "pre-update-2026-08-01-090000.sql.gz", 90)             # from the PostgreSQL days
    make_copy(app, "notes.txt", 0)                                        # not a backup
    make_copy(app, ".hidden.gz", 0)
    backups = get(owner)["backups"]
    assert backups["copies"]["count"] == 3
    assert backups["copies"]["latest"]["name"] == "pre-update-2026-10-30-101500.sqlite3.gz" and backups["copies"]["latest"]["size_bytes"] == 2048
    assert backups["age_days"] == 3 and backups["old"] is False


def test_the_newer_of_a_copy_and_a_download_is_the_last_backup(owner, app):
    make_copy(app, "pre-update-2026-09-01-101500.sqlite3.gz", 60)
    assert get(owner)["backups"]["old"] is True and get(owner)["backups"]["age_days"] == 60
    owner.get("/api/backup")
    assert get(owner)["backups"]["old"] is False and get(owner)["backups"]["age_days"] == 0


def test_an_automatic_backup_counts_as_the_last_backup(owner, app):
    from datetime import datetime, timedelta, timezone
    from app import auto_backup
    make_copy(app, "pre-update-2026-10-01-101500.sqlite3.gz", 40)
    assert get(owner)["backups"]["automatic"] == {"count": 0, "latest": None} and get(owner)["backups"]["old"] is True
    made = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0)
    path = auto_backup.run_once(app, made)
    backups = get(owner)["backups"]
    assert backups["automatic"] == {"count": 1, "latest": {"name": path.name, "size_bytes": path.stat().st_size, "at": made.isoformat()}}
    assert backups["newest_at"] == made.isoformat() and backups["age_days"] == 2 and backups["old"] is False
    assert backups["copies"]["count"] == 1                                # the automatic backups are not counted as update copies


def test_a_garbled_note_about_the_last_backup_is_ignored(owner, app):
    with app.extensions["pool"].connection() as conn:
        conn.execute("INSERT INTO app_state (key, value) VALUES ('last_backup', 'not json')")
    assert get(owner)["backups"]["downloaded"] is None


def test_a_factory_reset_forgets_the_last_backup(owner, app):
    owner.get("/api/backup")
    with app.extensions["pool"].connection() as conn:
        assert conn.execute("SELECT 1 FROM app_state WHERE key = 'last_backup'").fetchone()
        conn.execute("DELETE FROM app_state")                              # what the reset does to every table (tests/test_system.py covers the reset itself)
    assert get(owner)["backups"]["downloaded"] is None


def test_a_failed_automatic_backup_warns_and_switched_off_is_a_choice(owner, app, monkeypatch):
    from datetime import datetime, timezone
    from app import auto_backup, backup as backup_module
    states = lambda: {c["key"]: c for c in get(owner)["health"]["checks"]}
    assert states()["auto_backup"]["state"] == "ok" and states()["auto_backup"]["value"] is None

    def full(doc, attachments, handle):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(backup_module, "write_zip", full)
    auto_backup.run_once(app, datetime.now(timezone.utc))
    assert states()["auto_backup"]["state"] == "warn" and "No space left" in states()["auto_backup"]["detail"]

    monkeypatch.undo()
    owner.put("/api/backup/auto", json={"enabled": False}, headers=H)
    off = states()["auto_backup"]
    assert off["value"] == "off"
