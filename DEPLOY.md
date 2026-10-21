# Deploying Voltage

One Ubuntu VM running Docker Compose, with Caddy in front for HTTPS. This is
the launch shape: one machine, one API process, SQLite on a local volume.
Backups and restores are in `OPS.md` (`scripts/backup.sh`, `scripts/restore.sh`).

> The images in this kit (`backend/Dockerfile`, `frontend/Dockerfile`) were
> written without Docker on the machine that made them and have not been
> built yet. Build them once on the VM (or any Docker host) before launch day.

## What runs

| Service    | Image                         | What it does |
|------------|-------------------------------|--------------|
| `app`      | `backend/Dockerfile`          | The FastAPI API (uvicorn, port 8000, not published). Runs every request-triggered job (turns, renders, exports, imports) on threads inside itself, and still sends review digests. Applies database migrations at start. |
| `worker`   | the same image, `python -m app.worker` | Periodic maintenance: the daily Bin purge (`AVE_PURGE_DAILY`, on here, off on `app`), and the review digests when `AVE_WORKER_DIGESTS=1`. |
| `web`      | `frontend/Dockerfile`         | nginx serving the built app and proxying `/api/` to `app` (port 8080, loopback only). |
| `postgres` | `postgres:16-alpine`          | Ready for `DATABASE_URL`. Blank `DATABASE_URL` (the default) keeps SQLite. |
| `caddy`    | `caddy:2.8-alpine`            | HTTPS on 80/443 with an automatic Let's Encrypt certificate (profile `https`). |

Data lives in Docker volumes: `avedata` (`/data`: `ave.db` and `artifacts/`),
`pgdata`, and Caddy's certificates in `caddydata`.

Keep exactly one `app` container per data volume: jobs live in its threads and
SQLite is opened by one API process. Do not `--scale app=2`.

### The worker

The API process still runs its own review-digest scheduler, so the worker's
digests are off (`AVE_WORKER_DIGESTS=0`) to avoid sending one twice. When the
API's scheduler gets a switch to turn it off, turn it off there and set
`AVE_WORKER_DIGESTS=1`. The purge runs only in the worker (compose sets
`AVE_PURGE_DAILY=0` on `app`); its first run is a day after the worker starts.

## 1. The machine

- Ubuntu 24.04 LTS, 4 vCPU, 8 GB RAM, 100 GB+ disk (media is the bulk; size the
  disk for the uploads you expect, each source up to 500 MB, plus renders).
- A DNS `A` record (and `AAAA` if IPv6) for your domain pointing at the VM.
- Install Docker Engine and the Compose plugin (docs.docker.com/engine/install/ubuntu),
  then add your deploy user to the `docker` group.
- Unattended security updates: `sudo apt install unattended-upgrades`.

### Firewall

Only SSH and the web ports are open; the app, worker and Postgres are reachable
only on the Compose network, and `web` is bound to `127.0.0.1`.

```sh
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable
```

Docker publishes ports through iptables and bypasses ufw; that is why only
Caddy publishes on all interfaces. Use the cloud provider's firewall as well if
it has one (same rules). SSH by key only: `PasswordAuthentication no` in
`/etc/ssh/sshd_config`.

## 2. The code and secrets

```sh
sudo mkdir -p /opt/voltage && sudo chown "$USER" /opt/voltage
git clone <repo-url> /opt/voltage && cd /opt/voltage
cp .env.example .env
chmod 600 .env
```

Edit `.env`. At least:

- `VOLTAGE_DOMAIN`, `ACME_EMAIL`, `COMPOSE_PROFILES=https`
- `AVE_PUBLIC_URL=https://<your domain>` (OAuth redirects, share links and emails use it)
- `AVE_AUTH=google`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; register
  `https://<your domain>/api/auth/callback` as an authorized redirect URI on the
  OAuth client in Google Cloud Console
- `AVE_SESSION_SECRET` and `AVE_SHARE_SECRET`: `openssl rand -hex 32` each
- `POSTGRES_PASSWORD`: `openssl rand -hex 24` (required by compose even while SQLite is used)
- `AVE_ALLOWED_EMAILS` for a private beta
- `AVE_FLAG_OWNERS` and `AVE_ADMIN_OWNERS`: the signed-in owner ids (for
  example `google:<sub>`) that see phase flags and the admin page; `local` means nobody once sign-in is on
- vendor keys: `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY` (and
  `ANTHROPIC_WORKSPACE_ID` if the key is not workspace-scoped)
- the money ceilings (`AVE_PROJECT_BUDGET_USD`, `AVE_USER_BUDGET_USD`, ...)

`.env` never goes into git or into an image (`.dockerignore` excludes it); it
is read by Compose and passed to the containers as environment variables. Every
variable the backend reads is listed in `.env.example` with its default
(a backend test keeps that list complete).

## 3. Start

```sh
cd /opt/voltage
docker compose up -d --build
docker compose ps                         # app and web "healthy"
curl -fsS https://<your domain>/api/health
```

`/api/health` says which vendors are live (`transcription`, `voice`, `planner`,
...) and that `auth` is `google`. Caddy gets the certificate on the first request
to the domain; `docker compose logs caddy` shows it.

## 4. Logs

Every service logs to Docker's `json-file` driver, rotated at 20 MB x 5 files
per container (set in `docker-compose.yml`), so logs cannot fill the disk.

```sh
docker compose logs -f app worker         # follow
docker compose logs --since 1h web
```

Optionally make rotation the default for anything else on the host, in
`/etc/docker/daemon.json`:

```json
{ "log-driver": "json-file", "log-opts": { "max-size": "20m", "max-file": "5" } }
```

then `sudo systemctl restart docker`.

## 5. Backups

What to keep: the `avedata` volume (`ave.db` and `artifacts/`) and `.env`.
`OPS.md` describes `scripts/backup.sh` (a consistent copy with SQLite's
`.backup`, plus the artifacts) and `scripts/restore.sh`. Run the backup
nightly from the host's crontab (`crontab -e`):

```cron
# 03:15 every night: Voltage backup (OPS.md); keeps its own log
15 3 * * * cd /opt/voltage && scripts/backup.sh >> /var/log/voltage-backup.log 2>&1
```

Ship the backups off the machine (object storage or another host) and test a
restore before launch and then monthly. Rotate `/var/log/voltage-backup.log`
with logrotate (`/etc/logrotate.d/voltage`):

```
/var/log/voltage-backup.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
}
```

A one-off consistent copy of the database by hand, without the script:

```sh
docker compose exec app sqlite3 /data/ave.db ".backup /data/ave-$(date +%F).db"
```

## 6. Updates and rollback

Take a backup first (`scripts/backup.sh`). Then:

```sh
cd /opt/voltage
git fetch && git log --oneline HEAD..origin/main      # what is coming
git pull --ff-only
docker compose up -d --build
docker compose ps && curl -fsS https://<your domain>/api/health
```

Migrations run when the API starts (each `Database` open applies what is
pending), so there is no separate migrate step. `python -m app.store.migrate
status --db /data/ave.db` shows where the schema stands.

Roll back the code: check out the previous commit and rebuild.

```sh
git checkout <previous-commit>
docker compose up -d --build
```

If that release added a migration, roll the schema back one step first, while
the new code is still running (the new code knows how to undo its own step):

```sh
docker compose exec app python -m app.store.migrate down --db /data/ave.db
```

`down 2` undoes two steps. If a migration cannot be undone cleanly, restore the
pre-update backup with `scripts/restore.sh` (OPS.md) instead.

## 7. Pre-launch checklist

- [ ] Both images built on the VM (`docker compose build`); `docker compose ps` shows `app` and `web` healthy
- [ ] DNS resolves to the VM; `https://<domain>` loads with a valid certificate; `http://` redirects to `https://`
- [ ] `ufw status` shows only 22, 80, 443; the cloud firewall matches; SSH is key-only
- [ ] `.env` is mode 600, owned by the deploy user, and not in git (`git status` is clean)
- [ ] `AVE_AUTH=google`; signing in works; the Google redirect URI matches `AVE_PUBLIC_URL`
- [ ] `AVE_PUBLIC_URL` is the https address (share links and emails point at it)
- [ ] `AVE_SESSION_SECRET`, `AVE_SHARE_SECRET` and `POSTGRES_PASSWORD` are fresh random values
- [ ] `AVE_ALLOWED_EMAILS` set if the beta is private; `AVE_ADMIN_OWNERS` is your signed-in id, not `local`
- [ ] `AVE_DRY_RUN` is blank and `/api/health` shows the real vendors; the money ceilings are set
- [ ] `AVE_CHAOS` and `AVE_CHAOS_FORCE` are blank
- [ ] A test upload of a large file (several hundred MB) succeeds through Caddy and nginx
- [ ] A turn runs and its live progress updates in the editor (Server-Sent Events pass through)
- [ ] The nightly backup has run once and a restore to a scratch directory worked
- [ ] Disk alerting (or a weekly check) on the volume holding `avedata`
- [ ] `SETUP_NEEDED.md` reviewed: email provider, Sentry, billing and trust and safety are still fakes until set up
