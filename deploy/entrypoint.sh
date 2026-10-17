#!/bin/sh
# Starts as root only to fix ownership of the mounted /data (Docker creates a missing bind-mount
# directory as root), then re-runs itself as the unprivileged `app` user.
# Migrations run before the server accepts traffic, and the container stops if they fail or the
# schema has drifted: serving on a half-migrated database is worse.
set -eu

UPLOAD_DIR="${UPLOAD_DIR:-/data/uploads}"

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$UPLOAD_DIR"
  chown app:app /data "$UPLOAD_DIR"
  exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

python migrate.py

# Tell opted-in devices about a new release. Best effort: a failed push never blocks the start.
python announce_release.py || true

# Reading a large 3MF can take a while, hence the longer timeout.
exec gunicorn \
  --bind "0.0.0.0:${WEB_PORT}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  wsgi:app
