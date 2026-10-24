#!/usr/bin/env bash
# The nightly backup, copied off the machine (provision.sh puts it in cron).
#
#   scripts/backup-offsite.sh
#
# Makes one folder voltage-<UTC time> under VOLTAGE_BACKUP_DIR holding the
# database (ave.pgdump from the postgres container when the app uses
# Postgres, else ave.db by SQLite's .backup), the media (data.tar.gz) and
# SHA256SUMS, the same layout scripts/restore.sh reads. Then `rclone copy` to
# VOLTAGE_BACKUP_REMOTE/<folder>. deploy.sh and migrate.sh run it first too
# (a local copy only, when they cannot read backup.env).
#
# Settings come from the environment, or from /etc/voltage/backup.env
# (VOLTAGE_BACKUP_ENV) which provision.sh writes:
#   VOLTAGE_BACKUP_REMOTE  rclone destination, remote:bucket/path (blank: a local copy only)
#   RCLONE_CONFIG_*        the remote's settings (rclone reads them itself)
#   VOLTAGE_DIR            the checkout with docker-compose.yml (default: this repo)
#   VOLTAGE_BACKUP_DIR     local copies (default /var/backups/voltage as root, else <checkout>/backups)
#   KEEP_DAYS              local copies older than this go (default 7)
#   REMOTE_KEEP_DAYS       remote copies older than this go (default: kept forever)
#   COMPOSE                the compose command (default "docker compose")
#   RCLONE                 the rclone command (default "rclone")
set -euo pipefail

env_file="${VOLTAGE_BACKUP_ENV:-/etc/voltage/backup.env}"
if [[ -r "$env_file" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$env_file"
  set +a
fi

here="$(cd "$(dirname "$0")/.." && pwd)"
dir="${VOLTAGE_DIR:-$here}"
remote="${VOLTAGE_BACKUP_REMOTE:-}"
if [[ "$(id -u)" -eq 0 ]]; then root="${VOLTAGE_BACKUP_DIR:-/var/backups/voltage}"; else root="${VOLTAGE_BACKUP_DIR:-$dir/backups}"; fi
keep="${KEEP_DAYS:-7}"
read -r -a dc <<< "${COMPOSE:-docker compose}"
read -r -a rclone <<< "${RCLONE:-rclone}"
if command -v sha256sum >/dev/null 2>&1; then sha=(sha256sum); else sha=(shasum -a 256); fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="$root/voltage-$stamp"
mkdir -p "$dest"
chmod 700 "$root" "$dest"
cd "$dir"
echo "backup: $dest"

if [[ "$("${dc[@]}" exec -T app printenv DATABASE_URL 2>/dev/null || true)" == postgres* ]]; then
  # The app image has no pg_dump; the postgres container does (its own variables, expanded there).
  # shellcheck disable=SC2016
  "${dc[@]}" exec -T postgres sh -c 'pg_dump --format=custom --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$dest/ave.pgdump"
  [[ -s "$dest/ave.pgdump" ]] || { echo "backup: the Postgres dump is empty" >&2; exit 1; }
else
  "${dc[@]}" exec -T app sh -c 'sqlite3 /data/ave.db ".backup /tmp/ave-backup.db" && cat /tmp/ave-backup.db && rm -f /tmp/ave-backup.db' > "$dest/ave.db"
  [[ "$(sqlite3 "$dest/ave.db" 'PRAGMA integrity_check;')" == "ok" ]] || { echo "backup: the copied database failed its integrity check" >&2; exit 1; }
fi

# The media store and the generated signing key, as backup.sh packs them.
"${dc[@]}" exec -T app tar -C /data -czf - --exclude='./ave.db*' --exclude='./backups' . > "$dest/data.tar.gz"
( cd "$dest" && "${sha[@]}" ./* > SHA256SUMS )

find "$root" -maxdepth 1 -type d -name 'voltage-*' -mtime +"$keep" -exec rm -rf {} +
if [[ -z "$remote" ]]; then
  echo "backup: local copy only (no VOLTAGE_BACKUP_REMOTE)"
  exit 0
fi

"${rclone[@]}" copy "$dest" "$remote/voltage-$stamp"
echo "backup: copied to $remote/voltage-$stamp"
if [[ -n "${REMOTE_KEEP_DAYS:-}" ]]; then
  "${rclone[@]}" delete --min-age "${REMOTE_KEEP_DAYS}d" "$remote"
  "${rclone[@]}" rmdirs --leave-root "$remote"
fi
