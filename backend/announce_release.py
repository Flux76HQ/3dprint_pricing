"""Tell subscribed devices that a new version is running. Run by the container entrypoint after migrations.

The first run on a fresh install only records the version (nobody needs an announcement for what they
just installed). Later runs announce when the version or commit changed, once, however many containers
or workers start: the state row is claimed atomically.
"""
import sys

from app import push
from app.i18n import DEFAULT_LANGUAGE, translate, user_language
from app.config import load_config
from app.db import make_pool


def announce(pool, cfg, label: str) -> int:
    with pool.connection() as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = 'announced_release'").fetchone()
        if row is None:
            conn.execute("INSERT INTO app_state (key, value) VALUES ('announced_release', %s) ON CONFLICT DO NOTHING", (label,))
            return 0
        claimed = conn.execute("UPDATE app_state SET value = %s WHERE key = 'announced_release' AND value <> %s RETURNING key",
                               (label, label)).fetchone()
        if claimed is None:
            return 0
        users = [u for u in conn.execute("SELECT id, preferences FROM users WHERE role = 'admin'").fetchall()
                 if str(u["preferences"].get("notify_release", True)).lower() != "false"]
    if not cfg.push_configured:
        return 0
    sent = 0
    for user in users:
        lang = user_language(user["id"], pool) or DEFAULT_LANGUAGE          # each person is told in their own language
        result = push.notify(pool, cfg, user["id"], "release", translate(lang, "push.test_title"),
                             translate(lang, "push.release_body", label=label))
        sent += result.get("sent", 0)
    return sent


if __name__ == "__main__":
    try:
        import app as app_module
        cfg = load_config()
        pool = make_pool(cfg.database_path)
        label = f"{app_module.VERSION} ({app_module._commit()})"
        print(f"Release {label}: announced to {announce(pool, cfg, label)} device(s).")
        pool.close()
    except Exception as exc:                       # never block a start-up on a notification
        print(f"Release announcement skipped: {exc}", file=sys.stderr)
