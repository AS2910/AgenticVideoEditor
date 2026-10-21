# Good morning: the overnight build

Branch `overnight/projects-plan`, cut from main `217db2d`. Spec: `docs/overnight/PLAN.md`.
Full detail per item: `PROGRESS.md`. Every choice made without you: `DECISIONS.md`.
Nothing is merged. Main is untouched.

---

## 1. What shipped

Every item below is committed and pushed. Flags are on for `local` only (see section 4).
Hashes are the feature commits (the "record the commit in PROGRESS" commits are left out).

| Plan ID | What it is | Commit(s) | Behind flag |
|---|---|---|---|
| M0 | Numbered migration runner with up and down; today's schema as 0001 to 0006 | 68e9c22 | none |
| FLAGS | Feature flags per owner, `GET /me/flags`, `useFlags()` | e4a627a | none |
| WS | Workspaces; `workspace_id` on every user-data table, backfilled | 87c976f | none |
| F2 | Brief versions; each turn records the version it read | a8827ee | none (schema and service) |
| F3 | Project rules store (pronounce, banned, required line, style) in the opening view | c6179f6 | none (schema and service) |
| F5 | Video stage, moved only through `stages.move` | 783b988 | none (schema and service) |
| F7 | Activity log, written in the change's own transaction | b599e70 | none (schema and service) |
| F8 | Soft delete for videos, projects, voices; purge CLI that keeps usage | d0d594a | none (schema and service) |
| A1 | Brief versions on the project page, "Brief changed", Bring up to date | 00b201f | `projects.consistency` |
| A3 | Words: glossary, banned words, required lines, take check | 3785675 | `projects.consistency` |
| A2 | Project check (free rule checks plus a cheap text pass) | 84975d1 | `projects.consistency` |
| F4 | Batch turn engine: one gate, children 3 at a time, shared cap | 8a907ac | `projects.batch` |
| B1 | Batch goals: Ask Voltage about all videos, batch board, Add all that passed | be1269b | `projects.batch` |
| F6 | Signed, revocable, expiring share links | de3d21f | none to open a link; making one needs `projects.batch` or `projects.review` |
| B3 | Batch export: presets, one job per video x preset, zip, share page | 544117e | `projects.batch` |
| B2 | Language sets: versions linked to a master, out of sync, Sync this change | 7b0e7f9, f2a9ccd (fix) | `projects.batch` |
| C1 | Stages and the project board, Activity feed, Approved warning | efab7a0 | `projects.review` |
| TEST | Steadier job waits in backend tests under load | a4d844f | none |
| C2 | Client review link: reviewer page, comments, approve, email digest (fake) | a40b10f | `projects.review` |
| D3 | Bin: restore for 30 days, consent records kept | 5a71edc | `projects.reuse` |
| D4 | Pin, archive, search, sort; archived review links read-only | 1c752fc, 0eda745 (fix) | `projects.reuse` |
| D1 | Project templates and 3 starters | 9727c45 | `projects.reuse` |
| D2 | Learned style: decisions logged, suggestions, "What Voltage has learned" | 805abfc, 5726625 (fix: the pass is a job) | `projects.reuse` |
| G1 | Sample project and upload from a link (Drive, Dropbox) | 4049bb9 | `golive.g1` |
| G2 | Roles (Owner, Editor, Reviewer), invites, per-member spend limits, email sign-in | f34f940 | `golive.g2` |
| G4 | Notification bell, per-kind settings, spend alerts | 8e231fd | `golive.g4` |
| SHELL | Editor header fits with the bell at common widths | 1f8cb7d | none |
| G7 | Analytics events, funnel, internal admin page | d0ebb59 | `golive.g7` |
| G8 | Thumbs up/down on takes and turns; error-reporting hook | ddb42ee | `golive.g8` |
| G3 | Billing behind interfaces: plans, credits, top-ups, GST invoices (fake Stripe and Razorpay) | 8e2bff4 | `golive.g3` |
| G6 | Trust and safety behind interfaces: liveness, public figures, watermark, C2PA, abuse reports, your data | 0338098 | `golive.g6` |

Not built:
- **G5** is not an item in tonight's plan. PLAN.md only names it as where "Postgres and RLS wait". Workspaces are in place, but reads are not yet scoped per member and there is no Postgres. It needs you (hosting) before it can start.
- **G9** does not appear anywhere in PLAN.md, so there was nothing to build.

---

## 2. Half done or skipped, and why

Nothing was skipped and nothing was reverted. These are the known gaps.

**Money and real vendors**
- No real paid smoke runs were done in any phase. $0 was spent on vendors. Every vendor call in tests is mocked, and since the D2 fix `tests/conftest.py` blocks real network calls in tests.
- A2's text pass was never run against the real API. The first real run costs about a cent.
- D2's learned-style pass never ran against a real model. Its quality is untested.
- The check and learned-style model defaults to `claude-haiku-4-5` ($1 in, $5 out per MTok, in `app/usage.py`). Haiku 5.5 is newer, but its price is not in the code, so it was not used.

**Quality limits**
- A3 pronunciation check reads the vendor's word alignment (ElevenLabs aligns the text it was sent). A real mispronunciation can pass. A real check needs a Whisper pass on each take.
- B2: the master's English words still go to ElevenLabs as context for a translated line. If Hindi takes sound anglicised, drop that context for language versions.
- B2: the syllable fit estimate uses the English counter, so Devanagari and Tamil lines are estimated loosely (the fit ladder still measures the real take).
- Burned-in captions use OpenCV (Hershey font). OpenCV is in the venv but is not a declared dependency. Latin script only. Hindi and Tamil captions need an ffmpeg built with libass.
- C2's reviewer watermark is a CSS overlay only, not burned into the file.

**Scale and housekeeping**
- Search is a full scan on every query, no index. Fine today; FTS5 is the next step past a few hundred videos.
- The daily purge is opt-in: `AVE_PURGE_DAILY=1`. Run `python -m app.purge --dry-run` first.
- A voice in the Bin still holds its slot at the vendor until the purge.

**Accounts and links**
- The sample project won't appear for `local` (it already has work). Use a fresh data dir to see it.
- A deleted account's `sample:` record remains in meta, so a re-created account of the same id would not get the sample again.
- Invites can be sent without sign-in, but accepting one needs `AVE_AUTH=google`.
- Share and review links use `AVE_PUBLIC_URL` (default `http://localhost:5173`).
- G4: notifications go to the workspace owner; a member's own notifications wait for G5.

**Trust and safety**
- G6 watermark is metadata only and can be stripped. The C2PA signature is a test HMAC, not a real certificate.
- G6 liveness is fake: it passes any readable recording of a second or more.

**Help and tours**
- No tour tip for the admin page (G7) or for the G6 consent and withdraw flows. Help articles exist for both.

**Tests**
- Flaky under full-suite load: a few Playwright and vitest tests (the `shell.spec` keyboard-focus test, "offers chips from the video", "puts a block on the monitor bar") and `test_board_api` time out now and then. All pass when run alone. DECISIONS.md also records `test_allow_more` and `test_endpoints::test_granting_consent_afterwards_unblocks_generation` as load flakes that pass alone.
- Last full counts recorded (at G6): backend 1243 passed, 5 skipped; vitest 477; tsc clean; oxlint 10 warnings (baseline); Playwright 43 passed.

---

## 3. Decisions to confirm

These change behaviour or need a business or legal call. The full list is in `DECISIONS.md`.

**Behaviour**
- **A1 Bring up to date starts its batch without a gate.** With `projects.batch` on, the button press counts as the yes. B1's Fix in all opens the real gate. Change: `POST /projects/{id}/brief-update` in `backend/app/api/main.py`.
- **Syncing an Approved language version drops it to Draft with no warning.** The Draft rule lives in `ProjectRepository.append_edit` (`backend/app/store/repository.py`), so a role change or a line move on an Approved video also drops it to Draft, without asking. Change: the two lines calling `stages.after_new_edit_in` there.
- **Voltage asks before shipping to an Approved video**, even under Just do it, unless the turn already has your yes. Change: the `ship` tool's stage seam in `backend/app/agent/`.
- **A reviewer link moves a video to In review from any stage**, including Approved and Exported. Change: `review_videos` in `backend/app/api/main.py` and `review_sent_in` in `backend/app/store/stages.py`.
- **Batch reservation is conservative.** A running child holds its whole turn cap; a batch above the project or month ceiling is refused. Change: `backend/app/jobs/batch.py`.
- **Archived means read-only via one middleware** (423 on writes). Export, delete to Bin and Save as template stay open. Change: the D4 middleware in `backend/app/api/main.py`.
- **Server-side analytics are recorded for every owner.** Only the admin page and the browser's `POST /analytics/events` are flagged. Change: `backend/app/analytics.py` `track`.
- **Older backend tests run with `golive.g6` off** via `backend/tests/conftest.py`, so they still test consent without a sentence and exports without a mark. The real default stays on for `local`.
- **A new notification kind `abuse_report` appears in everyone's notification settings**, though only admins get these. Change: `KINDS` in `backend/app/notify/inbox.py`.
- **G4 notifications go to the workspace owner**, not to the member who started the work. Waits for G5.
- **G4 only notifies on failures and on jobs of 60 s or more** (not a single line or a mix). Change: `JOB_NOTICE_SECONDS` in `backend/app/api/main.py`.
- **`projects.brief` is kept as a read-only alias for one release** (F2). Remove it in the release after.
- **The check and learned-style model is `claude-haiku-4-5`.** To switch, set `AVE_CHECK_MODEL` and add its price in `backend/app/usage.py`.
- **Bin sits in the main nav** (before Help), not in Settings. Change: `frontend/src/pages/Shell.tsx`.

**Billing (business sign-off)**
- **Billing applies once an owner has a billing account.** It is made at a new owner's first sign-in or when an owner first opens Billing. Opening Billing as `local` starts the 5-credit trial, and paid steps stop past 5 credits until a test-mode top-up or plan. Use a DB copy to try it.
- **Placeholder prices** in `backend/app/billing/__init__.py`: Starter $19 / ₹1,599 for 15 credits; Studio $59 / ₹4,999 for 50; Agency $179 / ₹14,999 for 160. Top-ups of 10, 25, 50 credits at $1.20 a credit (₹ at 84 to the dollar). One credit is $1 of vendor spend.
- **Plan credits carry over** month to month. A real policy may expire them.
- **Seller state defaults to 29 (Karnataka)** (`AVE_SELLER_STATE`). GST 18% under SAC 998314, CGST+SGST in state, IGST across states, zero-rated exports. Needs an accountant to review GST, the SAC code and invoice numbering (`VLT-YYYYMM-NNNNN`).

**Legal**
- **Consent records are kept 7 years after the purge** by default (`AVE_CONSENT_RETENTION_YEARS`). Legal to confirm.
- **Download my data** lists stored media by address in `media.json` and does not copy the media itself. Legal to confirm that is enough.
- **Deleting a video no longer removes its clone at once** (F8). The purge does that after 30 days; G6's Withdraw consent now does it at once.

---

## 4. How to try it

### Run the branch safely

Use the worktree. Never point it at the main checkout's `backend/var/ave.db`.

The Vite proxy is hard-wired to `127.0.0.1:8000` (`frontend/vite.config.ts`), and your main checkout's uvicorn and Vite are on 8000 and 5173 now. Stop both for the session (Ctrl+C in their terminals), then restart them when done.

```sh
WT="$HOME/Documents/Ashish - Personal/Ashish - Personal Experimentation/AgenticVideoEditor-overnight"
MAIN="$HOME/Documents/Ashish - Personal/Ashish - Personal Experimentation/AgenticVideoEditor"
TRY="$HOME/ave-try"                         # a throwaway data dir

# 1. Copy the live data (sqlite3 .backup includes the WAL safely)
mkdir -p "$TRY"
sqlite3 "$MAIN/backend/var/ave.db" ".backup '$TRY/ave.db'"
cp -R "$MAIN/backend/var/artifacts" "$TRY/artifacts"

# 2. Migrate the COPY (0007 to 0029 apply; status should list 0001 to 0029)
cd "$WT/backend"
PYTHONPATH="$WT/backend" "$MAIN/backend/.venv/bin/python" -m app.store.migrate up --db "$TRY/ave.db"
PYTHONPATH="$WT/backend" "$MAIN/backend/.venv/bin/python" -m app.store.migrate status --db "$TRY/ave.db"

# 3. Backend from the worktree, on the copy
AVE_DATA_DIR="$TRY" PYTHONPATH="$WT/backend" "$MAIN/backend/.venv/bin/uvicorn" app.api.main:app --port 8000

# 4. Front end from the worktree (second terminal)
cd "$WT/frontend" && npm run dev
```

Notes:
- `PYTHONPATH` matters: the shared `.venv` otherwise imports the main checkout's `app`.
- The worktree has no `backend/.env`, so every vendor runs on its free mock ($0). Voltage's turns, the check's text pass and the learned-style pass need `ANTHROPIC_API_KEY` in the backend's shell. Adding keys spends real money.
- Flags: all phase and `golive.*` flags are on for the owners in `AVE_FLAG_OWNERS` (default `local`). With sign-in off you are `local`.
- The admin page needs you in `AVE_ADMIN_OWNERS` (default `local`).
- To see the sample project, start with an empty data dir: `AVE_DATA_DIR="$HOME/ave-fresh"`.

Routes: Home `#home`, a project `#p/<id>`, a video `#v/<id>` (or `#v/<id>@<seconds>`).

### Phase A: keep a campaign consistent

**A1 Brief versions and stale videos**
1. Open a project (`#p/<id>`) that has videos with edits.
2. Change the brief and save. The brief shows "v2 · edited by you".
3. Click History to see the versions and the From/To word diff.
4. Older videos show a "Brief changed" chip (project page, Home, editor header).
5. Press Bring up to date on the "N videos made with an older brief" line.

**A3 Words**
1. On the project page, find the Words section.
2. Add a term with How to say it and a Respell; optionally an Example audio clip.
3. Add a banned word and a required line (for example "T&C apply").
4. In the editor, select a word in the transcript and choose "Add to project words".
5. A take that breaks a rule shows "Breaks a word rule".

**A2 Project check**
1. On the project page, find the Project check panel.
2. Press Rules only (free), or "Check project · about $0.01" (needs a Claude key).
3. On an issue: Fix in this video, Ignore, or Fix in all.
4. A place link opens the editor at that time.

### Phase B: work across many videos

**B1 Batch goals**
1. On the project page, use "Ask Voltage about all videos".
2. Type a goal, tick videos, press Plan it.
3. Read the gate card (videos, lines, cost, time, cap). Press Go, or Not yet.
4. Watch the board rows. Answer a "Waiting on you" row in place.
5. Press "Add all that passed". Each video has its own undo. Cancel the rest stops queued ones.

**B3 Batch export**
1. On the project page, check the Presets card (YouTube, Reels, Feed are seeded).
2. In Export videos, tick videos (Approved are ticked by default) and presets.
3. Press "Export N files". Warnings never block.
4. Use Download all (.zip), or Share link then Copy link.
5. Open the link (`#s/<token>`) in a private window. Then Turn off the link and reload it.

**B2 Language versions**
1. On the project page, press "+ Language versions" under a master card (or in the editor's project menu, "Make language versions…").
2. Pick languages and the voice handling. Read the numbers line. Press Make.
3. The batch board shows the language batch. Add what passed.
4. Ship a new edit on the master. Versions show "Out of sync with master".
5. Press Sync this change on a version.

### Phase C: review and hand-off

**C1 Stages and the board**
1. On the project page, switch Grid to Board beside Videos.
2. Drag a card to a column, or use Move to… from the keyboard.
3. Read the Activity feed in the aside. Show older pages back.
4. Move a video to Approved, then Add it a change in the editor. A warning asks: Cancel or Add anyway.

**C2 Client review link**
1. In the editor, open the project menu and pick "Send for review…" (or use the row under the transcript).
2. Give a name, optional email, days, and leave Allow download off. Press Make the link, then Copy link.
3. Open the link in a private window. Leave a comment at a time, then Ask for changes or Approve vN.
4. Back in the editor: comment dots sit on the scrubber. Reply, Resolve, or Do what the client asked.
5. Emails are not sent. They land in the `notify_outbox` table of your copy.

### Phase D: reuse and housekeeping

**D3 Bin**
1. On Home, delete a video. The confirm says Move to the Bin.
2. Open Bin in the main nav (`#bin`). Filter by kind.
3. Press Restore on a row.

**D4 Pin, archive, search, sort**
1. On Home, press `/` and search a spoken word. A "Said" result opens the editor at that time.
2. Try Sort, Stage and Needs attention above Recent videos.
3. Use Pin to Home on a card or project. It appears under Pinned.
4. On a project page, open ••• and choose Archive project. Edits are refused. Unarchive project brings it back.
5. A review link on an archived project turns watch-only.

**D1 Templates**
1. On a project page, open ••• and choose "Save as template…". Press Save template.
2. Press See templates (`#templates`). Rename, Delete, or New project from this.
3. On Home's new-project card, use Start from to pick Blank, yours, or a starter.

**D2 Learned style**
1. In a project video, Discard a proposal. A small "why?" card offers reasons (Wrong words, Wrong voice, and so on).
2. After every 10 decisions a pass runs (needs a Claude key; it is a `learn` job).
3. On the project page, "What Voltage has learned" shows the suggestion: Not now, Add to brief, or Add as a rule.
4. Remove a learned item to take it out of the next turn.

### Go-live items

**G1 Sample and links**
1. With an empty data dir, Home shows "Sample: bhaji-cam ad" with a Sample stamp.
2. Under the drop zone, use "Or paste a link" with a public Dropbox or Drive link and press Import.

**G2 Members**
1. Open Settings, then Members (`#members`).
2. Under Invite someone, enter an email, pick Editor or Reviewer, optional limit. Press Send invite.
3. Use Copy link on the waiting invite. Accepting needs `AVE_AUTH=google`.

**G4 Notifications**
1. Click the bell in the header. Mark all read.
2. Open Notification settings (`#notifications`) and switch kinds In app or Email.

**G7 Admin**
1. Open `#admin` (Settings side nav, admins only). Read the funnel, take acceptance, cost per exported minute, events.

**G8 Feedback**
1. Press a thumb on a take's facts line or under Voltage's reply. Add a reason or Skip.
2. See votes and reported errors on `#admin`.

**G3 Billing (on a copy only)**
1. Open `#billing`. Note the Test mode stamp and Credits left. This starts the 5-credit trial.
2. Press a Top up pack, or switch plan.
3. Fill Billing details (India shows GSTIN and State). Press Save details.
4. Press View invoice to see the GST split.

**G6 Trust and safety**
1. In the editor, open the Consent sheet. Under "Read this aloud", Record (then Stop and check) or Upload a recording. "Yes, I have it" unlocks after it passes.
2. Under the transcript, use Withdraw consent now.
3. Open `#terms`, `#privacy`, `#acceptable-use`. Use Report misuse, then Send report. It shows on `#admin`.
4. In Settings, Account: Download my data, or Delete my data.
5. Export a video. The file carries a mark and a `.c2pa.json` manifest.

---

## 5. What I need you to set up

### Keys and accounts
- **Stripe** (international, USD): account, `AVE_STRIPE_SECRET_KEY`, `AVE_STRIPE_WEBHOOK_SECRET`, Products and Prices, Checkout, a `checkout.session.completed` webhook. Replace the fake in `backend/app/billing/providers.py`.
- **Razorpay** (India, INR): account with KYC, `AVE_RAZORPAY_KEY_ID`, `AVE_RAZORPAY_KEY_SECRET`, Orders API, a `payment.captured` webhook.
- **Sentry** (or similar): a project and `SENTRY_DSN`, add `sentry-sdk`, wire `SentryReporter` in `backend/app/errors_report.py`.
- **Email provider** (Postmark, Amazon SES or Resend): verified sending domain (SPF, DKIM), API key, `AVE_EMAIL_PROVIDER`, a `send()` in `backend/app/notify/email.py`. Also `AVE_NOTIFY_OWNER_EMAIL` while sign-in is off, and `AVE_TRUST_EMAIL` for abuse reports.
- **Public address**: `AVE_PUBLIC_URL`, and optionally `AVE_SHARE_SECRET` (keep the generated `share_secret` file if you move the data dir).
- **Google sign-in**: `AVE_AUTH=google` with `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `AVE_SESSION_SECRET`. Needed to accept invites.
- **YouTube import** (G1): a Google Cloud OAuth client with YouTube Data API v3 and `youtube.readonly` (needs Google verification).
- **Postgres hosting for G5**, plus RLS. Not started.
- **C2PA**: an X.509 signing certificate from a CA on the C2PA trust list, and `c2patool` or the c2pa SDK.
- **Watermark vendor**: one that survives re-encoding (for example AudioSeal for audio, or Digimarc or Steg.AI).
- **Liveness and public figures**: a speaker-verification provider for `LivenessProvider.verify`; a voice-based public-figure check behind `PublicFigureCheck`.
- **ffmpeg with libass**, for Hindi and Tamil captions (for example `brew install homebrew-ffmpeg/ffmpeg/ffmpeg`).

### Legal
- Terms, Privacy and Acceptable use are placeholders marked "Draft, needs legal review" (`frontend/src/pages/LegalPage.tsx`). A lawyer must write them.
- Confirm the 7-year consent record retention, the data-export contents and the account-deletion wording.
- GST: register, set `AVE_SELLER_NAME`, `AVE_SELLER_GSTIN`, `AVE_SELLER_STATE`; file a LUT for zero-rated exports; have an accountant confirm SAC 998314, invoice numbering and the INR prices.
- Sign off the placeholder prices and credit amounts (section 3).

### Designs
These screens have no board. Each matches the nearest screen (details in `NEEDS_DESIGN.md`):
- A1: brief History panel, "older brief · Bring up to date" line, "Brief changed" chip
- A3: Words section, "Breaks a word rule" marks, Learn a word popover
- A2: Project check panel
- B1: Ask Voltage about all videos, the gate and the batch board
- B3: Presets card, Export videos card, public share page (`#s/<token>`)
- B2: Make language versions dialog, stacked master card and chips
- C1: Grid/Board toggle, the Board, Activity panel, Approved warning
- C2: Send for review dialog, reviewer page, editor comments and scrubber marks
- D3: Bin page
- D4: Home search, sidebar Pinned and Archived, sort and filter controls, archived banner
- D1: Save as template dialog, Start from picker, Templates page
- D2: What Voltage has learned card, the Discard "why?" card
- G1: Import from a link, Sample stamp
- G2: Members page, Invite page, email sign-in on the login page
- G4: the bell and its list, Notifications settings
- G7: Admin page
- G8: thumbs, error card, admin Feedback card
- G3: Billing page and the printable invoice
- G6: Consent sheet with liveness, Withdraw consent now row, policy pages, Report misuse form, Your data, admin Abuse reports card

---

**Your next step:** review this branch and decide on the merge. If yes, merge in a worktree and then fast-forward main, because uvicorn `--reload` serves the main checkout and would pick up a half-merged tree.
