#!/bin/sh
# One-time move of the uploaded print files to their current place.
#   migrate_uploads.sh <old folder> <new folder>
# Earlier releases kept them in DATA_PATH/app/uploads; they now live in DATA_PATH/uploads, next to DATA_PATH/postgres.
# Safe to run on every start: with no old folder it does nothing, a file is never overwritten (one that already exists in
# the new folder stays where it is, in the old one), and nothing is deleted except the empty old folders.
set -eu

old="${1:?old folder}"
new="${2:?new folder}"

[ -d "$old" ] || exit 0
[ "$old" != "$new" ] || exit 0
mkdir -p "$new"

moved=0
for file in "$old"/* "$old"/.[!.]*; do
  [ -e "$file" ] || continue                        # an unmatched pattern stays as written
  target="$new/$(basename "$file")"
  if [ -e "$target" ]; then
    echo "migrate_uploads: $target exists, leaving $file where it is" >&2
  else
    mv "$file" "$target"
    moved=$((moved + 1))
  fi
done

rmdir "$old" 2>/dev/null || true                    # only when it is empty
rmdir "$(dirname "$old")" 2>/dev/null || true
[ "$moved" -eq 0 ] || echo "migrate_uploads: moved $moved file(s) from $old to $new"
