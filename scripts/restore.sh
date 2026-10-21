#!/usr/bin/env bash
# Restore a backup made by backup.sh into a data dir.
#
#   scripts/restore.sh BACKUP_FOLDER DATA_DIR [--force]
#
# Stop the server first. Without --force it refuses to write over a data dir
# that already has a database. It checks the backup's SHA256SUMS, restores
# the database (SQLite file, or pg_restore into DATABASE_URL) and the media,
# then runs an integrity check. Run `python -m app.store.migrate status` after.
set -euo pipefail

src="${1:?usage: restore.sh BACKUP_FOLDER DATA_DIR [--force]}"
data="${2:?usage: restore.sh BACKUP_FOLDER DATA_DIR [--force]}"
force="${3:-}"

( cd "$src" && shasum -a 256 -c SHA256SUMS >/dev/null ) || { echo "The backup does not match its checksums." >&2; exit 1; }

mkdir -p "$data"
if [[ -f "$data/ave.db" && "$force" != "--force" ]]; then
  echo "$data already has a database. Stop the server, move it aside, or pass --force." >&2
  exit 1
fi

if [[ -f "$src/ave.pgdump" ]]; then
  pg_restore --clean --if-exists --no-owner --dbname "${DATABASE_URL:?DATABASE_URL must name the database to restore into}" "$src/ave.pgdump"
else
  rm -f "$data/ave.db" "$data/ave.db-wal" "$data/ave.db-shm"
  cp "$src/ave.db" "$data/ave.db"
  ok="$(sqlite3 "$data/ave.db" 'PRAGMA integrity_check;')"
  [[ "$ok" == "ok" ]] || { echo "The restored database failed its integrity check: $ok" >&2; exit 1; }
fi
tar -C "$data" -xzf "$src/data.tar.gz"
echo "Restored $src into $data"
