#!/usr/bin/env bash
# Go back to the build before: scripts/rollback.sh [SHA]
#
# Starts the images of the build deployed before the running one (or SHA, any
# build in .deploy/<stack>.history, or any sha already built) and waits for
# /api/ready. No build, no backup restore, and no `migrate down`: the schema
# stays as the newer build left it, because migrations only add (RUNBOOK.md,
# section 5), and the older build ignores what it does not know. Run twice in a
# row, it goes back to the newer build again; name a sha to go further back.
set -euo pipefail
# shellcheck source=scripts/_stack.sh
. "$(dirname "$0")/_stack.sh"

now="$(current_tag || true)"
if [[ -n "${1:-}" ]]; then
  target="$(git rev-parse --short=12 "$1^{commit}" 2>/dev/null || echo "$1")"
else
  # The newest entry that is not the running build.
  target="$(awk -v now="$now" '$1 != now {t = $1} END {print t}' "$HISTORY" 2>/dev/null || true)"
fi
if [[ -z "$target" ]]; then
  echo "rollback: no earlier build in $HISTORY; name one: scripts/rollback.sh <sha>" >&2
  exit 1
fi
for part in backend web; do
  if ! docker image inspect "voltage-$part:$target" > /dev/null 2>&1; then
    echo "rollback: voltage-$part:$target is not on this machine; scripts/deploy.sh $target builds it" >&2
    exit 1
  fi
done

start=$SECONDS
echo "rollback: $STACK from ${now:-unknown} to $target (schema kept)"
export VOLTAGE_TAG="$target"
"${DC[@]}" up -d --no-build app worker web
wait_ready 180
if [[ -z "${RH_NAME:-}" ]]; then
  docker tag "voltage-backend:$target" voltage-backend:latest
  docker tag "voltage-web:$target" voltage-web:latest
fi
record "$target" "rollback-from-${now:-unknown}"
echo "rollback: $target live on $STACK in $((SECONDS - start)) s"
