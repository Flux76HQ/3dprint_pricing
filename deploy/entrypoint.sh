#!/bin/sh
# Migrations run before the server accepts traffic, and the container stops if
# they fail or the schema has drifted: serving on a half-migrated database is worse.
set -eu

python migrate.py

exec gunicorn \
  --bind "0.0.0.0:${WEB_PORT}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 30 \
  --access-logfile - \
  wsgi:app
