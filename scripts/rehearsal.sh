#!/usr/bin/env bash
# The launch rehearsal stack (rehearsal item 2): the shipped docker-compose
# stack with mocked vendors, the public profile and Postgres, on this machine.
#   scripts/rehearsal.sh up        build and start app, worker, web, postgres; wait until ready
#   scripts/rehearsal.sh down      stop it (data kept)
#   scripts/rehearsal.sh reset     stop it and delete its data (volumes)
#   scripts/rehearsal.sh sql "..." run SQL on its Postgres (the dev outbox: notify_outbox)
#   scripts/rehearsal.sh logs      follow the app's log
#   RH_NAME=voltage-load RH_PORT=8090 scripts/rehearsal.sh up    a second, separate stack
# Extra environment for the app (drills): AVE_CHAOS=... AVE_CHAOS_FORCE=1 scripts/rehearsal.sh up
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] || touch .env          # the base compose file reads .env (empty is fine here)
# RH_NAME / RH_PORT: a second stack beside the first (default voltage-rehearsal on 8080).
export RH_PORT="${RH_PORT:-8080}"
DC=(docker compose -p "${RH_NAME:-voltage-rehearsal}" --env-file deploy/rehearsal/rehearsal.env -f docker-compose.yml -f deploy/rehearsal/compose.yml)

case "${1:-up}" in
  up)
    "${DC[@]}" up -d --build "${@:2}"
    for _ in $(seq 1 90); do
      if curl -fsS "http://localhost:$RH_PORT/api/ready" > /dev/null 2>&1; then echo "rehearsal: ready on http://localhost:$RH_PORT"; exit 0; fi
      sleep 2
    done
    echo "rehearsal: not ready after 3 minutes" >&2; "${DC[@]}" ps; "${DC[@]}" logs --tail 50 app >&2; exit 1 ;;
  down) "${DC[@]}" down ;;
  reset) "${DC[@]}" down -v ;;
  sql) "${DC[@]}" exec -T postgres psql -U voltage -d voltage -At -c "$2" ;;
  logs) "${DC[@]}" logs -f app ;;
  dc) "${DC[@]}" "${@:2}" ;;
  *) echo "usage: $0 up|down|reset|sql|logs|dc" >&2; exit 2 ;;
esac
