# Good morning: launch hardening (overnight run 2)

Branch **`overnight/launch-hardening`**, cut from main `dc292d7` (the projects
plan was already merged). Worktree: `../AgenticVideoEditor-launch`. Nothing is
pushed and main is untouched. Item details: `PROGRESS.md` (top table).
Every choice made without you: `DECISIONS.md` (top section).

Your second message ("Overnight run 2") arrived after I had started on the
first launch list. The work already done for it (migration 0030 and launch
flags) is item **1a**; everything else follows run 2's numbering. Items 6, 7,
8 and 9 were built by subagents on their own branches and cherry-picked in
order; I reviewed, integrated and re-tested them.

**State at the end:** every item 0 to 11 shipped (gaps below). Three full runs in a row
of `make launch-check` on the final code: backend **1637 passed, 10 skipped** each run;
vitest **492 passed** each run; build and lint clean; Playwright **43 passed** in three
runs after one fix (two e2e mocks lacked the new `projects.check` flag). Migrations
0030 to 0034 up, down and up on a copy of your live DB: identical row counts. The backend
suite also ran on a local Postgres 16: 1627 passed, and the 2 failures were fixed
(both tests read the SQLite file directly). The env step fails as it should: no
production secrets exist yet. **$0 spent** on vendors.

---

## 1. What shipped

| # | What | Commit |
|---|---|---|
| 1a | `workspace_id` on every user table (0030, defaults by trigger to the owner's workspace); `launch.*` flags, settable for everyone | `bdd6f7a` |
| 0 | Your MORNING decisions: Bring up to date shows the batch gate; sync / role change / line move on an Approved video asks once ("Change anyway"); batch gates say "N approved videos will return to Draft"; review links move only Draft and Changes asked; abuse_report kind hidden from non-admins; Bin moved to Home's sidebar footer; plan credits lapse at month end, top-ups after 12 months; prices in `backend/app/billing/prices.py` | `e26f544` |
| 1 | Per-member scoping: a user in another workspace gets 404 on every route (one test per route, 139 routes); Reviewers read only what was shared and cannot write (a test per write route); Editors cannot touch billing or members (a test per route); notices to the member who started the work, spend alerts to them and the owner | `311b672` |
| 2 | Security: signed expiring media URLs; uploads and link imports sniffed, 2 GB and 10 minutes; per-person rate limits; production fail-fast on secrets; tight CORS; no stack traces; security headers (webhook signatures came with item 7) | `5face52` |
| 3 | Spend protection: global day cap and an admin kill switch on every paid path, friendly banner, Admin "Spend today"; credits and ceilings on uploads, imports, A2, D2, batch starts | `bdb3ef5` |
| 4 | Reliability: stuck jobs failed with a reason (tested); one idempotency key across retries (at most 2); `/ready`; backup and restore scripts, tested on a live DB copy; `OPS.md` | `90494d7` |
| 5 | Accounts: email and password sign-up, verification, password reset, change email; Terms version and time stored; invite-only mode; a deleted account made again gets the sample again | `f91bdaf` |
| 6 | Postgres ready: `DATABASE_URL`, dialect-aware migrations, RLS policies (0034), full suite run on a local Postgres 16 | `9658414` |
| 7 | Stripe, Razorpay (checkout/orders, signed webhooks, refunds), Resend, Sentry; real only with keys; all HTTP mocked in tests | `ae03f2a` |
| 8 | Deploy kit: Dockerfiles (backend, worker, frontend), `docker-compose.yml` with Postgres and Caddy, `.env.example` (tested to list every variable), `DEPLOY.md` | `85e9c6f` |
| 9 | 9a takes heard by Whisper for the word check; 9b no English master context for language versions (setting); 9c OpenCV declared, libass detected, clear message; 9d FTS5 search; 9e tour tips for consent and withdraw | `b075860` `1970306` `510917f` `49176c9` `75f09ea` |
| 10 | `AVE_LAUNCH_PROFILE=public`; A2 split into `projects.check`; per-person feature switches on the Admin page | `c0d2751` |
| 11 | Flaky tests steadied; `make launch-check`; Postgres-only test fixes; backup scripts in the image | `d3e0dfe` `a4f0762` `d7e8a2a` |

## 2. Gaps (half done, skipped, or untested)

- **Docker images were never built**: Docker is not installed here. The Dockerfiles, compose file, nginx config and Caddyfile are written and reviewed, not run. First thing on the VM: `docker compose build`.
- **No real vendor was called**, and the optional end-of-night smoke run was not done (no keys in the worktree; nothing spent). Untested for real: Whisper hearing a mispronounced take (9a), Hindi takes without English context (9b), libass captions (9c), Stripe/Razorpay/Resend/Sentry against their real APIs.
- **Postgres**: tested on a local pgserver (PostgreSQL 16.2) only. RLS policies exist but are bypassed (the app still scopes in code); enforcing them is in SETUP_NEEDED.md. Home search reads every row on Postgres (no tsvector index yet). No tool copies SQLite data into Postgres.
- **Billing UI** does not yet redirect to Stripe Checkout or open Razorpay's checkout when real keys are set (the API returns the checkout; the page still assumes test mode). Refunds made in the Stripe or Razorpay dashboards are not picked up.
- **Rate limits and the day-cap state live in one process** (in memory / one database). Fine for one server; a second server needs Redis.
- **Google sign-up shows no Terms checkbox**: password sign-ups store the Terms version and time; Google sign-ups do not yet.
- **The worker container** runs the purge and (optionally) digests; jobs still run inside the API process. Turning the API's own digest scheduler off needs a small switch (so digests are not sent twice if `AVE_WORKER_DIGESTS=1`).
- **Media token renewal** reloads a playing video once per 11 hours (the address changes).
- Existing Reviewers (before tonight) see nothing until you share a project with them on the Members page.

## 3. Decisions to confirm

All are in `DECISIONS.md` with how to undo. The ones that change behaviour or need a business call:

- **Signed media**: one token per owner (not per file), valid 12 hours, in every media address; a leaked address works for at most 12 hours.
- **Upload limits**: 10 minutes and 2 GB a video; recordings 100 MB; AVI accepted.
- **Rate limits**: turns 30 / 10 min, voicing outside a turn 20 / 10 min, uploads 30 / hour, imports 10 / hour, sign-in 20 / 10 min per address, comments 30 / 10 min, abuse reports 5 / hour per address.
- **Day cap $50** across all users (AVE_DAILY_SPEND_CAP_USD), pausing until 00:00 UTC; a running turn stops at its next paid step, not at the end of the turn.
- **Credits**: spend comes from the grant that lapses soonest; the trial never lapses; existing accounts may see some October credits lapse on 1 Nov under the new rule. Trial stays 5 credits (`prices.py`). Prices are placeholders.
- **Line moves on Approved videos**: shift and the arrangement now also drop an Approved video to Draft (they did not before), after the one question.
- **Bring up to date** always uses the batch gate, even with Phase B off for the public.
- **Reviewers** see only shared projects or videos; account-wide pages answer 404 to them.
- **Accounts**: owner id `acct:<id>` (stable across address changes); passwords 10+ characters; verify 48 h, reset 1 h, change-email 24 h links; a password reset signs out every other session; signing up with a taken address emails its owner and tells the caller nothing.
- **Invite-only**: a waiting workspace invite for the address, or a code from AVE_INVITE_CODES; people who signed in before are never refused.
- **Launch profile** (public): A1, A3, G1 to G4, G6 to G8 on; B, C, D, A2 off. That means **no Bin, templates, pins or archive for the public** (D is off). Say if the Bin should be on.
- **Production** requires `AVE_AUTH` on, both signing secrets (32+ chars), https public URL, the three vendor keys and a real email provider.
- From the previous night, still yours: GST details, consent-record retention (7 years), data-export contents.

## 4. How to test it in the app

Use a copy of your data, never the main checkout's `backend/var/ave.db`:

```sh
L="$HOME/Documents/Ashish - Personal/Ashish - Personal Experimentation/AgenticVideoEditor-launch"
MAIN="$HOME/Documents/Ashish - Personal/Ashish - Personal Experimentation/AgenticVideoEditor"
TRY="$HOME/ave-try2"; mkdir -p "$TRY"
sqlite3 "$MAIN/backend/var/ave.db" ".backup '$TRY/ave.db'"; cp -R "$MAIN/backend/var/artifacts" "$TRY/artifacts"
# Stop the main checkout's uvicorn (8000) and Vite (5173) first; the Vite proxy points at 8000.
cd "$L/backend" && AVE_DATA_DIR="$TRY" PYTHONPATH="$L/backend" "$MAIN/backend/.venv/bin/uvicorn" app.api.main:app --port 8000
cd "$L/frontend" && npm run dev        # second terminal
```

Migrations 0030 to 0034 apply on first start (they were proven up, down and up on a copy of your live DB: 47 tables, 712 rows identical).

- **0 Decisions**: on a project with an older-brief video, press Bring up to date: the gate shows videos, lines, cost; Not yet drops it, Go runs it. Move a video to Approved, then drag a kept line or change its role: "Change anyway". Home: the Bin link is at the foot of the sidebar. Billing: credits line says what lapsed.
- **1 Scoping**: with sign-in on (see 5), invite someone as a Reviewer and tick one project; they see only it. Members page: Change what a Reviewer sees.
- **2 Security**: open a video, copy a media address from the network tab, remove `mt=`: 403. Upload a `.mp4` that is really a PNG: "That file is not a video we can take...".
- **3 Spend**: Admin page (`#admin`): Spend today, Pause paid work; reload any page: the Paused notice. Resume.
- **4 Reliability**: `curl localhost:8000/ready`. Backup: `scripts/backup.sh "$TRY" /tmp/ave-backups`, restore into an empty folder with `scripts/restore.sh <folder> /tmp/ave-restored`.
- **5 Accounts**: start the backend with `AVE_AUTH=accounts AVE_SESSION_SECRET=$(openssl rand -hex 32)`. Make an account on the login page; the confirm email is in the `notify_outbox` table of your copy (`sqlite3 "$TRY/ave.db" "select body from notify_outbox order by id desc limit 1"`). Open the link, sign in, Forgot your password, Settings > Change email. Invite-only: `python -m app.flags set launch.invite_only on --db "$TRY/ave.db"`.
- **6 Postgres**: `pip install 'psycopg[binary]' pgserver` into the venv, then see SETUP_NEEDED.md "Testing on Postgres".
- **7 Providers**: nothing visible without keys (test mode as before). With Stripe test keys, `POST /billing/topup` returns a checkout URL.
- **9**: project words with a pronunciation, then a take (needs a Whisper key to really hear it); a tour tip in the consent sheet's read-aloud step; Home search.
- **10 Profile**: start with `AVE_LAUNCH_PROFILE=public` and sign in as a new account: no batch, board, Bin or project check; Admin page > Features for one person turns them on.
- **11**: `make launch-check SKIP_ENV=1 VENV="$MAIN/backend/.venv" DB="$TRY/ave.db"`.

## 5. What you must set up (summary of SETUP_NEEDED.md)

- **Hosting**: one VM with Docker Compose; follow DEPLOY.md (Caddy for HTTPS, firewall, `.env` mode 600). Nothing was created.
- **Domain**: a domain and an A record to the VM; Caddy takes the certificate.
- **Database**: SQLite on the VM's disk to start; or managed Postgres via `DATABASE_URL`.
- **Storage / backups**: object storage (S3 or B2) and rclone for `/data/backups`; the nightly cron is in DEPLOY.md and OPS.md.
- **Email**: Resend with a verified domain (SPF, DKIM); `AVE_EMAIL_PROVIDER=resend`, `AVE_EMAIL_API_KEY`, `AVE_EMAIL_FROM`. Sign-up depends on it.
- **Error tracking**: a Sentry project, `SENTRY_DSN`.
- **Payments**: Stripe (`AVE_STRIPE_SECRET_KEY`, `AVE_STRIPE_WEBHOOK_SECRET`, webhook `/api/billing/webhooks/stripe`) and/or Razorpay (key id, secret, webhook secret, webhook `/api/billing/webhooks/razorpay`); GST registration and seller details.
- **Production variables**: listed in SETUP_NEEDED.md "For the public launch"; `make launch-check` (without SKIP_ENV) fails until they are all set.
- **Legal**: real Terms, Privacy and Acceptable use text, then bump AVE_TERMS_VERSION.

## 6. LAUNCH BLOCKERS

Anything still unsafe for public users, most serious first:

1. **No production deployment exists yet**, and the images have never been built. Until it runs on the VM with HTTPS and `AVE_ENV=production` passing its checks, nothing here protects real users.
2. **Legal pages are drafts** (Terms, Privacy, Acceptable use). Do not open sign-ups until a lawyer has replaced them. Google sign-ups do not record Terms acceptance yet.
3. **Email provider not set up**: without Resend, nobody can confirm an address or reset a password (production refuses to start without it).
4. **Liveness, public-figure check, watermark and C2PA are still fakes** (G6). Voice cloning's consent proof is a read-aloud sentence that any recording of a second passes. Before public voice cloning: a real liveness/speaker-verification provider, or keep cloning behind invite-only.
5. **Payments are test mode**: the Billing page cannot take real money yet (no redirect to Stripe or Razorpay checkout in the UI). With billing on, people stop at the trial's credits. Either finish the checkout UI or launch with the trial only (and say so).
6. **Off-machine backups** are not configured (scripts and cron exist; the destination does not).
7. **Abuse reports** reach the Admin page and `AVE_TRUST_EMAIL`; someone must watch them from day one.
8. **One server only**: rate limits and the pause state are per process. Do not run two API containers.
9. **Prices and credit amounts are placeholders**; sign them off or keep billing off.
10. **No real smoke run** of the whole flow with real vendors was done tonight (to keep spend at $0). Do one 5-line run on the VM before opening the doors (under $0.50).
