# Good morning: cost and staging (overnight run 4)

Branch `overnight/cost-and-staging`, cut from main `cb29d1d` (run 3 merged). Worktree
`../AgenticVideoEditor-cost`. Not pushed; main untouched; tag `1.0.0-rc1` on this branch
only (not pushed). Run 3's summary: `git show cb29d1d:MORNING.md`.

In one breath:
- **Cost per turn did not fall 40%.** Question turns are 97% cheaper and re-uploads are free, but the average fresh turn stayed at about $0.22, and one run per scenario turned out to be inside the noise.
- **Consent-verified cloning is built** behind `voices.cloning_verified`, off for everyone.
- **Add and Export are jobs now, so no request renders.** A real 60 s render takes about 7 s on the 4 vCPU VM after a 4x cheaper loudness pass, and the safe count stays 30 people, now for 60 s videos too.
- **No staging:** there is no `deploy/staging.env`, so item 7 did not run.
- **Real spend: $3.57**, all of it in item 1, under the $4 stop.
- **Your OpenAI key had expired.** You replaced it during the run; the live app reloaded with it and OpenAI accepts it.

## 1. What shipped

Each item was built on its own branch (`cost/item<N>`, worktrees `../AgenticVideoEditor-c<N>`)
and cherry-picked here, then gated with `make launch-check SKIP_ENV=1` on this branch.

| # | Item | Commits |
|---|---|---|
| 1 | Evals, then cost per turn | 72a9346 (evals), 88e2b94 (baseline), 66e6688 (1a caching), 34e9a5a, 4175978 (1b Haiku), e674d58 (1c takes), 916a108 (1d content cache, 0038), b65e5e8 (1e opening view), e425de1 (after run, COSTS.md section 8) |
| 2 | Consent-verified cloning | ad71ff3 (threshold study), ecb2ce2 (gate, 0039, flag), 238c59a (review queue), a4a25f1 (UI, Help, copy) |
| 3 | Capacity | cbd2d73 (Add is a job), a42401f (60 s render measured), 38f9068 (loudness pass 4x cheaper), 58e97af (Export is a job) |
| 4 | Fixes from run 3 | df2845d (sign-in per account and address), ad0f414 (receipt, invoice PDF, account deleted emails), e1e3a16 (no 401s signed out) |
| 5 | Production setup kit | ba1ffa7 (provision.sh), e4f2809 (deploy, migrate, rollback), 9e0c687 + 92831d6 (CHANGELOG) |
| 6 | Beta kit | bf4b662 (badge, Known issues), 80fc219 (invite email), 6ecf02d (cohort, credits), 237c8d5 (checklist), 0e008b1 (survey, 0042), cd6959c (admin Beta view), 96edb16 + 2e887d3 (Known issues updated) |
| 7 | Staging | not run: no `deploy/staging.env` |
| 8 | Legal drafts v2 | 502ec41 (Terms), 50f5ee9 (Privacy, sub-processors), 61d1832 (Acceptable use) |

## 2. Cost per turn, before and after (COSTS.md section 8)

Real vendors, one fresh upload and one turn per scenario, through the app's ledger.

| Scenario | Before | After (typical) | Scores, before to after |
|---|---|---|---|
| One-line fix | $0.058 | $0.059 | WER 0 to 0, SIM-o 0.63 to 0.52 / 0.62, UTMOS 4.34 to 4.39, duration error 0.11 to 0.18 s, plan 1 to 1 |
| 5-line rewrite | $0.485 | $0.485 | WER 0.03 to 0.24, SIM-o 0.71 to 0.73, UTMOS 4.14 to 3.75, duration error 0.36 to 0.33 s, plan 1 to 1 |
| New voice-over | $0.117 | $0.159 | WER 0 to 0, UTMOS 4.46 to 4.46, duration error 0 to 0, plan 1 to 1 |
| Hinglish line | $0.140 | $0.140 | WER 0.63 to 0.63, SIM-o 0.82 to 0.79, UTMOS 3.95 to 3.97 / 2.95, plan 1 to 1 / 0 |
| Hindi version | $0.453 | not re-run (budget) | WER 0.33, SIM-o 0.84, UTMOS 3.48, duration error 0.40 s |
| Question turn | $0.034 | **$0.001** | plan 1 to 1, help article used |
| **Average** | **$0.215** | **$0.216** | |

What worked:
- **Question turns:** how-do-I questions now go to claude-haiku-5-5, a 97% cut.
- **Re-uploads:** a re-uploaded clip's setup cost fell from $0.03 to $0.06 to $0, because transcripts and readings are kept by the file's hash.
- **Later turns:** their opening view is 65 to 74% smaller.

Why the average didn't move:
- **The levers miss single fresh edits:** caching was already 93% of the agent's input, and most lines needed all three takes.
- **The noise is bigger than the bar:** the same one-line fix cost $0.051 to $0.151 across three identical runs, so a 5% bar needs three or more runs per scenario (about $4.50 a pass).
- **Off behind a flag:** a wider take band (`AVE_TAKE_ACCEPT`) measured worse, so it is off.

Levers left for you (not changed): the ledger prices Opus 5.5 at the $5/$25 fallback. If your bill shows the list price is lower, agent cost is about 30% lower than shown. Other levers are two takes per line instead of three, a lower agent effort, and shorter tool descriptions.

## 3. Pricing at 2.5x (COSTS.md; no price in code changed)

The credit price is unchanged from run 3: **$2.62, or Rs 216 + GST, a credit** keeps 2.5x vendor cost after payment fees and 18% GST. Your current placeholder prices are still at about cost. What each scenario costs a user at that price:

| Scenario | Credits | USD | INR before GST | INR with GST |
|---|---|---|---|---|
| One-line fix (2.3 s) | 0.059 | $0.15 | Rs 13 | Rs 15 |
| 5-line rewrite (13 s) | 0.485 | $1.27 | Rs 105 | Rs 124 |
| New voice-over, one line (6 s) | 0.159 | $0.42 | Rs 34 | Rs 41 |
| Hinglish line (2.3 s) | 0.140 | $0.37 | Rs 30 | Rs 36 |
| Hindi version, 5 lines (13 s) | 0.453 | $1.19 | Rs 98 | Rs 116 |
| Question turn | 0.001 | under $0.01 | under Rs 1 | under Rs 1 |
| Average of the six | 0.216 | $0.57 | Rs 47 | Rs 55 |

These are short eval clips. Run 3's 60 s figures and the live ledger's $0.47 a real turn still stand.

## 4. Cloning thresholds and test results (docs/cloning-consent.md)

The check, in order:
1. The speaker reads a random 8 to 12 word phrase. It is made on the server, single use, and good for 10 minutes.
2. Length: the recording must be at least 4 s.
3. Words: what Whisper hears must match the phrase with WER under 20%.
4. Voice: SIM-o (WavLM, run locally) is compared with the clone's source audio.

| SIM-o | Result |
|---|---|
| 0.92 or more | pass |
| 0.84 to 0.92, or not measurable | admin review queue: approve or reject with a reason, audited, owner notified |
| below 0.84 | did not pass, with what to try |

Each attempt stores the phrase, what was heard, the scores, the deciding rule, the model names and the times (migration 0039).

Test set: 82 local clips, with 125 same-speaker pairs and 3,112 different-speaker pairs. Whisper was mocked, so this cost $0.

| Pairs | Median | Pass | Review | Fail |
|---|---|---|---|---|
| Same speaker (clean, and phone vs clean) | 0.95 to 0.97 | 90 of 97 | 6 | 1 (a phone copy at 0.835) |
| Different speakers | 0.62 | 1.6% | 7.5% | 90.9% |

- **False passes:** every different-speaker pass was two synthetic voices from one engine.
- **One threshold instead of bands:** a single bar at the model card's 0.86 would let 6.6% of strangers through. 0.94 would cut that to 0.6% but send more checks to review.
- **Caveat:** the set is small and mostly synthetic, and only one real person has two clips.
- **Flag:** `voices.cloning_verified` is off for everyone and not in the public profile. Turn it on for one person on Admin, Features. It needs `golive.g6`.

## 5. Render time and the safe user count (LOAD.md)

The test render: 60 s of 1080x1920 at 30 fps, with 4 replaced lines and an 8 s voice-over, through the app's real render path. Two thirds of the time went to the export loudness pass's true-peak check.

| Where | Before | After the cheaper pass (same loudness within 0.05 LU, peak within 0.1 dB) |
|---|---|---|
| Api image, Colima VM, 4 vCPU | 22.0 / 23.0 / 24.5 s | **6.0 / 6.8 / 7.9 s** |
| This laptop | 20.5 / 18.9 s | 5.5 / 5.6 s |

How the safe count follows:
- The VM's 4 render workers do about 34 renders a minute.
- At one render every 2 minutes per active person, with the workers kept under 70% busy, that holds about 48 people.
- So the load-tested **30 people at once with no slowdown** now holds for 60 s videos, with 50 at the edge. A 3 minute video holds about 16.
- Before the fix, the real render would have meant about 10 people.
- Check the `render done ... seconds=` log on the real VM in its first week.

## 6. Staging

**No staging.** There is no `deploy/staging.env`, so nothing was deployed: no journeys there, no real 5-line run, no VM render timing, no off-machine backup check. Item 7's $1 of budget was not spent.

What I ran instead, on this machine:
- **Rollback rehearsal** on a local stack: older build, newer build, migrate, then roll back in 15 s with data intact. A switch is about 15 s of outage.
- **Provision script:** `provision.sh` ran twice in an Ubuntu 24.04 container; the second run reported "no changes".
- **Journeys:** the three journeys on a fresh local stack of this branch were green 3 runs in a row (section 8).

## 7. Decisions to confirm

All are in DECISIONS.md with how to undo them. The ones that need your call:
- **Check model:** it moves from claude-haiku-4-5 to **claude-haiku-5-5** (AVE_CHECK_MODEL). Question turns also run on Haiku 5.5 (AVE_QUESTION_MODEL; empty turns it off).
- **Opus 5.5 rate:** the ledger's rate for Opus 5.5 was left at the fallback. Compare it with your Anthropic bill.
- **Cloning bands:** pass at 0.92, review from 0.84. The flag is off. English phrases only.
- **Beta cohort:** it gets all of `projects.batch` (B1, B2, B3) and all of `projects.review` (C1, C2), because those are phase flags. The 10 credits never lapse. The Beta stamp is always shown in the shell.
- **Sign-in limits:** 20 per 10 minutes per account and address, plus 100 per 10 minutes per address. One account guessed slowly from many addresses is not limited across them.
- **Invoice PDF:** standard fonts only, so it prints "INR", not the rupee sign, and a non-Latin buyer name prints as "?". The HTML email shows the name as typed.
- **Export answers:** `POST /videos/{id}/export` answers 202 with a job when the render isn't made yet. Any outside caller has to follow the job.
- **Rollback:** migrations only add, and a rollback never runs `down`. The firewall also opens 443/udp. provision.sh does not change SSH settings.
- **Legal proposals for counsel:** keep consent records 7 years, anonymised analytics 24 months, error reports 90 days, export zips 7 days. None of this is built.

## 8. How to test it

```sh
R="$HOME/Documents/Ashish - Personal/Ashish - Personal Experimentation/AgenticVideoEditor-cost"
cd "$R"
colima start                                    # if stopped
RH_NAME=voltage-r4 RH_PORT=8086 scripts/rehearsal.sh up
cd frontend && RH_NAME=voltage-r4 RH_PORT=8086 REHEARSAL_URL=http://localhost:8086 npx playwright test -c playwright.rehearsal.config.ts
```

- **Cost evals** (real spend: about $1.50 a pass): run a backend with real keys on a DB copy with a day cap, then `cd backend && python -m evals run --base http://127.0.0.1:8101 --db <copy>/ave.db ...` and `python -m evals compare results/a.json results/b.json`. The usage is in `backend/evals/__main__.py`.
- **Consent check:** turn on `golive.g6` and `voices.cloning_verified` for yourself on Admin, Features. Then try a clone from a speaker. Borderline checks appear under Admin, Consent reviews.
- **Beta:** on Admin, use Beta, Add to beta, or Waitlist, Invite to beta. The invite is in `#admin/emails`. The survey shows after a first export.
- **Emails:** buy a top-up in test mode. The receipt and the invoice with a PDF land in the dev outbox.
- **Render timing:** `tools/load/render_bench.py` (LOAD.md).
- **Deploy kit:** `scripts/deploy.sh <sha>`, `scripts/migrate.sh`, `scripts/rollback.sh` (OPS.md "Deploy, migrate and roll back").

Final gate on `92831d6`, `make launch-check SKIP_ENV=1`: all steps passed.

| Step | Result |
|---|---|
| Backend | 2140 passed, 10 skipped |
| Vitest | 549 passed |
| Build and lint | clean |
| Playwright | 145 passed |
| Migrations | up and down on a copy of your live DB, ok |
| Em dash check | ok |

The rehearsal journeys (owner, Reviewer, Editor) on a fresh stack of this branch, with Postgres, the public profile and mocked vendors, were green **3 runs in a row** (1.4 to 1.6 min a run, against 3.1 to 4.9 min in run 3). They now go through Add and Export as jobs.

## 9. What you must set up

Run 3's list still stands: VM, domain, Resend, Stripe/Razorpay live keys, Sentry, prices, legal, a real sample clip, someone watching reports. New tonight:
- **Staging (optional):** add `deploy/staging.env` with a STAGING host to have the next run deploy there. Provision it with `scripts/provision.sh`.
- **Backups:** an object storage bucket and an rclone remote in `/etc/voltage/backup.env` on the VM (`docs/ops/monitoring.md`, DEPLOY.md).
- **Monitoring:** `SENTRY_DSN`, plus an uptime check on `/api/ready` (`docs/ops/monitoring.md`).
- **Opus 5.5 rate:** check its price in `backend/app/usage.py` against your bill.

## 10. LAUNCH BLOCKERS (refreshed)

Fixed tonight and off the list:
- the expired OpenAI key (you replaced it)
- the sign-in limit behind one office address
- receipts and invoices not emailed
- console 401s
- Add and Export rendering inside the request
- the unknown 60 s render time (now measured at 7 s)
- no deploy, migrate or rollback commands
- no provisioning script

Still unsafe for public users, most serious first:

1. **No production deployment exists.** `scripts/provision.sh` and `deploy.sh` are ready but have never run on a real VM. ufw, swap and the service restarts are untested outside a container.
2. **Legal pages are drafts** (v2 is fuller, for counsel). Don't open sign-ups until a lawyer replaces them.
3. **No email provider.** Without Resend nobody can confirm an address or reset a password, and receipts and invoices can't go out.
4. **Prices sell at about cost.** Set them from COSTS.md, or keep to the free trial.
5. **Payments are untested against the real providers.** Do one real test-mode purchase per provider on the VM.
6. **Off-machine backups aren't configured.** The script and the cron job are ready; they need a bucket.
7. **No real end-to-end run on the VM.** Do one 5-line run with real vendors (under $0.50) and confirm the 7 s render time there.
8. **The sample video is a placeholder.** Every visitor sees it on the landing page.
9. **Abuse reports, consent reviews and beta feedback need a person watching** (RUNBOOK.md, Admin).

Not blockers, worth knowing:
- Cloning stays closed for the public until you turn on `voices.cloning_verified`.
- Reviewers can't comment in the public profile (beta accounts can).
- Consent recordings and some logs have no expiry yet (legal v2 proposes periods).
