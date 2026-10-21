# Operating Voltage

How to keep a running Voltage healthy: checks, backups, restores, and what to
do when something goes wrong. For setting up a server, see `DEPLOY.md`.

## Health and readiness

| Endpoint | Means | Use it for |
|---|---|---|
| `GET /api/health` | The process is up; lists which vendors are real (`transcription`, `voice`, `cloning`...). | Uptime checks. |
| `GET /api/ready` | 200 only when the database answers, every migration is applied, the data dir takes writes and ffmpeg runs. 503 otherwise, with each check's `ok`. | The load balancer, and after a deploy or restore. |
| `GET /api/status` | Public: whether new paid work is paused (the banner). | The status page. |

`/ready` never shows error text. The reason a check failed is in the server log (`readiness check <name> failed: ...`).

## Jobs that cannot finish

Jobs run inside the API process. On every start, the server fails anything a
previous process left queued or running ("The server restarted while this was
running. Try again."). While it runs, a sweep fails any job silent past its
kind's timeout ("This took too long and was stopped. Try again."; timeouts in
`backend/app/jobs/activity.py`, `TIMEOUT_SECONDS`). Nothing stays "running".

Vendor calls have timeouts (ElevenLabs and Whisper per call, Claude 60 s) and
are tried at most three times (two retries, with backoff). Every attempt of
one call sends the same `Idempotency-Key`.

## Spend

- Today's spend across everyone, by vendor, and the kill switch: the Admin page (`#admin`, "Spend today"), or `GET /api/admin/spend`.
- Pause all new paid work: the "Pause paid work" button, or `python -m app.flags set launch.paid_paused on --db <path>`. Everyone sees a short notice; free steps keep working.
- The day cap (`AVE_DAILY_SPEND_CAP_USD`, default 50) pauses new paid work on its own until 00:00 UTC.

## Backups

`scripts/backup.sh [DATA_DIR] [BACKUP_DIR]` makes one folder
`voltage-<UTC time>` holding:

- `ave.db`: the SQLite database, copied with `.backup` (safe while the server runs; includes the WAL), integrity-checked. With `DATABASE_URL=postgres://...` it is `ave.pgdump` from `pg_dump` instead.
- `data.tar.gz`: everything else in the data dir (the media store under `artifacts/`, the generated signing key file if there is one).
- `SHA256SUMS`: checked by the restore.

Backups older than `KEEP_DAYS` (default 14) are deleted by the same run.

Nightly, on a single VM with Docker Compose (see `DEPLOY.md`):

```sh
# crontab -e (as the deploy user)
15 3 * * * cd /opt/voltage && docker compose exec -T app /srv/scripts/backup.sh /data /data/backups >> /var/log/voltage-backup.log 2>&1
```

Then copy `/data/backups` off the machine (for example `rclone sync` to object
storage). A backup on the same disk is not a backup.

Without Docker: `AVE_DATA_DIR=/path/to/var scripts/backup.sh`.

## Restore (tested)

1. Stop the server (`docker compose stop app worker`).
2. `scripts/restore.sh <backup folder> <data dir>`. It checks the checksums, refuses to write over a data dir that has a database unless you pass `--force` (move the old one aside first), copies the database back, integrity-checks it and unpacks the media.
3. Check the schema: `PYTHONPATH=backend python -m app.store.migrate status --db <data dir>/ave.db`. Every step should be applied; if the code is newer, the next start applies the rest.
4. Start the server and check `GET /api/ready` answers 200.

What was tested: `backend/tests/launch/test_backup.py` backs up a database and
media, restores into an empty dir, and compares every table's row count and
the media bytes; it also checks the refusal to overwrite and a tampered
backup. On 2026-10-22 the same was done by hand on a copy of the live
database (5 videos, 165 messages, 225 charges, 193 turns, 41 edits: identical
after the restore).

## Migrations

- Status: `python -m app.store.migrate status --db <path or postgres URL>`.
- Every start applies pending steps in order, each in its own transaction.
- Roll back one step: `python -m app.store.migrate down --db <path>` (take a backup first). Some steps refuse to go down while they hold data, by design.

## When something goes wrong

| You see | Do |
|---|---|
| `/ready` 503, `database` | Disk full or the file is gone. Check `df -h`, then the log. Restore the last backup if the file is damaged. |
| `/ready` 503, `migrations` | A start failed midway. Read the log for the step; fix and restart. |
| `/ready` 503, `storage` | The data dir is read-only or full. |
| Spend climbing fast | Pause paid work from the Admin page, then look at "Spend today" by vendor. |
| Lots of 429 in the log | Rate limits doing their job; per-bucket limits can be raised with `AVE_RATE_<NAME>=hits/seconds`. |
| A vendor is down | Jobs fail with the vendor's reason after two retries; users can Retry. Nothing else to do. |
