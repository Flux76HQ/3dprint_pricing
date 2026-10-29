"""Copy the database to a file, safely while the app is running: `python backup_db.py /data/backups/name.sqlite3`.

Uses SQLite's online backup, so the copy is one consistent moment even in the middle of writes (copying the file itself would not be:
part of the newest data may still be in the -wal file). scripts/update.sh calls this before an update; it works as well by hand.
"""
import sqlite3
import sys
from pathlib import Path

from app.config import load_config
from app.db import _open

if len(sys.argv) != 2:
    sys.exit("Usage: python backup_db.py <file to write>")
target = Path(sys.argv[1])
if target.exists():
    sys.exit(f"{target} exists already; not overwriting it.")
source_path = load_config().database_path
if not Path(source_path).exists():
    sys.exit(f"No database at {source_path}.")
target.parent.mkdir(parents=True, exist_ok=True)
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
try:
    copy = sqlite3.connect(str(target))
    try:
        source.backup(copy)
    finally:
        copy.close()
    check = _open(str(target))                       # through the app's own connection: the indexes on lower_u() need the function it registers
    try:
        verdict = check.execute("PRAGMA integrity_check").fetchone()["integrity_check"]
    finally:
        check.close()
finally:
    source.close()
if verdict != "ok":
    target.unlink(missing_ok=True)
    sys.exit(f"The copy is not sound ({verdict}); removed.")
print(f"Database copied to {target} ({target.stat().st_size} bytes).")
