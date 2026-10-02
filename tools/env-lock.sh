#!/bin/sh
# Encrypts backend/.env into backend/.env.enc so the keys can travel with the
# repo. Only the ciphertext is committed; the passphrase is the one thing you
# keep outside git. AES-256 with a key derived from the passphrase (PBKDF2,
# 600k rounds). Run it again whenever a key changes.
#
#   tools/env-lock.sh                      # prompts for a passphrase
#   AVE_ENV_PASSPHRASE=... tools/env-lock.sh
set -eu
cd "$(dirname "$0")/.."
[ -f backend/.env ] || { echo "backend/.env not found — nothing to lock." >&2; exit 1; }
if [ -n "${AVE_ENV_PASSPHRASE:-}" ]; then
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass env:AVE_ENV_PASSPHRASE \
    -in backend/.env -out backend/.env.enc
else
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -in backend/.env -out backend/.env.enc
fi
echo "Wrote backend/.env.enc ($(wc -c < backend/.env.enc | tr -d ' ') bytes). Commit it; keep the passphrase outside git."
