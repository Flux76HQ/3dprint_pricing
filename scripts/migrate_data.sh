#!/bin/sh
# Move the data of an installation that ended up in the wrong host folder to DATA_PATH.
#   sh scripts/migrate_data.sh [--check]       (from the folder with docker-compose.yml and .env, as the user that owns the data)
# A relative DATA_PATH (./data) is resolved by whatever tool starts the stack; under Dockhand on Unraid that was a folder in
# the host's RAM disk, gone at the next reboot. This reads where the db container really keeps the database, and when that is
# not DATA_PATH/postgres, stops the stack and copies the whole data folder (postgres/, uploads/, backups/) to DATA_PATH.
# Safe to run on every update (scripts/update.sh does): with no db container, or the data already in place, it does nothing.
# It never deletes the old folder (it says where it is), and it refuses when DATA_PATH/postgres already holds a database.
# --check says what it would do and changes nothing. Afterwards `docker compose up -d` recreates the containers on the new folder.
set -eu

check=0
[ "${1:-}" != "--check" ] || check=1

[ -f .env ] || { echo ".env not found: run this from the folder with docker-compose.yml" >&2; exit 1; }
set -a
. ./.env
set +a

data="${DATA_PATH:?DATA_PATH is not set in .env}"
case "$data" in
  /*) ;;
  *) echo "DATA_PATH is \"$data\", a relative path: set an absolute folder of the host in .env (e.g. /srv/printpricing) first." >&2; exit 1 ;;
esac
data="${data%/}"

db="$(docker compose ps -aq db 2>/dev/null | head -n 1 || true)"
if [ -z "$db" ]; then
  echo "migrate_data: no db container yet, so there is nothing to move."
  exit 0
fi

current="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Source}}{{end}}{{end}}' "$db")"
if [ -z "$current" ]; then
  echo "migrate_data: the db container has no mount on /var/lib/postgresql/data; not touching it." >&2
  exit 1
fi

resolve() { readlink -f "$1" 2>/dev/null || printf '%s' "$1"; }
if [ "$(resolve "$current")" = "$(resolve "$data/postgres")" ]; then
  echo "migrate_data: the database is already in $data/postgres."
  exit 0
fi

case "$current" in
  */postgres) old="${current%/postgres}" ;;
  *) echo "migrate_data: the database is in $current, which is not a postgres/ folder inside a data folder; move it by hand (see docs/handleiding.md)." >&2; exit 1 ;;
esac

[ -d "$current" ] || { echo "migrate_data: $current does not exist on this machine; run this on the Docker host." >&2; exit 1; }
if [ -e "$data/postgres/PG_VERSION" ]; then
  echo "migrate_data: $data/postgres already holds a database, and so does $current. Not choosing between them: keep one, and move the other away." >&2
  exit 1
fi
[ -r "$current" ] && [ -x "$current" ] || { echo "migrate_data: cannot read $current (the database folder belongs to another user): run this as root." >&2; exit 1; }

echo "migrate_data: the data is in $old, DATA_PATH is $data."
if [ "$check" -eq 1 ]; then
  echo "migrate_data: --check: would stop the stack and copy $old to $data."
  exit 0
fi

docker compose stop
mkdir -p "$data"
cp -a "$old/." "$data/"

# The copy has to be the same before anything is started on it. backups/ may differ: update.sh writes its dump to the new folder first.
for part in postgres uploads; do
  [ ! -d "$old/$part" ] || diff -rq "$old/$part" "$data/$part" >/dev/null || { echo "migrate_data: $data/$part differs from $old/$part after the copy; nothing was removed, start again." >&2; exit 1; }
done

echo "migrate_data: copied $old to $data."
echo "migrate_data: the old folder is untouched; remove it yourself once the app works on the new one: rm -rf '$old'"
echo "migrate_data: now run: docker compose up -d   (it recreates the containers on $data)"
