#!/bin/sh
# Update the installation without risking the data: copy the database first, then pull and restart.
#   sh scripts/update.sh        (from the folder with docker-compose.yml and .env)
# The copy goes to DATA_PATH/backups/ (pre-update-*.sqlite3.gz; for an installation that still runs on PostgreSQL, a gzipped SQL dump); a failing or empty
# copy stops the update. The data itself is never touched by an update: the database is DATA_PATH/db/printpricing.sqlite3 and the uploads are in
# DATA_PATH/uploads, both on the host. Copy the backups off the server now and then: they are in the same folder as the data they protect.
set -eu

[ -f .env ] || { echo ".env not found: run this from the folder with docker-compose.yml" >&2; exit 1; }
set -a
. ./.env
set +a

data="${DATA_PATH:?DATA_PATH is not set in .env}"
backups="$data/backups"
mkdir -p "$backups"
stamp="$(date +%Y-%m-%d-%H%M%S)"

if [ -f "$data/db/printpricing.sqlite3" ]; then
  copy="$backups/pre-update-$stamp.sqlite3"
  if docker compose ps --status running --services 2>/dev/null | grep -qx app; then
    # SQLite's own online backup, run by the app: one consistent moment, also while the app is writing.
    docker compose exec -T app python backup_db.py "/data/backups/pre-update-$stamp.sqlite3" || { rm -f "$copy"; echo "The copy failed: not updating." >&2; exit 1; }
  else
    # The app is stopped, so nothing is writing; the -wal file holds the newest data, so it goes along.
    cp "$data/db/printpricing.sqlite3" "$copy"
    [ ! -f "$data/db/printpricing.sqlite3-wal" ] || cp "$data/db/printpricing.sqlite3-wal" "$copy-wal"
  fi
  [ -s "$copy" ] || { rm -f "$copy" "$copy-wal"; echo "The copy is empty: not updating." >&2; exit 1; }
  gzip "$copy"
  [ ! -f "$copy-wal" ] || gzip "$copy-wal"
  echo "Database saved to $copy.gz"
elif docker compose ps --status running --services 2>/dev/null | grep -qx db; then
  # Still on PostgreSQL (the release before SQLite): the update that follows moves the data over; this dump is the way back.
  dump="$backups/pre-update-$stamp.sql"
  # Not piped into gzip: a pipe hides a failing pg_dump, and a broken dump must stop the update.
  docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "$dump" || { rm -f "$dump"; echo "The dump failed: not updating." >&2; exit 1; }
  [ -s "$dump" ] || { rm -f "$dump"; echo "The dump is empty: not updating." >&2; exit 1; }
  gzip "$dump"
  echo "Database saved to $dump.gz"
else
  echo "The database is not running, so there is nothing to copy: updating anyway." >&2
fi

# Data that sits in another folder than DATA_PATH (a relative DATA_PATH once resolved elsewhere) is copied there first; no-op otherwise.
sh "$(dirname "$0")/migrate_data.sh"

docker compose pull
docker compose up -d
