"""Prepare the database. Run by the container entrypoint before the server starts.

An installation from before the SQLite releases is moved over first: with `LEGACY_DATABASE_URL` set (docker-compose.yml does it) and no SQLite file
yet, the PostgreSQL data is imported once (app/pg_import.py). Then the schema is brought up to date. Any failure stops the container.
"""
from pathlib import Path

from app.config import load_config
from app.db import run_migrations

# Where the PostgreSQL release kept its data inside the container (DATA_PATH/postgres on the host).
OLD_DATABASE_FOLDER = Path("/data/postgres")


def prepare(cfg, old_folder: Path = OLD_DATABASE_FOLDER) -> str:
    """Import the old database if there is one to import, then migrate. Returns what to print."""
    said = []
    if cfg.legacy_database_url:
        from app.pg_import import maybe_import
        counts = maybe_import(cfg.legacy_database_url, cfg.database_path)
        if counts is not None:
            said.append(f"Imported the PostgreSQL database from the earlier release: {sum(counts.values())} rows in {sum(1 for n in counts.values() if n)} tables.")
    elif (old_folder / "PG_VERSION").exists() and not Path(cfg.database_path).exists():
        raise SystemExit(f"{old_folder} holds the PostgreSQL database of an earlier release and there is no SQLite database yet. Starting now would begin "
                         "with an empty database. Start the stack with the docker-compose.yml of the release that still has the db service, and let it "
                         "import once (docs/handleiding.md, 'Overstap naar SQLite').")
    done = run_migrations(cfg.database_path)
    said.append(f"Migrations applied: {', '.join(done) if done else 'none (up to date)'}")
    return "\n".join(said)


if __name__ == "__main__":
    print(prepare(load_config()))
