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
- `scripts/migrate.sh` applies pending steps explicitly (backup first); `scripts/deploy.sh` runs it before switching builds.
- Migrations only add, so a rollback (`scripts/rollback.sh`) keeps the schema and never runs `down` (RUNBOOK.md, section 5). `python -m app.store.migrate down --db <path>` is for undoing a step that was itself wrong, by hand, after a backup. Some steps refuse to go down while they hold data, by design.

## When something goes wrong

| You see | Do |
|---|---|
| `/ready` 503, `database` | Disk full or the file is gone. Check `df -h`, then the log. Restore the last backup if the file is damaged. |
| `/ready` 503, `migrations` | A start failed midway. Read the log for the step; fix and restart. |
| `/ready` 503, `storage` | The data dir is read-only or full. |
| Spend climbing fast | Pause paid work from the Admin page, then look at "Spend today" by vendor. |
| Lots of 429 in the log | Rate limits doing their job; per-bucket limits can be raised with `AVE_RATE_<NAME>=hits/seconds`. |
| A vendor is down | Jobs fail with the vendor's reason after two retries; users can Retry. Nothing else to do. |

## Failure drills (launch rehearsal, 2026-10-23)

Run against the rehearsal stack (the shipped compose stack, Postgres, mocked
vendors that wait and bill like the real ones) with `python3 tools/drills/drill.py all`
(`--port`, `--name` pick the stack; results in `docs/rehearsal/drills/final.json`).
Each drill makes a new user and video, asks for a line (the paid question), injects
the fault, then checks four things: no job stuck, no double charge (characters
billed equal the takes that exist), a clear status (one sentence, no trace), and
recovery with no manual step (the same go-ahead then voices the line).

| Drill | What happened | Before tonight | Now |
|---|---|---|---|
| Kill the API mid-job (SIGKILL to uvicorn while a line is being voiced) | Docker restarted the container in 3 s; the job read "The server restarted while this was running. Try again."; the go-ahead then worked. | **The 60 characters charged before the vendor call were never given back**, so a retry paid twice for one take. | Each charge is "open" until its call returns (`VoiceBudget.held`); the next start refunds charges a dead process left open. Billed = takes made. Pass. |
| Kill the worker container | Nothing user-facing: jobs run in the API process; the worker only purges and sends digests. Restarted with `up -d`. | Pass. | Pass. |
| Restart Postgres | Requests during the restart fail, then work again on their own (3 s later all 200). | The app had one connection and never reconnected (every request would fail until the app restarted; found reading the code before the drill); during the restart people saw "Something went wrong". | The next transaction reconnects (`store/db.py`, `store/pg.py`); while Postgres is down people get 503 "Voltage could not reach its database for a moment. Try again in a few seconds." Pass. |
| ElevenLabs answers 500 on every call | Two retries, then the job fails with "ElevenLabs is unavailable right now (500)."; every charge refunded. | Pass. | Pass. |
| ElevenLabs hangs 75 s, Claude hangs 70 s on half its calls | Timeouts, retries, then a clear failure; nothing charged; the next go-ahead works. | Claude's timeout reached the person as the SDK's own text with a docs link. | "I did not get an answer in time, so I stopped. Nothing was charged for the step that failed. Say it again and I'll retry." Pass. |
| Fill the data disk to 95% | Uploads answer 507 with a sentence; renders fail with the same sentence; `/ready` stays 200 (reads and downloads keep working); freeing space reopens both. | Nothing refused new work: uploads and renders would have run until the disk was truly full and then failed halfway with "No space left on device" (the generic 500). | `app/diskroom.py`: past AVE_DISK_FULL_PCT (95) or under 1 GB free, uploads and renders say "Voltage is short of storage space right now, so new uploads and renders are paused. Your videos are safe." Any ENOSPC anywhere answers 507 with it. Pass. |

What the drills taught about operating it:

- **`docker kill` is not a crash.** Docker treats it as a manual stop and the
  restart policy does not bring the container back. A real crash (the process
  dying, the kernel's OOM killer) is restarted in seconds. After a deliberate
  `docker kill`, run `docker compose up -d app`.
- **The day cap trips under a load test.** The first drill run found every paid
  step paused: the load test's mock spend had reached the $50 day cap. People saw
  the pause sentence and nothing was charged, which is the cap working. Keep
  load tests off the production database.
- Watch the disk: at 95% Voltage stops taking uploads and renders. `df -h /data`
  and the log line `disk short: ... refusing new uploads and renders`.
- One API process only: a second one on the same database refuses to start
  (`app/lease.py`).

## Deploy, migrate and roll back (rehearsed 2026-10-24)

`scripts/deploy.sh [REF]`, `scripts/migrate.sh` and `scripts/rollback.sh [SHA]`
(RUNBOOK.md, section 5). Images are tagged by git sha; rollback starts the
previous tag and keeps the schema, because migrations only add.

Rehearsed on the local stack (`RH_NAME=voltage-rb RH_PORT=8085`: the shipped
compose stack, Postgres 16, mocked vendors, the public profile), from an
empty database:

| Step | Command | Time | Result |
|---|---|---|---|
| 1. Older build | `scripts/deploy.sh cb29d1d` | 232 s (209 s of it the first, uncached image build) | 0001 to 0037 applied by migrate.sh before the switch; ready |
| 2. Data | a password account (signed up, verified, signed in) and an uploaded video | | accounts 1, videos 2 (with the sample), 2 media files, 196,096 bytes |
| 3. Newer build | `scripts/deploy.sh HEAD` (4359221, this branch) | 43 s (build 20 s, cached) | backup taken (`ave.pgdump`, `data.tar.gz`, `SHA256SUMS`); nothing pending; app, worker, web on `:43592217746a`; ready |
| 4. Migrate | `scripts/migrate.sh` | 4 s | backup taken; nothing pending, nothing changed; 37 steps listed as applied |
| 5. Roll back | `scripts/rollback.sh` | 15 s | back to `cb29d1d74686`, no build, schema kept; `/api/ready` 200 (database, migrations, storage, ffmpeg) |
| 6. Data check | sign in as the account, `GET /videos/p2`, `GET /videos` | | 200 and 200; counts and the media checksum identical to step 2 |

Then the case the rule is for, code older than the schema:

| Step | Command | Time | Result |
|---|---|---|---|
| 7. A build without 0037 | `scripts/deploy.sh 0c9cd0b^` (5042c0a, which knows 0001 to 0036) on the schema at 0037 | 60 s (build 46 s) | ready; it ignores 0037 (`beta_feedback`); sign-in and both reads 200; data identical |
| 8. Forward again | `scripts/rollback.sh 43592217746a` | 21 s | ready; data identical |

The history file after it (`.deploy/voltage-rb.history`):

```
cb29d1d74686 2026-10-24T05:59:04Z deploy
43592217746a 2026-10-24T06:00:36Z deploy
cb29d1d74686 2026-10-24T06:01:26Z rollback-from-43592217746a
5042c0ae0af1 2026-10-24T06:02:38Z deploy
43592217746a 2026-10-24T06:03:23Z rollback-from-5042c0ae0af1
```

What it showed:

- **A switch is a short outage, not zero downtime.** Polling `/api/health`
  every 0.25 s through step 8: 15 s without an answer (502 from nginx while
  the app restarted, then nothing while `web` was recreated after the app
  passed its health check). One API process per database (`app/lease.py`)
  rules out running old and new side by side; deploy at a quiet hour, and
  pause paid work first if a turn must not be cut off (a cut-off job reads
  "The server restarted while this was running. Try again." and its charge is
  refunded).
- Rollback takes seconds because nothing is built: keep the last few images
  on the VM (`docker image prune` with no `-a` keeps tagged images).
- Each deploy and migrate takes a backup first; on a VM they go to
  `<checkout>/backups` (or `/var/backups/voltage` from cron) and only the
  nightly cron copies off the machine.
- The nightly off-site copy (`scripts/backup-offsite.sh`) was run against
  this stack with a local rclone remote (no object store): dump, media and
  checksums copied, `shasum -c` OK, `pg_restore --list` reads 52 tables of data.
