#!/usr/bin/env bash
# Back up Voltage's data: the database and the media store, as one dated folder.
#
#   scripts/backup.sh [DATA_DIR] [BACKUP_DIR]
#
# DATA_DIR    where ave.db and artifacts/ live (default: $AVE_DATA_DIR, else backend/var)
# BACKUP_DIR  where backups go (default: $AVE_BACKUP_DIR, else DATA_DIR/../backups)
# KEEP_DAYS   delete backups older than this many days (default 14)
#
# SQLite is copied with `.backup`, which is safe while the server runs (it
# reads a consistent snapshot, WAL included). With DATABASE_URL set to a
# postgres:// URL, pg_dump is used instead. Media is copied as a tar.gz.
# Each backup folder gets a SHA256SUMS file; restore.sh checks it.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
data="${1:-${AVE_DATA_DIR:-$here/backend/var}}"
dest_root="${2:-${AVE_BACKUP_DIR:-$(dirname "$data")/backups}}"
keep="${KEEP_DAYS:-14}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="$dest_root/voltage-$stamp"

mkdir -p "$dest"
chmod 700 "$dest_root" "$dest" 2>/dev/null || true

if [[ "${DATABASE_URL:-}" == postgres* ]]; then
  pg_dump --format=custom --no-owner --file "$dest/ave.pgdump" "$DATABASE_URL"
else
  if [[ ! -f "$data/ave.db" ]]; then
    echo "No database at $data/ave.db" >&2
    exit 1
  fi
  sqlite3 "$data/ave.db" ".backup '$dest/ave.db'"
  ok="$(sqlite3 "$dest/ave.db" 'PRAGMA integrity_check;')"
  if [[ "$ok" != "ok" ]]; then
    echo "The copied database failed its integrity check: $ok" >&2
    exit 1
  fi
fi

# The media store and the signing key file (if one was generated).
tar -C "$data" -czf "$dest/data.tar.gz" --exclude='./ave.db*' --exclude='./backups' .

( cd "$dest" && shasum -a 256 ./* > SHA256SUMS )
echo "$dest"

# Old backups go after a fortnight (KEEP_DAYS).
find "$dest_root" -maxdepth 1 -type d -name 'voltage-*' -mtime +"$keep" -exec rm -rf {} + 2>/dev/null || true
