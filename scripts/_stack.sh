# Shared by deploy.sh, migrate.sh and rollback.sh (sourced, not run).
#
# Which stack: the production one (`docker compose` in this checkout, reading
# .env), or, with RH_NAME set, a rehearsal stack on this machine
# (scripts/rehearsal.sh; RH_PORT picks its port).
#
# Which build: images are tagged by git sha (voltage-backend:<sha>,
# voltage-web:<sha>), and .deploy/<stack>.history lists each one deployed, the
# running one last. Compose picks the tag from VOLTAGE_TAG.
# shellcheck shell=bash

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
[[ -f .env ]] || touch .env      # the compose file reads .env (empty is fine for a rehearsal)

if [[ -n "${RH_NAME:-}" ]]; then
  export RH_PORT="${RH_PORT:-8080}"
  STACK="$RH_NAME"
  DC=(docker compose -p "$RH_NAME" --env-file deploy/rehearsal/rehearsal.env -f docker-compose.yml -f deploy/rehearsal/compose.yml)
  READY_URL="http://localhost:$RH_PORT/api/ready"
else
  STACK="voltage"
  DC=(docker compose)
  # `web` listens on the VM's loopback (docker-compose.yml); Caddy is in front of it.
  READY_URL="${VOLTAGE_READY_URL:-http://127.0.0.1:8080/api/ready}"
fi
HISTORY="$ROOT/.deploy/$STACK.history"

# The tag running now: the last line of the history ("<sha> <UTC time> <how>").
current_tag() { [[ -s "$HISTORY" ]] && tail -n 1 "$HISTORY" | cut -d' ' -f1; }

record() {
  mkdir -p "$(dirname "$HISTORY")"
  echo "$1 $(date -u +%Y-%m-%dT%H:%M:%SZ) $2" >> "$HISTORY"
}

# Wait for /api/ready (the database, every migration, the data dir, ffmpeg).
wait_ready() {
  local within="${1:-180}" start=$SECONDS
  while (( SECONDS - start < within )); do
    if curl -fsS "$READY_URL" > /dev/null 2>&1; then
      echo "ready in $((SECONDS - start)) s: $READY_URL"
      return 0
    fi
    sleep 2
  done
  echo "not ready after $within s: $READY_URL" >&2
  "${DC[@]}" ps >&2
  "${DC[@]}" logs --tail 40 app >&2
  return 1
}

# Is the app container up (so there is something to back up or migrate)?
app_running() { [[ -n "$("${DC[@]}" ps -q --status running app 2>/dev/null)" ]]; }

# A backup before anything that can change the data (local only unless
# VOLTAGE_BACKUP_REMOTE is set). SKIP_BACKUP=1 skips it.
backup_first() {
  if [[ "${SKIP_BACKUP:-0}" == "1" ]]; then echo "backup: skipped (SKIP_BACKUP=1)"; return; fi
  if ! app_running; then echo "backup: nothing running yet, nothing to back up"; return; fi
  VOLTAGE_DIR="$ROOT" COMPOSE="${DC[*]}" "$ROOT/scripts/backup-offsite.sh"
}
