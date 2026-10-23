# Good morning: launch rehearsal (overnight run 3)

Branch **`overnight/launch-rehearsal`**, cut from main `47ff162` (launch hardening was
merged). Worktree: `../AgenticVideoEditor-rehearsal`. Nothing is pushed and main is
untouched. Items 5, 8, 9, 10, 11 and 7 were built by subagents on their own branches
and cherry-picked; I resolved the conflicts, re-tested and integrated them. Item
details: `PROGRESS.md` (top table). Every choice made without you: `DECISIONS.md`
(top section). Last night's MORNING is in git history (`git show 47ff162:MORNING.md`).

**State at the end:** every item 1 to 11 shipped. Final `make launch-check SKIP_ENV=1`
on the head: see the last line of this file. The three rehearsal journeys (owner,
Reviewer, Editor) passed **4 runs in a row** against the docker stack built from the
final code. **$0 spent**: every vendor was mocked; no accounts, keys, servers or DNS.

Setup I did on this Mac: Docker was not installed, so I installed **Colima, the Docker
CLI, compose, buildx, k6 and gitleaks** with Homebrew (local tools only;
`brew uninstall colima docker docker-compose docker-buildx k6 gitleaks` and
`colima delete` undo it). The Colima VM is 4 CPUs, 6 GB, 60 GB; `colima stop` frees it.

---

## 1. What shipped

| # | What | Commits |
|---|---|---|
| 1 | Launch blockers fixable in code: Billing follows a real Stripe/Razorpay checkout; Google sign-ups record the Terms; voice cloning closed for the public until real liveness (`voices.cloning`); a second API process refuses to start; digests from one place. Building the images for the first time found three deploy bugs (no psycopg in the image, compose refusing to run without the Caddy domain, 520 MB proxy caps under a 2 GB upload limit), all fixed | `9fd5483` |
| 2 | Production rehearsal: the compose stack (app, worker, web, Postgres) with the public profile, password accounts and mocked vendors (`scripts/rehearsal.sh`); Playwright journeys for owner, Reviewer, Editor, videos in `docs/rehearsal/`. Found a **P0: an Editor's Delete account deleted the workspace owner's account and every video** (fixed), plus lost invites, a Reviewer's unplayable video, Billing errors for members | `e890153` `139b825` |
| 3 | Load test (k6, up to 75 users): one upload froze the whole API (fixed); worker counts in config with tested defaults; LOAD.md | `4e04a6d` |
| 4 | Failure drills (six): a crash mid-call kept its charge (fixed), Postgres restarts needed an app restart (fixed), a full disk refused nothing (fixed), Claude timeouts showed SDK text (fixed); OPS.md | `3504d70` |
| 5 | Security: dependency audit (certifi critical, 6 high in build tools; both audits now 0), SSRF guard with rebinding defence, one CSRF check for all 151 writes, path traversal via an email owner id, zip-slip/zip-bomb, reference files served as pages; forged X-Forwarded-For dodged rate limits (fixed); secret scan clean; SECURITY.md | `90a1517` `8fb92f5` `360001f` `f4c5d20` `b06c70b` `05b1e85` |
| 6 | Cost and pricing sheet: COSTS.md (prices in code unchanged) | `489f3fb` |
| 7 | Public polish: every public screen walked, axe 0 serious/critical (92 checks, light, dark, 375 px), 44 px touch targets, Reviewers no longer see editing controls, lazy-loaded flagged parts (first-load JS 913 to 774 kB) | `6b52088` `bfdb0db` `419dffb` `ff81d53` `82300d8` `c89b4f3` `523699a` |
| 8 | Landing page at `/` (demo, 3 steps, prices from `GET /pricing`, FAQ, legal links, empty slots for real quotes and logos), Request access waitlist (0035) with Send invite on the Admin page | `3450cad` `3a9d704` `86ad6b4` |
| 9 | Emails: Volt-style HTML plus plain text for every email, `#admin/emails` preview | `bab101b` `b0af311` |
| 10 | Admin tools: find a person, their workspace, spend, credits, jobs, errors; grant credits, refund, suspend/unsuspend, kill switch, a flag for one owner; append-only audit trail (0036); admins named by email; RUNBOOK.md | `5042c0a` |
| 11 | Send feedback (help menu, optional screenshot, route/video/job attached), admin list with status (0037) | `0c9cd0b` |

Docs: `PROGRESS.md`, `DECISIONS.md` commits `fde3516`, `beb2666`; this file is the last commit.

## 2. Load and drills in brief (LOAD.md, OPS.md)

**Safe user count for one VM (4 vCPU): 30 people working at the same moment with no
slowdown; 50 with no errors but voicing slows (renders queue); 75 breaks.** At a
typical 5 to 10% of accounts active at once, 30 active is roughly 300 to 600 accounts:
watch `/api/health` jobs.queued rather than trusting that ratio.

- **First bottleneck: one upload froze every request.** `POST /videos` did the probe,
  store and transcription on the event loop; with real Whisper, one upload would stall
  everyone for seconds to minutes. Fixed for all five upload routes (test proves it).
- **Then 4 job threads** (turns queued 2 minutes at 50 users) and **40 HTTP threads**
  (Add renders inside the request and starved sign-in). Now AVE_JOB_WORKERS=16,
  AVE_WORK_WORKERS=4, AVE_HTTP_THREADS=100 by default.
- 30 users (run 6): every read under 0.5 s at p95, turn proposal 4 s, 0 failures.
  50 users (run 8): 0 failed requests in 7,811, reads under 2.2 s at p95, turn 6 s p50
  / 37 s p95, go-ahead with preview 28 s p50 but up to 6 min p95 (render queue).
- Caveat: renders were a 2.3 s clip plus a sleep; measure one real 60 s render on the VM.

**Drills (all six pass after the fixes):**

| Drill | Result |
|---|---|
| Kill the API mid-voicing (a real crash) | Docker restarts it in 3 s; the job says "The server restarted while this was running. Try again."; **the charge for the unfinished take is now refunded at start** (before: kept, so a retry paid twice) |
| Kill the worker | No user effect (jobs run in the API) |
| Restart Postgres | **Now reconnects by itself** (before: every request would fail until the app restarted); 503 with a sentence for the few seconds it is down |
| ElevenLabs 500s | Two retries, clear failure, everything refunded |
| ElevenLabs and Claude time out | Clear failure, nothing charged; Claude's timeout now reads as a sentence instead of SDK text with a docs link |
| Disk at 95% | **Uploads and renders now refuse with a sentence (507)**, reads and downloads keep working, freeing space reopens them (before: nothing refused until "No space left") |

Learned: `docker kill` is a manual stop, not a crash, so the restart policy does not
bring the container back; and a load test on the same database trips the $50 day cap
(every paid step paused, correctly).

## 3. Pricing (COSTS.md; nothing in code changed)

Vendor cost (typical): one-line fix about $0.13, a 5-line rewrite about $0.33, a 60 s
new voice-over about $0.75, a 60 s clone voice-over about $1.40, a 60 s language
version about $1.10, an export $0 (compute only). Real turns on the live ledger
average $0.47 (Claude is half to two thirds of every scenario).

To keep credits at **2.5x vendor cost after payment fees and 18% GST**:

| Item | Credits | Proposed USD | Proposed INR before GST | INR with GST | Today USD | Today INR | Margin today |
|---|---|---|---|---|---|---|---|
| One credit | 1 | $2.62 | Rs 216 | Rs 255 | $1.20 | Rs 101 | 1.1x |
| Top-up 10 | 10 | $26.46 | Rs 2,160 | Rs 2,549 | $12 | Rs 1,008 | 1.12x / 1.17x |
| Top-up 25 | 25 | $65.69 | Rs 5,401 | Rs 6,373 | $30 | Rs 2,520 | 1.14x / 1.17x |
| Top-up 50 | 50 | $131.07 | Rs 10,801 | Rs 12,745 | $60 | Rs 5,040 | 1.14x / 1.17x |
| Starter, a month | 15 | $39.54 | Rs 3,240 | Rs 3,824 | $19 | Rs 1,599 | 1.19x / 1.23x |
| Studio, a month | 50 | $131.07 | Rs 10,801 | Rs 12,745 | $59 | Rs 4,999 | 1.12x / 1.16x |
| Agency, a month | 160 | $418.72 | Rs 34,563 | Rs 40,784 | $179 | Rs 14,999 | 1.07x / 1.09x |

**Every placeholder price today is near cost (1.07x to 1.23x).** Assumptions to check:
Opus 5.5 is charged at the code's fallback $5/$25 per million tokens (it is not a key in
`usage.py`); every line is voiced 3 times; Stripe 4.4% + $0.30 and Razorpay 2% + GST on
the fee are my estimates.

## 4. Decisions to confirm

All are in `DECISIONS.md` with how to undo. The ones that change behaviour or need a call:

- **Voice cloning is closed for the public** (`voices.cloning` off in the public profile) until a real liveness check exists; Describe a voice stays open. Turn it on per person on the Admin page.
- **Google sign-up Terms**: a "continuing accepts the Terms" line under the button, not a checkbox (a checkbox would stop every returning user). Ask your lawyer if a checkbox is needed.
- **Capacity defaults**: 16 job threads, 4 render threads, 100 HTTP threads.
- **Disk guard** at 95% (AVE_DISK_FULL_PCT) refuses uploads and renders only.
- **Reviewers**: editing controls hidden; they may delete their own account; they cannot comment in the public profile (`projects.review` is off). Say if Reviewers should comment at launch.
- **Landing**: the Request access form shows only with invite-only on; quote/logo slots appear in dev builds only; sign out lands on the landing page.
- **Waitlist invites never expire**; they admit the address while invite-only is on.
- **Emails**: receipts, invoices and the account-deleted email have templates and previews but **nothing sends them yet** (nothing did before). For Indian GST invoices you may want the invoice emailed.
- **Admins** may be named by email in AVE_ADMIN_OWNERS; admins cannot be suspended from the page; audit rows cannot be changed or deleted.
- **One CSRF middleware** for all writes; SSRF allows any public address after a redirect; owner emails must be plain addresses.
- **Prices**: yours (COSTS.md section 6).

## 5. How to test it

```sh
R="$HOME/Documents/Ashish - Personal/Ashish - Personal Experimentation/AgenticVideoEditor-rehearsal"
cd "$R"
colima start                                   # if the VM is stopped
scripts/rehearsal.sh up                        # the whole stack, mocked vendors, Postgres: http://localhost:8080
cd frontend && npx playwright test -c playwright.rehearsal.config.ts     # the three journeys
```

- Sign up on http://localhost:8080 (signed out you first see the landing page); the
  confirm link is in the dev outbox: `scripts/rehearsal.sh sql "select body from notify_outbox order by id desc limit 1"`.
- Admin: sign up as `admin@rehearsal.test` (AVE_ADMIN_OWNERS in `deploy/rehearsal/rehearsal.env`), then `#admin`: People, Waitlist, Emails, Beta feedback, Audit trail, Spend today.
- A turn proposes "Fresh every morning." (the mock Claude); Add it, Export, Billing top-up (test mode), Members invite.
- Load test: `RH_NAME=voltage-load RH_PORT=8090 scripts/rehearsal.sh up`, `tools/load/seed.sh 55 > users.json`, then `k6 run -e BASE=http://localhost:8090 -e USERS=users.json tools/load/voltage.js` (LOAD.md "How it was run").
- Drills: `python3 tools/drills/drill.py all` (against voltage-load on 8090; set `AVE_DAILY_SPEND_CAP_USD=none` first).
- Gate: `make launch-check SKIP_ENV=1 VENV="<main checkout>/backend/.venv" DB=<a copy of ave.db>`.
- The front end's lockfile changed (security bumps): run `npm ci` in `frontend/` of any checkout you use.
- `scripts/rehearsal.sh reset` deletes the stack's data; `colima stop` frees the memory.

## 6. What you must set up (beyond last night's list, which still stands)

- **A VM** (4 vCPU / 8 GB is the tested size), a **domain**, and `docker compose up -d --build` with `COMPOSE_PROFILES=https` (DEPLOY.md). The images now build and run; they were rehearsed here.
- **Resend** with a verified domain (every email template is ready).
- **Stripe and/or Razorpay** live keys and webhooks; one real test purchase on the VM. The Billing page now redirects to Stripe Checkout and opens Razorpay.
- **Off-machine backups** (rclone to object storage).
- **Sentry** DSN.
- **Prices** in `backend/app/billing/prices.py` (COSTS.md), and add `claude-opus-5-5` to the price table in `backend/app/usage.py` with its real list price.
- **Legal**: real Terms, Privacy, Acceptable use (the pages still say draft), then bump AVE_TERMS_VERSION. A real support address for the account-deleted email.
- **A real sample clip** for the landing demo and the new-user sample (the bundled one says "placeholder picture").
- Someone to watch abuse reports and beta feedback on the Admin page from day one (RUNBOOK.md).

## 7. LAUNCH BLOCKERS (refreshed)

Fixed tonight and off the list: images never built (built and rehearsed); Google
sign-ups not recording Terms; voice cloning on fake liveness (closed for the public);
no checkout UI; two API processes (now refused); the P0 member account deletion; one
upload freezing the API; crash charges; Postgres restart; full disk; forged
X-Forwarded-For.

Still unsafe for public users, most serious first:

1. **No production deployment exists.** The stack runs on this laptop only. Until it runs on the VM with HTTPS and `AVE_ENV=production` passing its checks (`make launch-check` without SKIP_ENV), nothing here protects real users.
2. **Legal pages are drafts.** Do not open sign-ups until a lawyer replaces them.
3. **No email provider.** Without Resend nobody can confirm an address or reset a password (production refuses to start without it).
4. **Prices sell at about cost** (1.07x to 1.23x of vendor spend). Set them (COSTS.md) or keep billing to the free trial.
5. **Payments are untested against the real providers** (code, redirect and webhooks are written and mocked). One real test-mode purchase per provider on the VM.
6. **Off-machine backups** are not configured.
7. **No real end-to-end run with real vendors.** Do one 5-line run on the VM (under $0.50) and time one real 60 s render: the safe user count assumes renders of a few seconds.
8. **The sample video is a placeholder** every visitor sees on the landing page.
9. **Abuse reports and beta feedback** need a person watching (RUNBOOK.md).

Not blockers, worth knowing: the sign-in limit (20 per 10 minutes per address) could
stop an office behind one NAT signing up together; Reviewers cannot comment in the
public profile; signed-out pages log a few harmless 401s in the console; Add renders
inside the request (fine for 30 users; making it a job is the next capacity step).

---

Final gate on `beb2666` (the code in this branch; this file and the re-recorded videos came after): `make launch-check SKIP_ENV=1` all steps passed: backend **2032 passed**, 10 skipped; vitest **520 passed**; build and lint clean; Playwright **140 passed** (48 before tonight plus 92 axe checks); migrations up/down/up on a copy of your live DB ok; em dash check ok. The env step is skipped on this laptop (no production secrets), as last night.
