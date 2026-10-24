# Changelog

## 1.0.0-rc1 (2026-10-24)

The first release candidate: everything built from the first commit
(2026-08-07) to the end of overnight run 4. Details per item are in
`PROGRESS.md` and `DECISIONS.md`; the run summaries are in git history
(`git show dc292d7:MORNING.md`, `47ff162:MORNING.md`, `cb29d1d:MORNING.md`).

### The editor (August to October 20)

- Upload a video with consent; Whisper transcribes it; speakers are found and named.
- Edit by the transcript: change, add, remove, shift or move any line, with
  tracked changes, takes, Keep / Hold per line, undo and Revert.
- New lines are voiced with ElevenLabs in a stock, library, designed or cloned
  voice, fitted to the gap by writing and by generation, matched to the room,
  and checked for continuity (prosody, level, identity).
- Voltage is an agent with tools (Claude): it plans the whole video from a
  goal, asks instead of guessing, quotes the cost before paid steps, and ships
  from the chat. A silent clip gets a voice-over from what Voltage sees in the
  picture.
- Picture that flexes: shots, motion and a living hold instead of a frozen frame.
- Mixing by role (voice, bed, effect), loudness targets, ducking, export
  loudness; a real, downloadable MP4.
- One processing model: jobs with live progress over Server-Sent Events,
  render versions, row chips and a status strip.
- The UI: one workspace (monitor, script, Voltage's panel), keyboard first,
  phone layouts, light and dark on shadcn/ui, 44 px targets, live regions.
- Google sign-in, spend recorded and capped per project and per person.
- The bench: a labelled corpus, a seam metric and a gate against a baseline.

### Projects (overnight run 1, merged 2026-10-21)

- A numbered migration runner (up and down), feature flags per owner, workspaces.
- Projects: brief versions, rules (pronunciation, banned words, required
  lines, style), project checks, stages and a board, an activity log.
- Batches: ask about every video at once, batch export with presets, language
  versions that stay in sync with the master.
- Review: signed, expiring share links; a client review page with comments,
  approval and an email digest.
- Reuse: the Bin (30 days), pin, archive, search, templates, learned style.
- Go-live groundwork: roles (Owner, Editor, Reviewer), invites, notifications,
  analytics and an admin page, feedback on takes, error reports, billing and
  trust and safety behind interfaces (fakes until keys are set).

### Launch hardening (overnight run 2, merged 2026-10-22)

- Every route scoped to the member's workspace; Reviewers read only what was
  shared; Editors cannot touch billing or members.
- Security: signed media URLs, upload sniffing and limits, rate limits,
  production fail-fast on missing secrets, tight CORS, security headers.
- Spend protection: a global day cap and a kill switch on every paid path.
- Reliability: stuck jobs fail with a reason, one idempotency key across
  retries, `/api/ready`, tested backup and restore.
- Accounts: email and password sign-up, verification, reset, change email,
  Terms recorded, invite-only mode.
- Postgres support (`DATABASE_URL`, row-level security policies) alongside SQLite.
- Stripe, Razorpay, Resend and Sentry, each real only with its keys.
- The deploy kit: Dockerfiles, `docker-compose.yml` with Postgres and Caddy,
  `.env.example`, DEPLOY.md. Whisper checks takes; FTS5 search.
- The public launch profile and `make launch-check`.

### Launch rehearsal (overnight run 3, 2026-10-23)

- Launch blockers fixed: Billing follows a real checkout, Google sign-ups
  record the Terms, voice cloning closed to the public until real liveness, a
  second API process refuses to start, digests sent from one place.
- The shipped stack run locally with mocked vendors (`scripts/rehearsal.sh`)
  and three journeys (owner, Reviewer, Editor). Fixed: an Editor's Delete
  account deleted the owner's account (P0), lost invites, a Reviewer's
  unplayable video.
- Load test to 75 users (LOAD.md): uploads no longer block the API; worker
  counts set from the results. Safe for about 30 people at once on one VM.
- Six failure drills (OPS.md): crash refunds, Postgres reconnects, a full disk
  refuses new work with a sentence, timeouts read as sentences.
- Security pass (SECURITY.md): dependency audit, SSRF guard, one CSRF check,
  path traversal and zip fixes, forged X-Forwarded-For.
- COSTS.md (prices in code unchanged), public screens polished and checked
  with axe, the landing page and waitlist, HTML emails, admin tools with an
  audit trail (RUNBOOK.md), Send feedback.

### Cost and staging (overnight run 4, 2026-10-24)

- Cost evals (`backend/evals`): six scenarios scored by WER, SIM-o, UTMOS,
  duration error, plan quality and cost. How-do-I questions answered by a
  small model (97% cheaper); checks on the small model; takes stop at the
  first that fits; a clip's transcript and readings kept by its hash, so a
  re-upload is free; a shorter opening view on later turns.
- Consent-verified cloning (behind `voices.cloning_verified`, off): the
  speaker reads a random phrase aloud; words, length and voice similarity
  decide, and borderline checks go to an admin review queue.
- Add and Export never render inside a request: both are jobs in the status
  strip. The export loudness pass is about 4x cheaper with the same result,
  so a 60 s render takes about 7 s on a 4 vCPU server.
- Sign-in limited per account and address (an office can sign up together);
  receipts, tax invoices with a PDF and the account-deleted email are sent;
  signed-out pages make no calls that need a session.
- Beta kit: the Beta stamp, Known issues, the beta invite, a beta cohort
  (batch and review on, 10 credits), a welcome checklist, three questions
  after a first export and an admin Beta view.
- Legal drafts v2 for counsel and a sub-processors page.
- Production setup kit: `scripts/provision.sh` for a fresh Ubuntu 24.04 VM
  (Docker, firewall, security updates, fail2ban, swap, log rotation, the
  nightly off-site backup with rclone), `docs/ops/monitoring.md` (Sentry,
  uptime, disk, backup), and one command each to deploy, migrate and roll
  back (`scripts/deploy.sh`, `migrate.sh`, `rollback.sh`; images tagged by git
  sha; migrations only add, so a rollback keeps the schema).

### Known before 1.0.0

See `MORNING.md` (launch blockers) and `SETUP_NEEDED.md`: real vendor checks,
the email provider, Sentry, billing and trust and safety keys, the VM, DNS
and the off-site bucket are still to set up. Prices are placeholders.
