"""Where the data lives, and that an update cannot lose it.

The database is one SQLite file in `DATA_PATH/db`, the uploads are in `DATA_PATH/uploads`, and the app container sees the whole of DATA_PATH as /data.
The PostgreSQL of the earlier releases is still in `DATA_PATH/postgres` for the one-time import. Nothing is a Docker volume: `docker compose down -v`
or a prune must not be able to touch it.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def mounts(service: str) -> list[str]:
    """The volume lines of one service of docker-compose.yml, without comments."""
    block = re.search(rf"^  {service}:\n(.*?)(?=^  \w|\Z)", COMPOSE, re.S | re.M).group(1)
    volumes = re.search(r"^    volumes:\n((?:      .*\n)+)", block, re.M)
    lines = [re.sub(r"\s+#.*$", "", line.strip()) for line in volumes.group(1).splitlines() if not line.strip().startswith("#")]
    return [line[2:] for line in lines if line.startswith("- ")]


def test_the_old_database_is_a_folder_in_the_data_path_and_the_app_sees_the_whole_data_path():
    assert mounts("db") == ["${DATA_PATH}/postgres:/var/lib/postgresql/data"]
    assert mounts("app") == ["${DATA_PATH}:/data"]                                # the SQLite file is DATA_PATH/db/printpricing.sqlite3 in it


def test_the_database_is_a_file_in_the_data_folder_and_the_old_one_is_handed_over_once():
    from app.config import DEFAULT_DATABASE_PATH
    assert DEFAULT_DATABASE_PATH == "/data/db/printpricing.sqlite3"
    assert "LEGACY_DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}" in COMPOSE
    assert "DATABASE_URL:" not in COMPOSE.replace("LEGACY_DATABASE_URL:", "")


def test_nothing_in_the_compose_file_is_a_docker_volume():
    assert not re.search(r"^volumes:", COMPOSE, re.M)                          # no named volumes declared
    for line in mounts("db") + mounts("app"):
        assert line.split(":")[0].startswith("${DATA_PATH}"), line               # and every mount is a host folder under DATA_PATH


def test_one_tag_picks_the_image_and_tells_the_app_which_channel_it_is():
    """PRINTPRICING_TAG (latest or beta, set in .env) chooses the image and is passed on, so a beta build can show it is one."""
    assert "image: ghcr.io/flux76hq/3dprint_pricing:${PRINTPRICING_TAG:-latest}" in COMPOSE
    assert "PRINTPRICING_TAG: ${PRINTPRICING_TAG:-latest}" in COMPOSE
    assert re.search(r"^PRINTPRICING_TAG=latest$", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M)       # stable unless chosen otherwise


def test_the_uploads_are_where_the_app_looks_for_them():
    from app.config import Config
    assert Config.__dataclass_fields__["upload_dir"].default == "/data/uploads"      # DATA_PATH/uploads on the host


def test_the_entrypoint_and_the_image_carry_the_migration_and_do_not_take_over_the_data_path():
    entry = (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")
    assert '/migrate_uploads.sh /data/app/uploads "$UPLOAD_DIR"' in entry
    commands = "\n".join(line.split("#")[0] for line in entry.splitlines())
    assert not re.search(r"chown[^\n]*\s/data(\s|$)", commands)                 # /data is the host's DATA_PATH: only the uploads folder is handed to `app`
    assert "WARNING: /data is not a mounted folder" in entry
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "deploy/migrate_uploads.sh" in dockerfile and "chmod +x /entrypoint.sh /migrate_uploads.sh" in dockerfile
    assert "backend/backup_db.py" in dockerfile and "mkdir -p /data/uploads /data/db" in dockerfile
    assert 'chown app:app "$UPLOAD_DIR" "$DB_DIR"' in entry                                  # the two folders the app writes in, not /data itself


@pytest.mark.parametrize("script", ["deploy/entrypoint.sh", "deploy/migrate_uploads.sh", "scripts/update.sh", "scripts/migrate_data.sh"])
def test_the_shell_scripts_parse(script):
    assert subprocess.run(["sh", "-n", str(ROOT / script)]).returncode == 0


# --- the move of the uploads of earlier releases ---------------------------------------------------------------------

def migrate(old: Path, new: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(ROOT / "deploy" / "migrate_uploads.sh"), str(old), str(new)], capture_output=True, text=True)


@pytest.fixture
def data(tmp_path):
    """A DATA_PATH as an older release left it: uploads in app/uploads, next to the database folder."""
    (tmp_path / "postgres").mkdir()
    (tmp_path / "postgres" / "PG_VERSION").write_text("17")
    old = tmp_path / "app" / "uploads"
    old.mkdir(parents=True)
    return tmp_path, old, tmp_path / "uploads"


def test_the_uploads_of_an_earlier_release_move_to_the_new_folder_with_their_content(data):
    root, old, new = data
    (old / "a1b2.3mf").write_bytes(b"model one")
    (old / "c3d4.stl").write_bytes(b"model two")
    (old / ".tmp-leftover").write_bytes(b"x")
    done = migrate(old, new)
    assert done.returncode == 0 and "moved 3 file(s)" in done.stdout
    assert {p.name: p.read_bytes() for p in new.iterdir()} == {"a1b2.3mf": b"model one", "c3d4.stl": b"model two", ".tmp-leftover": b"x"}
    assert not (root / "app").exists()                                          # the empty old folders are gone
    assert (root / "postgres" / "PG_VERSION").read_text() == "17"               # and the database folder was never touched


def test_running_it_again_or_without_an_old_folder_does_nothing(data):
    root, old, new = data
    (old / "a.3mf").write_bytes(b"1")
    assert migrate(old, new).returncode == 0
    again = migrate(old, new)
    assert again.returncode == 0 and again.stdout == "" and again.stderr == ""
    assert [p.name for p in new.iterdir()] == ["a.3mf"]
    assert migrate(root / "nothing" / "here", new).returncode == 0


def test_a_file_that_is_already_in_the_new_folder_is_never_overwritten(data):
    root, old, new = data
    new.mkdir()
    (new / "same.3mf").write_bytes(b"new one")
    (old / "same.3mf").write_bytes(b"old one")
    (old / "other.3mf").write_bytes(b"other")
    done = migrate(old, new)
    assert done.returncode == 0 and "same.3mf exists" in done.stderr
    assert (new / "same.3mf").read_bytes() == b"new one" and (old / "same.3mf").read_bytes() == b"old one"      # both kept
    assert (new / "other.3mf").read_bytes() == b"other" and old.exists()                                         # the old folder stays while it has a file


def test_the_same_folder_is_left_alone(data):
    root, old, new = data
    (old / "a.3mf").write_bytes(b"1")
    assert migrate(old, old).returncode == 0 and (old / "a.3mf").read_bytes() == b"1"


def test_names_with_spaces_move_too(data):
    root, old, new = data
    (old / "my model.3mf").write_bytes(b"1")
    assert migrate(old, new).returncode == 0 and (new / "my model.3mf").read_bytes() == b"1"


# --- DATA_PATH is an absolute folder of the host --------------------------------------------------------------------------

def test_a_new_installation_gets_an_absolute_data_path():
    """./data is resolved by whatever tool starts the stack (Dockhand on Unraid: a RAM disk), so no template or helper may hand it out."""
    example = re.search(r"^DATA_PATH=(.*)$", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M).group(1)
    assert example.startswith("/")
    assert "DATA_PATH: ${DATA_PATH:?" in COMPOSE                                # compose refuses to start without it, and the app gets to see it
    init_env = subprocess.run(["python3", str(ROOT / "scripts" / "init_env.py"), "--data-path", "./data"], capture_output=True, text=True)
    assert init_env.returncode != 0 and "absolute" in init_env.stderr and not (ROOT / ".env").exists()


def run_entrypoint_as_root_warning(data_path: str) -> str:
    entry = (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")
    block = re.search(r'(case "\$\{DATA_PATH:-\}" in.*?\n  esac)', entry, re.S).group(1)
    return subprocess.run(["sh", "-c", block], env={"DATA_PATH": data_path, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True).stderr


def test_the_entrypoint_warns_about_a_relative_data_path_only():
    assert "relative path" in run_entrypoint_as_root_warning("./data")
    assert run_entrypoint_as_root_warning("/mnt/user/appdata/printpricing") == ""
    assert run_entrypoint_as_root_warning("") == ""


# --- scripts/migrate_data.sh: data that sits in another folder than DATA_PATH ------------------------------------------------

@pytest.fixture
def stack(tmp_path):
    """A stack folder with a .env and a fake `docker` that reports where the db container keeps the database."""
    folder = tmp_path / "stack"
    bin_dir = tmp_path / "bin"
    folder.mkdir()
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(
        "#!/bin/sh\n"
        'echo "$*" >> "$FAKE_LOG"\n'
        'case "$*" in\n'
        '  "compose ps -aq db") [ -z "$FAKE_SOURCE" ] || echo abc123 ;;\n'
        '  "inspect "*) echo "$FAKE_SOURCE" ;;\n'
        "esac\n", encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    return folder, bin_dir, tmp_path / "log"


def migrate_data(stack, data_path, source="", *args):
    folder, bin_dir, log = stack
    (folder / ".env").write_text(f"DATA_PATH={data_path}\n", encoding="utf-8")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_SOURCE": str(source), "FAKE_LOG": str(log)}
    done = subprocess.run(["sh", str(ROOT / "scripts" / "migrate_data.sh"), *args], cwd=folder, env=env, capture_output=True, text=True)
    return done, (log.read_text() if log.exists() else "")


def wrong_place(tmp_path):
    """The data where a relative DATA_PATH once ended up: postgres/ and uploads/ in a folder that is not DATA_PATH."""
    old = tmp_path / "ram" / "data"
    (old / "postgres").mkdir(parents=True)
    (old / "postgres" / "PG_VERSION").write_text("17")
    (old / "uploads").mkdir()
    (old / "uploads" / "a.3mf").write_bytes(b"model")
    return old


def test_data_in_another_folder_is_copied_to_the_data_path_and_the_old_folder_stays(stack, tmp_path):
    old, new = wrong_place(tmp_path), tmp_path / "array" / "printpricing"
    done, log = migrate_data(stack, new, old / "postgres")
    assert done.returncode == 0, done.stderr
    assert (new / "postgres" / "PG_VERSION").read_text() == "17" and (new / "uploads" / "a.3mf").read_bytes() == b"model"
    assert (old / "postgres" / "PG_VERSION").exists()                           # nothing is deleted
    assert "compose stop" in log and str(old) in done.stdout                    # the stack is stopped first, and the old folder is named


def test_nothing_happens_when_the_data_is_already_in_the_data_path_or_there_is_no_installation(stack, tmp_path):
    new = tmp_path / "array" / "printpricing"
    (new / "postgres").mkdir(parents=True)
    done, log = migrate_data(stack, new, new / "postgres")
    assert done.returncode == 0 and "already" in done.stdout and "compose stop" not in log
    done, log = migrate_data(stack, new, "")                                    # no db container: a new installation
    assert done.returncode == 0 and "compose stop" not in log


def test_it_refuses_a_relative_data_path_and_a_target_that_already_has_a_database(stack, tmp_path):
    old, new = wrong_place(tmp_path), tmp_path / "array" / "printpricing"
    done, log = migrate_data(stack, "./data", old / "postgres")
    assert done.returncode != 0 and "relative" in done.stderr and "compose stop" not in log
    (new / "postgres").mkdir(parents=True)
    (new / "postgres" / "PG_VERSION").write_text("17")
    done, log = migrate_data(stack, new, old / "postgres")
    assert done.returncode != 0 and "already holds a database" in done.stderr and "compose stop" not in log


def test_check_changes_nothing(stack, tmp_path):
    old, new = wrong_place(tmp_path), tmp_path / "array" / "printpricing"
    done, log = migrate_data(stack, new, old / "postgres", "--check")
    assert done.returncode == 0 and "would" in done.stdout and "compose stop" not in log and not new.exists()


# --- the database file ----------------------------------------------------------------------------------------------------

def warning_for(filesystem: str, tmp_path) -> str:
    """The entrypoint's check of the file system the database folder is on, with `stat` replaced by one that names `filesystem`."""
    entry = (ROOT / "deploy" / "entrypoint.sh").read_text(encoding="utf-8")
    block = re.search(r'(  case "\$\(stat -f -c %T "\$DB_DIR".*?\n  esac)', entry, re.S).group(1)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "stat").write_text(f"#!/bin/sh\necho {filesystem}\n", encoding="utf-8")
    (bin_dir / "stat").chmod(0o755)
    return subprocess.run(["sh", "-c", block], env={"DB_DIR": "/data/db", "PATH": f"{bin_dir}:/usr/bin:/bin"}, capture_output=True, text=True).stderr


@pytest.mark.parametrize("filesystem", ["nfs", "nfs4", "cifs", "smb2", "fuse", "fuseblk", "9p"])
def test_the_entrypoint_warns_when_the_database_folder_is_on_a_network_or_fuse_file_system(filesystem, tmp_path):
    assert "SQLite can lose data" in warning_for(filesystem, tmp_path)


@pytest.mark.parametrize("filesystem", ["ext2/ext3", "xfs", "btrfs", "zfs", "overlayfs", "tmpfs"])
def test_it_is_quiet_on_a_local_file_system(filesystem, tmp_path):
    assert warning_for(filesystem, tmp_path) == ""


def test_the_start_is_refused_when_an_old_database_is_there_and_nothing_hands_it_over(tmp_path):
    """Starting on an empty database next to a PostgreSQL folder full of data would look like lost data, and nothing would import it afterwards."""
    import migrate
    from app.config import Config
    old = tmp_path / "postgres"
    old.mkdir()
    (old / "PG_VERSION").write_text("17")
    cfg = Config(database_path=str(tmp_path / "db" / "printpricing.sqlite3"), session_secret="x" * 40, setup_code="s", rp_id="", rp_name="", rp_origins=(),
                 session_hours=1, cookie_secure=False, static_dir="")
    with pytest.raises(SystemExit, match="empty database"):
        migrate.prepare(cfg, old)
    assert not (tmp_path / "db").exists()
    assert "Migrations applied: 0001_init.sql" in migrate.prepare(cfg, tmp_path / "no-postgres-here")                 # a new installation just starts
    assert migrate.prepare(cfg, old).endswith("none (up to date)")                                                      # and once there is a database, the old folder is ignored


def test_the_refusal_is_the_message_also_when_the_old_folder_cannot_be_looked_into(tmp_path, monkeypatch):
    """/data/postgres belongs to the postgres user (mode 0700) and the app runs as `app`: a file in it cannot even be stat-ed. That used to end in a
    PermissionError and a restart loop with no explanation."""
    import os
    import migrate
    from app.config import Config
    old = tmp_path / "postgres"
    old.mkdir()
    (old / "PG_VERSION").write_text("17")
    real = os.stat

    def stat(path, *args, **kwargs):
        if str(path).startswith(str(old) + os.sep):
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    cfg = Config(database_path=str(tmp_path / "db" / "printpricing.sqlite3"), session_secret="x" * 40, setup_code="s", rp_id="", rp_name="", rp_origins=(),
                 session_hours=1, cookie_secure=False, static_dir="")
    with pytest.raises(SystemExit, match="empty database"):
        migrate.prepare(cfg, old)


def test_a_compose_file_from_before_the_switch_still_hands_the_old_database_over(monkeypatch):
    """An installation whose docker-compose.yml was never replaced still sets DATABASE_URL (to the PostgreSQL); that is what gets imported."""
    from app.config import load_config
    for name, value in (("SESSION_SECRET", "s" * 40), ("SETUP_CODE", "code")):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://printpricing:pw@db:5432/printpricing")
    assert load_config().legacy_database_url == "postgresql://printpricing:pw@db:5432/printpricing"
    monkeypatch.setenv("LEGACY_DATABASE_URL", "postgresql://other@db/other")                                       # the new name wins
    assert load_config().legacy_database_url == "postgresql://other@db/other"
    monkeypatch.delenv("LEGACY_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", "/data/db/something.sqlite3")                                                 # anything else is not a PostgreSQL
    assert load_config().legacy_database_url == ""
    monkeypatch.delenv("DATABASE_URL")
    assert load_config().legacy_database_url == ""


def test_the_online_backup_copies_a_database_that_is_in_use(tmp_path):
    import sqlite3
    from app.db import Database, run_migrations
    path = tmp_path / "db" / "printpricing.sqlite3"
    run_migrations(str(path))
    database = Database(str(path))
    with database.connection() as conn:
        conn.execute("INSERT INTO users (display_name) VALUES ('Anna')")
    target = tmp_path / "backups" / "copy.sqlite3"
    env = {"DATABASE_PATH": str(path), "SESSION_SECRET": "x" * 40, "SETUP_CODE": "s", "PATH": "/usr/bin:/bin"}
    done = subprocess.run([sys.executable, str(ROOT / "backend" / "backup_db.py"), str(target)], cwd=ROOT / "backend", env={**env, "PYTHONPATH": str(ROOT / "backend")},
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert sqlite3.connect(target).execute("SELECT display_name FROM users").fetchone() == ("Anna",)
    again = subprocess.run([sys.executable, str(ROOT / "backend" / "backup_db.py"), str(target)], cwd=ROOT / "backend", env={**env, "PYTHONPATH": str(ROOT / "backend")},
                           capture_output=True, text=True)
    assert again.returncode != 0 and "exists already" in again.stderr                                              # never over a backup
