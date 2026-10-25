"""Where the data lives, and that an update cannot lose it.

The database is a folder on the host (`DATA_PATH/postgres`), the uploads are in `DATA_PATH/uploads`, and the app container sees the
whole of DATA_PATH as /data. Nothing is a Docker volume: `docker compose down -v` or a prune must not be able to touch it.
"""
import re
import subprocess
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


def test_the_database_is_a_folder_in_the_data_path_and_the_app_sees_the_whole_data_path():
    assert mounts("db") == ["${DATA_PATH}/postgres:/var/lib/postgresql/data"]
    assert mounts("app") == ["${DATA_PATH}:/data"]


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


@pytest.mark.parametrize("script", ["deploy/entrypoint.sh", "deploy/migrate_uploads.sh", "scripts/update.sh"])
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
