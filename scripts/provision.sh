#!/usr/bin/env bash
# Set up a fresh Ubuntu 24.04 LTS VM for Voltage (DEPLOY.md, section 1). Run as root:
#
#   sudo DEPLOY_USER=deploy VOLTAGE_BACKUP_REMOTE=offsite:my-bucket/voltage \
#        RCLONE_CONFIG_OFFSITE_TYPE=s3 RCLONE_CONFIG_OFFSITE_PROVIDER=... \
#        scripts/provision.sh
#
# What it does, each step only when it is not done already:
#   1. packages: Docker Engine and the Compose plugin (Docker's apt repo), ufw,
#      fail2ban, unattended-upgrades, logrotate, cron, rclone
#   2. Docker's own log limits (json-file, 20 MB x 5, /etc/docker/daemon.json)
#   3. DEPLOY_USER (default: the sudo user) in the docker group
#   4. the firewall: deny incoming, allow 22, 80, 443 (tcp; 443/udp too for HTTP/3)
#   5. unattended security upgrades
#   6. fail2ban on sshd
#   7. swap (half the RAM, 2 to 8 GB) unless the machine already has some
#   8. logrotate for the app's logs on the host (/var/log/voltage-*.log)
#   9. the nightly off-site backup: scripts/backup-offsite.sh from cron, with
#      rclone set up only from environment variables (VOLTAGE_BACKUP_REMOTE and
#      RCLONE_CONFIG_<REMOTE>_*), kept in /etc/voltage/backup.env (mode 600)
#
# Idempotent: a second run changes nothing and ends "provision: no changes".
#
# Environment:
#   DEPLOY_USER            the user that runs `docker compose` (default: $SUDO_USER)
#   VOLTAGE_DIR            where the repo is checked out (default /opt/voltage)
#   VOLTAGE_BACKUP_REMOTE  rclone destination, remote:bucket/path (blank: no off-site backup cron)
#   RCLONE_CONFIG_*        the remote's settings (rclone reads these itself; see rclone.org/docs/#config-file)
#   BACKUP_HOUR            hour (UTC) of the nightly backup (default 3)
#   PROVISION_TEST=1       test mode, for a container: skips what needs systemd, a
#                          kernel or a real network stack (services, ufw, swapon, sysctl)
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-}}"
VOLTAGE_DIR="${VOLTAGE_DIR:-/opt/voltage}"
BACKUP_HOUR="${BACKUP_HOUR:-3}"
TEST="${PROVISION_TEST:-0}"
CHANGED=0
UPDATED_APT=0

say() { printf '%-8s %s\n' "$1" "$2"; }
changed() { CHANGED=$((CHANGED + 1)); say changed "$1"; }
ok() { say ok "$1"; }
skip() { say skip "$1"; }
test_mode() { [[ "$TEST" == "1" ]]; }

if [[ "$(id -u)" -ne 0 ]]; then
  echo "provision: run as root (sudo $0)" >&2
  exit 1
fi
# shellcheck source=/dev/null
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "provision: this is for Ubuntu (24.04 LTS); found ${PRETTY_NAME:-unknown}" >&2
  exit 1
fi

# put_file PATH MODE: write stdin to PATH only if it differs. Returns 0 when it wrote.
put_file() {
  local path="$1" mode="$2" tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  if [[ -f "$path" ]] && cmp -s "$tmp" "$path"; then
    rm -f "$tmp"
    [[ "$(stat -c %a "$path")" == "$mode" ]] || { chmod "$mode" "$path"; return 0; }
    return 1
  fi
  mkdir -p "$(dirname "$path")"
  install -m "$mode" "$tmp" "$path"
  rm -f "$tmp"
  return 0
}

service_reload() {
  if test_mode; then skip "restart $1 (test mode: no systemd)"; return; fi
  systemctl enable --now "$1" >/dev/null
  systemctl restart "$1"
}

apt_install() {
  local missing=()
  for pkg in "$@"; do
    dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "packages: $*"
    return
  fi
  if [[ "$UPDATED_APT" == "0" ]]; then apt-get update -qq; UPDATED_APT=1; fi
  apt-get install -y -qq --no-install-recommends "${missing[@]}" >/dev/null
  changed "installed: ${missing[*]}"
}

# 1. Packages.
apt_install ca-certificates curl gnupg ufw fail2ban unattended-upgrades logrotate cron rclone sqlite3

if [[ ! -s /etc/apt/keyrings/docker.asc ]]; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  changed "Docker's apt key"
else
  ok "Docker's apt key"
fi
if put_file /etc/apt/sources.list.d/docker.list 644 <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable
EOF
then
  changed "Docker's apt repo"
  UPDATED_APT=0
else
  ok "Docker's apt repo"
fi
apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 2. Docker's log limits for every container (docker-compose.yml sets the same per service).
if put_file /etc/docker/daemon.json 644 <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "5" }
}
EOF
then
  changed "Docker log limits (/etc/docker/daemon.json)"
  service_reload docker
else
  ok "Docker log limits"
fi

# 3. The deploy user runs docker without sudo.
if [[ -z "$DEPLOY_USER" || "$DEPLOY_USER" == "root" ]]; then
  skip "docker group (no DEPLOY_USER)"
elif ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  echo "provision: DEPLOY_USER $DEPLOY_USER does not exist" >&2
  exit 1
elif id -nG "$DEPLOY_USER" | tr ' ' '\n' | grep -qx docker; then
  ok "$DEPLOY_USER in the docker group"
else
  usermod -aG docker "$DEPLOY_USER"
  changed "$DEPLOY_USER in the docker group (log in again to use it)"
fi

# 4. Firewall: SSH and the web ports only. Docker bypasses ufw for published
#    ports, which is why only Caddy publishes on all interfaces (DEPLOY.md).
if test_mode; then
  skip "ufw (test mode: no netfilter)"
else
  want="22/tcp 80/tcp 443/tcp 443/udp"
  have="$(ufw status | awk '/ALLOW/ && $2 != "(v6)" {print $1}' | sort -u | tr '\n' ' ' | sed 's/ $//')"
  sorted_want="$(tr ' ' '\n' <<< "$want" | sort -u | tr '\n' ' ' | sed 's/ $//')"
  if ufw status | grep -q "Status: active" && [[ "$have" == "$sorted_want" ]] \
     && ufw status verbose | grep -q "deny (incoming)"; then
    ok "ufw: $want"
  else
    ufw --force reset >/dev/null
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    for rule in $want; do ufw allow "$rule" >/dev/null; done
    ufw --force enable >/dev/null
    changed "ufw: deny incoming, allow $want"
  fi
fi

# 5. Unattended upgrades (security updates only: the package's default origins).
if put_file /etc/apt/apt.conf.d/20auto-upgrades 644 <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
then
  changed "unattended security upgrades"
  service_reload unattended-upgrades
else
  ok "unattended security upgrades"
fi

# 6. fail2ban on sshd.
if put_file /etc/fail2ban/jail.d/voltage-sshd.local 644 <<'EOF'
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
then
  changed "fail2ban: sshd jail"
  service_reload fail2ban
else
  ok "fail2ban: sshd jail"
fi

# 7. Swap: half the RAM, at least 2 GB, at most 8 GB; never a second one.
ram_mb=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 ))
swap_mb=$(( ram_mb / 2 ))
(( swap_mb < 2048 )) && swap_mb=2048
(( swap_mb > 8192 )) && swap_mb=8192
if [[ -n "$(swapon --show --noheadings 2>/dev/null)" ]] || grep -q '^/swapfile ' /etc/fstab 2>/dev/null; then
  ok "swap (already present)"
elif test_mode; then
  skip "swap: would make /swapfile of ${swap_mb} MB (test mode: no swapon)"
else
  fallocate -l "${swap_mb}M" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  changed "swap: /swapfile ${swap_mb} MB"
fi
if put_file /etc/sysctl.d/99-voltage-swap.conf 644 <<'EOF'
vm.swappiness = 10
EOF
then
  changed "vm.swappiness = 10"
  if test_mode; then skip "sysctl (test mode)"; else sysctl -q --system; fi
else
  ok "vm.swappiness = 10"
fi

# 8. Logs on the host: the backup's log (containers log through Docker, step 2).
if put_file /etc/logrotate.d/voltage 644 <<'EOF'
/var/log/voltage-*.log {
    weekly
    rotate 8
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
then
  changed "logrotate: /var/log/voltage-*.log"
else
  ok "logrotate: /var/log/voltage-*.log"
fi

# 9. The nightly off-site backup. Only what the operator passed in goes into
#    backup.env: the destination and the remote's RCLONE_CONFIG_* settings.
if [[ -z "${VOLTAGE_BACKUP_REMOTE:-}" ]]; then
  skip "off-site backup (set VOLTAGE_BACKUP_REMOTE and RCLONE_CONFIG_<REMOTE>_*; docs/ops/monitoring.md)"
else
  remote_name="${VOLTAGE_BACKUP_REMOTE%%:*}"
  remote_env="RCLONE_CONFIG_$(tr '[:lower:]-' '[:upper:]_' <<< "$remote_name")_"
  if ! env | grep -q "^${remote_env}TYPE="; then
    echo "provision: VOLTAGE_BACKUP_REMOTE names the remote '$remote_name' but ${remote_env}TYPE is not set" >&2
    exit 1
  fi
  if {
    echo "# Written by scripts/provision.sh. Read by scripts/backup-offsite.sh."
    printf 'VOLTAGE_DIR=%q\n' "$VOLTAGE_DIR"
    printf 'VOLTAGE_BACKUP_REMOTE=%q\n' "$VOLTAGE_BACKUP_REMOTE"
    for var in KEEP_DAYS REMOTE_KEEP_DAYS VOLTAGE_BACKUP_DIR; do
      if [[ -n "${!var:-}" ]]; then printf '%s=%q\n' "$var" "${!var}"; fi
    done
    env | grep "^${remote_env}" | sort | while IFS='=' read -r key value; do printf '%s=%q\n' "$key" "$value"; done
  } | put_file /etc/voltage/backup.env 600
  then
    changed "/etc/voltage/backup.env (remote $remote_name)"
  else
    ok "/etc/voltage/backup.env"
  fi
  if put_file /etc/cron.d/voltage-backup 644 <<EOF
# Voltage: the nightly backup, copied off the machine (scripts/backup-offsite.sh, OPS.md).
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
15 ${BACKUP_HOUR} * * * root ${VOLTAGE_DIR}/scripts/backup-offsite.sh >> /var/log/voltage-backup.log 2>&1
EOF
  then
    changed "cron: nightly off-site backup at ${BACKUP_HOUR}:15"
  else
    ok "cron: nightly off-site backup"
  fi
fi

if [[ "$CHANGED" -eq 0 ]]; then
  echo "provision: no changes"
else
  echo "provision: $CHANGED changed"
fi
