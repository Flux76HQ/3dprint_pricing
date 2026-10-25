#!/bin/sh
# Update the installation without risking the data: dump the database first, then pull and restart.
#   sh scripts/update.sh        (from the folder with docker-compose.yml and .env)
# The dump goes to DATA_PATH/backups/ as a gzipped SQL file; a failing or empty dump stops the update. The data itself is never touched by an update: the database lives in
# DATA_PATH/postgres and the uploads in DATA_PATH/uploads, both folders on the host. Copy the backups off the server now and then:
# they are in the same folder as the data they protect.
set -eu

[ -f .env ] || { echo ".env not found: run this from the folder with docker-compose.yml" >&2; exit 1; }
set -a
. ./.env
set +a

backups="${DATA_PATH:?DATA_PATH is not set in .env}/backups"
mkdir -p "$backups"
dump="$backups/pre-update-$(date +%Y-%m-%d-%H%M%S).sql"

if docker compose ps --status running --services 2>/dev/null | grep -qx db; then
  # Not piped into gzip: a pipe hides a failing pg_dump, and a broken dump must stop the update.
  docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "$dump" || { rm -f "$dump"; echo "The dump failed: not updating." >&2; exit 1; }
  [ -s "$dump" ] || { rm -f "$dump"; echo "The dump is empty: not updating." >&2; exit 1; }
  gzip "$dump"
  echo "Database saved to $dump.gz"
else
  echo "The database is not running, so there is nothing to dump: updating anyway." >&2
fi

# Data that sits in another folder than DATA_PATH (a relative DATA_PATH once resolved elsewhere) is copied there first; no-op otherwise.
sh "$(dirname "$0")/migrate_data.sh"

docker compose pull
docker compose up -d
