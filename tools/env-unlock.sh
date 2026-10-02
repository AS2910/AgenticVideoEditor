#!/bin/sh
# Decrypts backend/.env.enc into backend/.env on a fresh clone, e.g. a cloud
# server. Needs the passphrase that locked it, from AVE_ENV_PASSPHRASE or a
# prompt. The result is readable by you alone (mode 600) and git-ignored.
#
#   AVE_ENV_PASSPHRASE=... tools/env-unlock.sh
set -eu
cd "$(dirname "$0")/.."
[ -f backend/.env.enc ] || { echo "backend/.env.enc not found — nothing to unlock." >&2; exit 1; }
if [ -f backend/.env ] && [ "${AVE_ENV_FORCE:-}" != "1" ]; then
  echo "backend/.env already exists; set AVE_ENV_FORCE=1 to overwrite it." >&2; exit 1
fi
umask 077
if [ -n "${AVE_ENV_PASSPHRASE:-}" ]; then
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass env:AVE_ENV_PASSPHRASE \
    -in backend/.env.enc -out backend/.env
else
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in backend/.env.enc -out backend/.env
fi
chmod 600 backend/.env
echo "Unlocked backend/.env. Start the backend as the README says."
