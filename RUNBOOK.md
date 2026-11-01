# Voltage runbook

What to do when something goes wrong on launch day and after. Every command
assumes the Docker Compose setup in `DEPLOY.md` (one VM, `/opt/voltage`, data
in `/data` inside the `app` container). Health checks, backups and migrations
are described in `OPS.md`; this file is the "it is happening now" version.

Run commands from `/opt/voltage`. `app` is the API container; Python modules
run inside it with `docker compose exec app python -m ...`.

## Before anything: who is an admin

The admin page is `https://<your domain>/#admin` (Settings > Admin). Only the
people in `AVE_ADMIN_OWNERS` see it; everyone else gets 404 from every
`/api/admin/...` route. An entry is either an owner id (`google:<sub>`,
`acct:<id>`, `email:<address>`) or an email address: an entry with `@`
matches a verified password account, or a Google or emailed-link sign-in,
with that address (case does not matter). So the founder can be named before
they sign up:

```sh
# .env
AVE_ADMIN_OWNERS=founder@yourdomain.com
docker compose up -d app        # picks up the new .env
```

Every admin action (credits granted, refunds, suspensions, the kill switch,
feature changes, share links taken down) is written to the append-only
`admin_audit` table and shown on the admin page under **Audit trail**, newest
first. From a shell: `docker compose exec app python -m app.admin audit --db /data/ave.db`.

## 1. A vendor is down

| Vendor | Used for | How it shows | What users see |
|---|---|---|---|
| ElevenLabs | voicing lines, cloning, designing voices | `voice_line`, `clone`, `design_voice` jobs fail; log lines `elevenlabs` with 5xx, 429 or timeouts | The line's chip reads Failed: "Something went wrong on our end. Nothing was charged. Try again in a minute." and a Retry; Activity lists the failed job. A line its safety filter refuses reads "The voice service's safety filter refused the line at 0:06 (...). Nothing was charged. Reword that line and try again." |
| OpenAI (Whisper) | transcribing uploads, hearing takes | uploads fail at transcription; log lines `openai` / `TranscriptionError` | The upload says "Something went wrong on our end. Nothing was charged. Try again in a minute."; nothing is charged |
| Anthropic (Claude) | Voltage's turns, the project check | turns fail; log lines `anthropic` / `APIStatusError` | Voltage's reply is the same sentence (or, if the turn paid for a step before failing, says what that cost); the user can send it again |
| Stripe / Razorpay | top-ups and plans (only when real keys are set) | `checkout failed` / `refund ... failed` warnings in the log | "We could not open the payment page. Nothing was charged; try again." Refund: "The refund did not go through. Nothing changed; try again." |
| Resend | sign-up confirmations, password resets, invites, digests | `email (resend) failed` or `refused` in the log; rows in `notify_outbox` with provider `resend (failed)` | Nothing on screen: the email just does not arrive. Sign-up and reset wait on it |

Every vendor call has a timeout and is tried three times at most (two
retries, one Idempotency-Key), so a short blip heals itself. Nothing is
charged for a call that failed.

How you hear about it (run 5 item 1): every failure on our side (a refused or
missing key, a quota, an outage, a timeout, a bug) is classified once
(`backend/app/failures.py`). People never see the vendor's text. The real
cause goes to the log (`voltage.failures`, "our side at ..."), to Admin >
Feedback > Errors reported (source `vendor`, and Sentry when `SENTRY_DSN` is
set), and to every admin's bell and email digest as "Failures on our side"
(for example "Claude (Anthropic) failed: the key was refused."), at most once
per vendor and cause every 30 minutes.

What to do:

1. Confirm it: `curl -fsS https://<your domain>/api/health` (which vendors are real), then
   `docker compose logs --since 30m app | grep -iE "elevenlabs|openai|anthropic|stripe|razorpay|resend"`.
   Check the vendor's own status page.
2. If paid calls are failing in a loop and still costing (for example Claude answers but ElevenLabs fails every take), pause paid work (section 2). Free steps keep working and everyone sees a short notice.
3. Resend down: emails are not queued for a later retry. When it is back, people press "Send it again" on the sign-in page (confirmation) or "Forgot your password" (reset). Find who missed one:
   `docker compose exec app sqlite3 /data/ave.db "select created_at, to_addr, kind from notify_outbox where provider = 'resend (failed)' order by id desc limit 50"`.
4. Stripe or Razorpay down: nothing is granted until the provider confirms a payment; their webhooks are retried by the provider, and a repeated webhook grants nothing twice. Nothing to replay by hand.
5. When it is back: resume paid work if you paused it; tell people with failed jobs to press Retry.

Rehearse it (never on the public server): `AVE_CHAOS` injects faults at the
ElevenLabs, OpenAI and Anthropic seams without any network call or charge.
It is refused when sign-in is on unless `AVE_CHAOS_FORCE=1`, and production
(`AVE_ENV=production`) refuses to start with it. On a local copy:

```sh
AVE_CHAOS="elevenlabs=status:503" ...        # every voicing call answers 503
AVE_CHAOS="anthropic=hang:70"   ...           # Claude hangs past its 60 s timeout
AVE_CHAOS="openai=reset@0.5"    ...           # half of the transcription calls drop
```

(`vendor=kind[:arg][@rate]`, kinds `status`, `hang`, `slow`, `reset`, and `refuse` for ElevenLabs's safety filter; see
`backend/app/chaos.py`.) `/api/health` shows the faults in `chaos`. Stripe,
Razorpay and Resend are not covered by `AVE_CHAOS`; their failures are
rehearsed by the backend tests, which mock their HTTP
(`backend/tests/golive/test_item7_providers.py`).

## 2. Spend spike

How it shows: the admin page's **Spend today** climbing fast (it is today's
spend across everyone since 00:00 UTC, by vendor), or the day cap pausing
paid work on its own (the card says "Paused: day cap reached").

1. **Stop the bleeding.** Admin page > Spend today > **Pause paid work**.
   New paid work stops for everyone at once; running turns stop at their
   next paid call. Without the page:
   `docker compose exec app python -m app.flags set launch.paid_paused on --db /data/ave.db`
   (this one is not in the audit trail; write it down).
2. **The day cap** (`AVE_DAILY_SPEND_CAP_USD`, default 50) pauses new paid work on its own until 00:00 UTC. To lower it: set it in `.env` and `docker compose up -d app`.
3. **Find the owner.** Who spent today:
   ```sh
   docker compose exec app sqlite3 /data/ave.db "select v.owner, round(sum(u.usd), 2) as usd from usage u join videos v on v.id = u.project_id where u.at >= strftime('%Y-%m-%dT00:00:00', 'now') group by v.owner order by usd desc limit 10"
   ```
   Then Admin > **People**: paste part of their address (or the owner id) and Open. Their card shows spend today, this month and all time, by vendor, their credits and their recent jobs.
4. **Suspend** if it is abuse: in their card, **Suspend** with a reason. They and their members get "This account is suspended..." on every request, their running jobs are cancelled, their next paid step refuses, their share links and media links stop. Without the page:
   `docker compose exec app python -m app.admin suspend <owner id> --reason "spend spike" --db /data/ave.db`.
5. **Resume** paid work (the same button, or `... app.flags set launch.paid_paused off ...`). If it was not abuse, raise their credits instead (**Grant credits**, with a reason) or set a per-person feature off (**Features for this person**).

## 3. An abuse report

Where it arrives: the public form (`POST /api/abuse-reports`, on every share
page and in Help) stores it in `abuse_reports`, puts a bell notice to every
admin ("Abuse report #N: ...") and emails `AVE_TRUST_EMAIL`. The newest are on
the admin page under **Abuse reports**. Someone must watch these from day one.

1. **Triage.** Open the location in the report (usually a share link `.../#s/<token>`). Is it someone's voice without consent, a public figure, deceptive, hateful? If you are unsure, take the link down first and decide after; it can be shared again by its owner.
2. **Keep evidence before acting.** The report row stays in `abuse_reports`; copy what the link showed:
   ```sh
   docker compose exec app sh -c 'mkdir -p /data/evidence && sqlite3 /data/ave.db ".mode json" "select * from abuse_reports where id = <N>" > /data/evidence/abuse-<N>.json'
   docker compose exec app sqlite3 /data/ave.db "select id, owner, scope, target, created_at, expires_at from share_tokens where id = '<share id>'"
   ```
   The share id is the part of the link after `#s/` and before the first dot. Take a backup now (section 6) so the media is kept even if the owner deletes it.
3. **Take the link down.** Admin page > Audit trail > **Take the link down**: paste the link and the report number as the reason. From then on the link says "This link was turned off by the person who shared it." This is audited.
4. **Suspend the owner** if the content breaks the rules (Admin > People > their card > Suspend, reason "Abuse report #N"). All their share links stop at once, reviewers' included; unsuspending brings them back, so take the bad link down too.
5. **Withdrawn consent** (a speaker says "that is my voice"): the owner can withdraw consent on the video (`POST /videos/<id>/consent/withdraw` deletes the speaker's clones at the vendor). If the owner does not act, suspend.
6. Reply to the reporter if they left a contact. Note what you did in the audit reason.

A report about a cloned voice (or a legal order about one) follows section 7 as well.

## 4. A deletion or data request

- **"Send me my data"**: the person does it themselves in Settings > Your data (`POST /api/me/data-export`): a zip of JSON, one file per kind of record (their videos and everything made on them, projects, notifications, feedback, billing, consent records, analytics events, liveness attempts, data requests), plus `media.json` listing every stored file by content address. Media is not in the zip; it stays downloadable in the app while the account exists. If they cannot sign in (suspended or locked out), confirm who they are by email, then unsuspend long enough for them to export, or ask them to sign in and use Settings.
- **"Delete my account"**: Settings > Account > Delete everything (`DELETE /api/account`). It deletes every project with its media and the voices made for it, every voice of their own at ElevenLabs (a failure is logged by name: `voice ... is still at ElevenLabs`; delete it in the ElevenLabs dashboard), their samples, defaults, pins, templates, and the password account. A `data_requests` row of kind `deletion` is kept as the record that it happened.
- **What is kept, from the code**:
  - **Charges** (`usage`) are never deleted; a purged item leaves its name in `purged_items` so totals still add up.
  - **Consent records** of purged videos and voices stay in `purged_items.consent` for `AVE_CONSENT_RETENTION_YEARS` (default 7, until legal confirms), then the worker's purge clears them.
  - **The Bin** keeps deleted videos and projects 30 days; the worker runs the purge daily (`AVE_PURGE_DAILY=1` on `worker` in `docker-compose.yml`). By hand: `docker compose exec app python -m app.purge --days 30 --dry-run`, then without `--dry-run`.
  - **Invoices** (`invoices`) stay for tax records; the admin audit (`admin_audit`) cannot be edited or deleted.
  - **Backups** keep 14 days (`KEEP_DAYS`), so deleted data leaves backups within 14 days of the deletion.
- Keep a note of the request and the date in your own records: the audit trail holds admin actions only.

## 5. A bad deploy and rollback

Three commands, run from the checkout on the VM (`/opt/voltage`):

| Command | What it does |
|---|---|
| `scripts/deploy.sh [REF]` | Builds REF (default `HEAD`; fetch and `git pull --ff-only` first) as `voltage-backend:<sha>` and `voltage-web:<sha>`, backs up, migrates with the new image while the old one still serves, switches app, worker and web to the new images, waits for `/api/ready`, and records the sha in `.deploy/voltage.history`. |
| `scripts/migrate.sh` | Backs up, then applies pending migrations with the running build's image and prints every step's status. With nothing pending it changes nothing. (The API also applies pending steps when it starts.) |
| `scripts/rollback.sh [SHA]` | Starts the build deployed before the running one (or SHA) from images already on the machine: no build, no migrations, about a minute. |

Each prints its timings. `docker compose ps` and `.deploy/voltage.history`
say what is running.

### The rule: migrations only add (expand only)

A rollback never runs `migrate down` and never drops anything. The schema
stays as the newer build left it, and the older build runs on it. That works
because every migration only adds:

- new tables, new indexes, new columns that are nullable or have a default;
- never a dropped or renamed table or column, a narrowed type, or a new
  `NOT NULL` without a default, in the same release as the code that stops
  using the old shape.

Removing something takes two releases: first a release whose code no longer
reads or writes it (the old shape stays in the schema), then, once nobody will
roll back past that release, a migration that removes it. A release that
needs a breaking change is not one `rollback.sh` can undo: restore the
pre-deploy backup instead (section 6).

The older build ignores what it does not know: it applies only the steps it
has, and `/ready` checks only that those are applied. `python -m
app.store.migrate down` is still there for a step that was itself wrong, by
hand, after a backup; some steps refuse to go down while they hold data, by
design (0020, 0036).

### How a bad deploy shows

`deploy.sh` stops with "not ready" (`/api/ready` answers 503: `migrations` or
`database` false; the reason is in `docker compose logs app`), errors climbing
on the admin page (Feedback > Errors reported) or in Sentry, or people writing in.

### Roll back

1. **Pause paid work** first if anything is charging wrongly (section 2).
2. `scripts/rollback.sh`. It names the build it goes back to and ends with "ready in N s".
3. `curl -fsS https://<your domain>/api/ready` from outside.
4. Find and fix the cause on a branch; when it is fixed, `git pull --ff-only` and `scripts/deploy.sh` again.

`rollback.sh` twice in a row goes back to the newer build; to go further back,
name a sha: `scripts/rollback.sh <sha>` (it must have been built on this
machine; `scripts/deploy.sh <sha>` builds one that was not).

Rehearsed on the local stack on 2026-10-24: OPS.md, "Deploy, migrate and roll back".

## 6. Restore from a backup

The nightly backup (OPS.md) makes `/data/backups/voltage-<UTC time>/` with
`ave.db` (or `ave.pgdump` on Postgres), `data.tar.gz` (the media) and
`SHA256SUMS`. Copies off the machine are your safety net.

1. Pause paid work if the server still answers, and tell people (a short outage).
2. Stop the API and the worker: `docker compose stop app worker`.
3. Pick the backup: `docker compose run --rm --no-deps app ls /data/backups`.
4. Restore. The script checks the checksums, refuses to write over a database unless you pass `--force`, restores the database and the media and runs an integrity check:
   ```sh
   docker compose run --rm --no-deps app /srv/scripts/restore.sh /data/backups/voltage-<time> /data --force
   ```
   (`--force` because `/data` already has a database. To keep the damaged one, move it aside first: `docker compose run --rm --no-deps app mv /data/ave.db /data/ave.db.broken`, then run without `--force`.)
5. Check the schema: `docker compose run --rm --no-deps app python -m app.store.migrate status --db /data/ave.db`. If the code is newer, the next start applies the rest.
6. Start: `docker compose up -d app worker`, then `curl -fsS https://<your domain>/api/ready` must answer 200.
7. Resume paid work. Anything made after the backup's time is gone; say so to the people who wrote in that window (`select owner, created_at from videos where created_at > '<backup time>'` on the damaged copy, if you kept it).

Restore is tested: `backend/tests/launch/test_backup.py` backs up, restores into an empty directory and compares every table's row count and the media bytes.

## 7. Abuse and takedown: cloned voices

Voice consent V1 (behind `voices.cloning_verified`). For a report or a legal
order about a voice made with Voltage: a cloned voice used without consent,
a public figure's voice, a fraud or impersonation script, an election line.
Section 3 still applies to the link itself; this is the voice side.

Everything below is on the admin page (`#admin`); every action needs a reason
and is written to the audit trail. Use the abuse report's number (`#N`) as the
reason, so the trail reads as one story.

### 1. The report arrives; the clock starts

It comes from the public form (Admin > Abuse reports, a bell notice and an
email to `AVE_TRUST_EMAIL`), from an email to the Grievance Officer, or as a
legal order (a court, the police, a government notice under the IT Rules).
Write down when it arrived. **Target: act on a legal order within 3 hours**
of receiving it (disable the voice and the links, step 3), whatever the time
of day; a reporter's complaint within 24 hours. Who is on call for this is
the owner's to set before the flag goes public. If a report arrives by email,
enter it in the form yourself (`#acceptable-use`, Report misuse) so it has a
number and Trace can find it.

### 2. Find it with Trace; preserve the logs

Admin > Abuse reports > **Trace** on the report (or Admin > **Trace**, and
paste the export id `ve_...`, the reminder reference `ex_...`, the
provenance mark, or the report number). Trace lists the files, the voices
(scope, status, source video and speaker), every attestation for them (who,
which choice, the statement version, time, IP, browser), the export
confirmation (label on or off), the synthesis log rows of the lines the
export plays with their line checks, and the people. The call itself is
audited (`voice_trace`). The route is `GET /api/admin/exports/{ref}/trace`.

Preserve before you change anything:

```sh
docker compose exec app sh -c 'mkdir -p /data/evidence/report-<N>'
# The rows behind it: attestations, the export confirmation, line checks, the synthesis log, the voice and the marks.
for t in voice_records voice_attestations export_attestations line_checks synthesis_log; do
  docker compose exec app sh -c "sqlite3 /data/ave.db '.mode json' \"select * from $t where owner = '<owner id>'\" > /data/evidence/report-<N>/$t.json"
done
docker compose exec app sh -c "sqlite3 /data/ave.db '.mode json' \"select * from provenance_marks where export_id = '<export id>' or mark = '<mark>'\" > /data/evidence/report-<N>/marks.json"
```

Then take a backup (section 6) so the media is kept even if the owner
deletes it. Nothing in the takedown deletes these rows: attestations are
kept 7 years, line checks and the synthesis log 2 years (Terms, Records we
keep about voices). A line's words are stored only when it was blocked or
held; for the rest the log has a hash, so save the export file itself too.

### 3. Disable the voice and the links; suspend cloning if credible

- **The links.** Every live link that opens the video, in one call:
  `POST /api/admin/links/revoke {"video_id": "<video id from Trace>", "reason": "Abuse report #N"}`
  turns off its share and review links, a project link that shows it, and a
  batch export link with a file of it, whoever made them (one
  `share_revoke` audit row per link). A single link: Admin > Audit trail >
  **Take the link down** (`POST /api/admin/shares/{id}/revoke`). With sign-in
  on, call the routes from the browser console of the admin page:
  `fetch('/api/admin/links/revoke', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'voltage'}, body: JSON.stringify({video_id: 'p12', reason: 'Abuse report #N'})}).then(r => r.json())`.
- **The voice, and cloning for the user.** If the report is credible:
  Admin > People > their card > Voice cloning > **Suspend cloning**, reason
  `Abuse report #N` (`POST /api/admin/users/{owner}/suspend-cloning`). Every
  cloned voice of theirs (from a speaker or an uploaded recording) stops at
  once, and no new clone is made. There is no switch for one voice alone; a
  suspension is the way to disable it, and **Restore cloning** brings the
  others back once the voice in question is withdrawn. To delete it at the
  voice service for good, the owner withdraws it (`POST /api/voices/{id}/withdraw`);
  if they will not, keep cloning suspended.
- **Everything else** (the account is the problem, not one voice): suspend
  the account (section 3, step 4).

### 4. Reply; add a public figure to the no-go list

Reply to the reporter (if they left a contact) and to the user, saying what
was done and why, unless the law or someone's safety stops you. For a legal
order, reply to the issuer with the time you acted.

If the voice is a public figure's (or anyone who asked not to be cloned):
Admin > Voice safety > **No-go voices** > Add, from **Export mark or abuse
report number** (paste the mark or `#N`) or from an uploaded clip, with the
person's name and the reason (`POST /api/admin/no-go-voices`, audited
`no_go_add`). Only the voice's vector is kept. From then on a clone of that
voice is blocked at 0.92 similarity and held for review from 0.84.

### 5. Record the outcome

Every step above is already in the audit trail (`share_revoke`,
`voice_suspend`, `no_go_add`, `voice_trace`). Add the outcome as the reason of
the last action, or, if nothing was done, say why in the report's row and in
your own records (the trail holds admin actions only). Note the time you
acted against the time the report arrived.

### Changing the consent wording

The attestation and the export reminder's words, and their version, live in
one place: `STATEMENT`, `EXPORT_STATEMENT` and `STATEMENT_VERSION` in
`backend/app/safety/voice_guard.py`. The front end shows the same words from
`frontend/src/consent/copy.ts`, and its test fails if a sentence there is not
in `voice_guard.py`. A confirmation counts only for the version it was given
under, so a new version asks everyone again the next time they use a cloned
voice or export one.

To change a word (for example after the lawyer's review):

1. Edit the words in `voice_guard.py` and the same words in `copy.ts`.
2. Set `STATEMENT_VERSION` to today's date (`YYYY-MM-DD`).
3. `cd backend && .venv/bin/python -c "from app.safety import voice_guard as v; print(v.statement_hash())"`,
   and add `"<version>": "<hash>"` to `PINNED` in
   `backend/tests/safety/test_statement_version.py`. Never edit an old line.
4. Run the gate. `test_statement_version.py` fails if the words changed and
   the version did not.

Bump `AVE_TERMS_VERSION` too when the Terms change (SETUP_NEEDED.md, item 8).

### Regions

Cloning opens in India first (open decision 5). Today that is enforced by
who has the flag: an admin turns `voices.cloning_verified` on per person, for
people in India. The EU and the US wait for V2 (biometric consent wording, a real
watermark). A country gate is V2 work (as-built spec, step 8).
