#!/usr/bin/env bash
# Make N verified accounts on a rehearsal stack (rehearsal item 3), for k6.
#   RH_NAME=voltage-load RH_PORT=8090 tools/load/seed.sh 60 > tools/load/users.json
# Each signs up through the API and opens its verify link from the dev outbox.
set -euo pipefail
N="${1:-50}"; PORT="${RH_PORT:-8090}"; B="http://localhost:$PORT/api"; RUN="${RUN:-$(date +%s)}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
echo "["
for i in $(seq 1 "$N"); do
  email="load${RUN}u${i}@load.test"
  curl -fsS -X POST "$B/auth/signup" -H 'Content-Type: application/json' -H 'X-Requested-With: voltage' \
    -d "{\"email\":\"$email\",\"password\":\"rehearsal-pass-1\",\"accept_terms\":true}" > /dev/null
  token=$("$ROOT/scripts/rehearsal.sh" sql "select body from notify_outbox where to_addr='$email' and kind='verify_email' order by id desc limit 1" \
          | grep -o 'verify?token=[A-Za-z0-9_-]*' | head -1 | cut -d= -f2)
  curl -fsS -o /dev/null "$B/auth/verify?token=$token"
  sep=","; [ "$i" = "$N" ] && sep=""
  echo "  {\"email\": \"$email\", \"password\": \"rehearsal-pass-1\"}$sep"
done
echo "]"
