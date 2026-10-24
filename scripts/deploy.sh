#!/usr/bin/env bash
# Deploy one build: scripts/deploy.sh [REF]   (default: HEAD)
#
#   1. builds REF's commit as voltage-backend:<sha> and voltage-web:<sha>
#      (from `git archive`, so the checkout itself does not move; a sha
#      already built is not built again)
#   2. backs up (scripts/backup-offsite.sh; SKIP_BACKUP=1 skips it)
#   3. migrates with the new image, while the old build still serves
#      (scripts/migrate.sh; migrations only add, so the old build keeps working)
#   4. switches app, worker and web to the new images and waits for /api/ready
#   5. records the sha in .deploy/<stack>.history (scripts/rollback.sh reads it)
#
# RH_NAME=voltage-rb RH_PORT=8085 scripts/deploy.sh ...   the same against a rehearsal stack.
set -euo pipefail
# shellcheck source=scripts/_stack.sh
. "$(dirname "$0")/_stack.sh"

ref="${1:-HEAD}"
sha="$(git rev-parse --short=12 "$ref^{commit}")"
start=$SECONDS
echo "deploy: $ref = $sha on $STACK (running now: $(current_tag || echo nothing))"

for part in backend web; do
  image="voltage-$part:$sha"
  if docker image inspect "$image" > /dev/null 2>&1; then
    echo "build: $image already built"
    continue
  fi
  dockerfile="$([[ $part == backend ]] && echo backend/Dockerfile || echo frontend/Dockerfile)"
  echo "build: $image"
  git archive --format=tar "$sha" \
    | docker build --quiet --label "org.opencontainers.image.revision=$sha" -f "$dockerfile" -t "$image" - > /dev/null
done
echo "build: done at $((SECONDS - start)) s"

backup_first
VOLTAGE_TAG="$sha" SKIP_BACKUP=1 "$ROOT/scripts/migrate.sh"

export VOLTAGE_TAG="$sha"
"${DC[@]}" up -d --no-build app worker web
if ! wait_ready 180; then
  echo "deploy: $sha is not ready. Read the log above; scripts/rollback.sh goes back to the build before it." >&2
  record "$sha" "deploy-not-ready"
  exit 1
fi
# A plain `docker compose up -d` (no VOLTAGE_TAG) then keeps this build too.
if [[ -z "${RH_NAME:-}" ]]; then
  docker tag "voltage-backend:$sha" voltage-backend:latest
  docker tag "voltage-web:$sha" voltage-web:latest
fi
record "$sha" deploy
echo "deploy: $sha live on $STACK in $((SECONDS - start)) s"
