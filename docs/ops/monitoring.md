# Monitoring: errors, uptime and the backup

What to set up once the VM is provisioned (`scripts/provision.sh`) and the
stack is running (`scripts/deploy.sh`). None of it is needed for Voltage to
run: without it, errors stay in the log and on the Admin page, and nobody is
told when the site is down.

## 1. Error reports (Sentry)

What the app does today (`backend/app/errors_report.py`):

- Every unhandled server error (the exception handler in `app/api/main.py`)
  and every browser error the front end posts to `POST /api/errors`
  (`window.onerror` and unhandled promise rejections, `frontend/src/lib/errors.ts`)
  goes through one reporter.
- The reporter always writes the report to the log and to the `error_reports`
  table. The Admin page lists the newest (Feedback > Errors reported).
- With `SENTRY_DSN` set, each report is also posted to Sentry's envelope
  endpoint over HTTPS, in the background, with no SDK. Cookies,
  authorization headers, request bodies and secret-looking values are
  scrubbed before anything leaves the machine. A failed post is logged and
  never breaks the request.

What to set:

| Where | What |
|---|---|
| sentry.io (or your own Sentry) | Create one project, platform "Python". Copy its DSN: `https://<key>@<host>/<project_id>`. |
| `.env` on the VM | `SENTRY_DSN=<that DSN>`. Then `scripts/deploy.sh` (or `docker compose up -d app`) so the app reads it. |
| The cloud firewall | Outbound HTTPS to the DSN's host must be allowed (it is by default; `provision.sh` allows all outgoing). |
| Sentry, Alerts | One alert rule: "A new issue is created" and "The issue is seen more than 20 times in 1 hour", sent to your email. |

Variables the app reads for this:

| Variable | Default | Meaning |
|---|---|---|
| `SENTRY_DSN` | blank | Blank: reports stay local. A value that is not a DSN logs a warning at start and reports stay local. |

Events are sent with `environment: production` and the logger `voltage`.
For a staging copy, use a second Sentry project (its own DSN) rather than a
second environment.

Check it works: after a deploy, `docker compose logs app | grep -i sentry`
shows no "bad DSN" warning, and the Admin page's error list and Sentry show
the same new reports.

## 2. Uptime alerts

Voltage answers three public endpoints through Caddy (OPS.md, "Health and
readiness"):

| Check | URL | Alert when |
|---|---|---|
| Up | `https://<domain>/api/health` | not 200 for 2 checks in a row (the process is down, or Caddy or nginx is) |
| Ready | `https://<domain>/api/ready` | 503 for 3 checks in a row (database, migrations, the data disk or ffmpeg). The body says which check is false; the log says why. |
| Certificate | `https://<domain>/` | the TLS certificate expires in under 14 days (Caddy renews at 30; this catches a renewal that keeps failing) |

What to set, in any uptime service (UptimeRobot, Better Stack, Healthchecks.io,
a cloud provider's own checks): the two HTTP checks every 1 minute from at
least two regions, plus the certificate check, alerting your email (and phone
for "Up"). Use a keyword or status check only; never put a session cookie or
key in a monitor.

The app reads no variable for this: the checks are made from outside.

## 3. The disk

Voltage pauses uploads and renders past `AVE_DISK_FULL_PCT` (default 95) or
under 1 GB free, and logs `disk short: ...`. Alert well before that:

- In the cloud provider's monitoring, an alert on the data disk at 80% used.
- Without one, a weekly look: `df -h /var/lib/docker`.

| Variable | Default | Meaning |
|---|---|---|
| `AVE_DISK_FULL_PCT` | 95 | Used percentage at which new uploads and renders are refused. |

## 4. The nightly backup

`provision.sh` installs the cron job only when it is given a destination.
Run it with:

```sh
sudo DEPLOY_USER=deploy \
     VOLTAGE_BACKUP_REMOTE=offsite:<bucket>/voltage \
     RCLONE_CONFIG_OFFSITE_TYPE=s3 \
     RCLONE_CONFIG_OFFSITE_PROVIDER=<provider> \
     RCLONE_CONFIG_OFFSITE_ENDPOINT=<endpoint> \
     RCLONE_CONFIG_OFFSITE_ACCESS_KEY_ID=<key id> \
     RCLONE_CONFIG_OFFSITE_SECRET_ACCESS_KEY=<secret> \
     scripts/provision.sh
```

The remote's name (`offsite` here) is yours to choose; its settings are
rclone's own `RCLONE_CONFIG_<NAME>_<OPTION>` variables (rclone.org/docs, "Config
file", environment variables), so any backend rclone supports works. They are
kept in `/etc/voltage/backup.env` (root only, mode 600), never in the repo.
Use a bucket key that can write and list but not delete, if the provider
allows it, and set the bucket's own retention there.

Every night at 03:15 UTC (`BACKUP_HOUR` changes the hour)
`scripts/backup-offsite.sh` makes `voltage-<UTC time>/` with the Postgres dump
(`ave.pgdump`, or `ave.db` on SQLite), the media (`data.tar.gz`) and
`SHA256SUMS`, copies it to the remote, and deletes local copies older than
`KEEP_DAYS` (7). `REMOTE_KEEP_DAYS` also prunes the remote. Its log is
`/var/log/voltage-backup.log` (rotated weekly by `/etc/logrotate.d/voltage`).

Know it ran: a Healthchecks.io-style "dead man's switch" is the simplest. Add
`&& curl -fsS <ping url>` to the end of the line in `/etc/cron.d/voltage-backup`
and have it alert when no ping comes for 25 hours. Restore one backup to a
scratch directory each month (RUNBOOK.md, section 6).

## Checklist

- [ ] `SENTRY_DSN` set; a test error shows in Sentry and on the Admin page
- [ ] Sentry alert rule on new issues, to your email
- [ ] Uptime checks on `/api/health` and `/api/ready`, plus the certificate
- [ ] Disk alert at 80%
- [ ] `/etc/cron.d/voltage-backup` exists; one backup is in the bucket; one restore tried
