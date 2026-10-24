#!/usr/bin/env bash
# Apply pending migrations: scripts/migrate.sh   (then prints every step's status)
#
# Runs `python -m app.store.migrate up` in a one-off container of the backend
# image VOLTAGE_TAG (default: the build running now), against the stack's
# database (DATABASE_URL, else /data/ave.db). Backs up first (SKIP_BACKUP=1
# skips it). Safe to run any time: with nothing pending it changes nothing.
# The API also applies pending steps when it starts.
#
# Migrations only add (tables, columns with defaults, indexes): the build
# before keeps working on the new schema, so a rollback never runs `down`.
# See RUNBOOK.md, section 5.
set -euo pipefail
# shellcheck source=scripts/_stack.sh
. "$(dirname "$0")/_stack.sh"

tag="${VOLTAGE_TAG:-$(current_tag || echo latest)}"
start=$SECONDS
backup_first
echo "migrate: with voltage-backend:$tag on $STACK"
"${DC[@]}" up -d --wait postgres > /dev/null 2>&1    # the first deploy: nothing runs yet
# shellcheck disable=SC2016
VOLTAGE_TAG="$tag" "${DC[@]}" run --rm --no-deps -T app \
  sh -c 'python -m app.store.migrate up --db "${DATABASE_URL:-/data/ave.db}"'
echo "migrate: done in $((SECONDS - start)) s"
