#!/bin/sh
# Starts as root only to fix ownership of the uploads folder (Docker creates a missing bind-mount
# directory as root), then re-runs itself as the unprivileged `app` user. /data is the host's DATA_PATH:
# the database lives in its postgres/ folder (the db container mounts that), the uploads in uploads/.
# Migrations run before the server accepts traffic, and the container stops if they fail or the
# schema has drifted: serving on a half-migrated database is worse.
set -eu

UPLOAD_DIR="${UPLOAD_DIR:-/data/uploads}"

if [ "$(id -u)" = "0" ]; then
  # Data that is not on a mount is gone with the container at the next update: say so loudly instead of finding out then.
  if ! grep -qs " /data " /proc/mounts && ! grep -qs " $UPLOAD_DIR " /proc/mounts; then
    echo "WARNING: /data is not a mounted folder. Everything stored there (the uploaded print files) is lost when the container is replaced." >&2
    echo "         Mount the host's DATA_PATH on /data (see docker-compose.yml)." >&2
  fi
  mkdir -p "$UPLOAD_DIR"
  chown app:app "$UPLOAD_DIR"                                   # only the uploads: /data itself is the host's DATA_PATH, which also holds postgres/
  # Earlier releases kept the uploads in DATA_PATH/app/uploads. A failed move must not keep the app from starting: the files just stay there.
  /migrate_uploads.sh /data/app/uploads "$UPLOAD_DIR" || echo "WARNING: moving the old uploads from /data/app/uploads failed; they stay where they are." >&2
  exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

# A command after the image name (docker compose run app python generate_vapid.py) runs instead of the
# server, without touching the database.
if [ "$#" -gt 0 ]; then
  exec "$@"
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
