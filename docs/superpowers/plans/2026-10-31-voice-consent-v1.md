# Voice Consent V1: as built

The owner's plan is the run's BRIEF.md (Oct 28, 2026). This file maps each plan item to where it lives in the code and records every place the code's shape differs from the plan's. Each step appends its own section. Everything here is behind `voices.cloning_verified` (off by default, the default owners too); with it off Voltage behaves exactly as before.

## Step 1: migration 0048, voice scope and the five tables

**Shape.** The plan adds columns to a `voices` table. There is none: voices live in JSON lists (`meta` `my_voices:<owner>` and `project_voices:<project>`, a video's `settings.made_voices`, and each speaker's `clone_voice_id` in `videos.speakers`). Those lists are left exactly as they are, and the plan's columns live in a new table beside them, one row per vendor voice:

| Plan (`voices` column) | Code (`voice_records`) |
| --- | --- |
| (the voice) | `voice_id`, the vendor's id, primary key; `owner`, `workspace_id`, `kind` (cloned, recorded, designed, library) |
| `scope` video, library | `scope` |
| `source_video_id` | `source_video_id` |
| `speaker_label` | `speaker_label` (the diarization label, `_` for a whole clip) and `speaker_name` (the name shown) |
| `verified_consent_id` | `verified_consent_id`: a `liveness_attempts.id` of the real gate (method `verified`, status `passed`) |
| `status` active, suspended, withdrawn | `status`, plus `status_reason` and `status_by` (who: the user, an admin, the strike rule, the migration) |
| (new) | `origin` (migration, clone, upload, promote, design), `migration_row` (the plan row that decided it), `vendor_state` (live, delete_queued, deleted), `created_at`, `updated_at` |

A stock (catalogue) voice has no row: the guard treats a voice with no row as not a clone. The five tables are as the plan names them, with `owner` for the plan's `user`, `workspace_id` on all (NULL on `no_go_voices`, one list for the whole platform, which also has no RLS policy), TEXT ids, and JSON text for the list columns:

| Table | Columns beyond the plan's |
| --- | --- |
| `voice_attestations` | `voice_id` may be empty: an attestation can be given for a speaker before their clone exists (cloning needs it first) |
| `export_attestations` | `covers` (the videos and content it confirmed, so a later export of the same edits needs no second click and a changed one does) |
| `line_checks` | `text_hash` (always); `text` only when the verdict is block or review, as the plan says |
| `synthesis_log` | `video_id`; `cost_usd` for the plan's `cost` |
| `no_go_voices` | `reference_embedding` is JSON text (step 5 fills it) |

Code: `backend/app/store/migrations/m0048_voice_consent.py` (`inventory`, `classify`, `counts`, `up`, `down`). On Postgres the five scoped tables get 0034's RLS policy.

**Migrating existing voices** (`classify`, the plan's table):

| Plan row | `migration_row` | Becomes |
| --- | --- | --- |
| Designed or stock voice | `designed_or_stock` | library, active |
| Clone with a passed own-voice check | `clone_verified` | library, `verified_consent_id` set. Only the real gate counts (method `verified`); the 0029 stand-in check passes any recording, so it does not |
| Any other clone | `clone_video` | video scope, `source_video_id` the video it was made from. A source video in the Bin counts as there (the purge deletes its voices as it always did; deleting the voice now would break Restore) |
| Clone whose source video is deleted | `clone_source_deleted` | withdrawn, `vendor_state` delete_queued. The migration never calls the vendor: the guard's `drain_vendor_deletes` deletes queued voices at app start, only for owners with the flag on (step 2) |
| (not in the plan) an uploaded recording of your own voice | `upload` | library, no check linked. These came through the admin-opened `voices.cloning` path. Owner to confirm (DECISIONS.md) |

`up` is additive (no existing row or column changes) and idempotent. `down` drops the six tables, which puts the database back exactly as it was; it refuses while any table holds evidence (an attestation, a confirmation, a line check, a synthesis, a no-go entry, or a voice record made or changed after the migration).

**Dry run.** `python -m app.tools.voice_scope_dry_run --db <db> [--json]` copies the database, applies the steps before 0048, prints the counts per row, then applies 0048 on the copy, checks that every existing table is unchanged and there is one record per voice, runs `down` and checks the copy is back as it was. It never writes the database it is given.

Run on a copy of the live database (main checkout's `backend/var/ave.db`, 2026-10-31, 56 tables compared):

| Row | Count |
| --- | --- |
| Designed or stock voice -> library | 0 |
| Clone with a passed own-voice check -> library | 0 |
| Any other clone -> video scope | 2 (p65, in the Bin, and p66) |
| Clone whose source video is deleted -> withdrawn | 0 |
| Uploaded recording -> library | 1 ("Deewar song", shared into two projects: one record) |

Nothing lost; down restores the copy. The live database's four passed consent checks are all stand-in checks (method empty), so none links a voice.

Tests: `backend/tests/store/test_m0048_voice_consent.py` (every row of the table, nothing lost, down restores, down refuses over evidence, the dry run counts on a copy and leaves the original), plus the runner's own per-step down/up test.

## Step 2: the voice guard

Code: `backend/app/safety/voice_guard.py` (the rules, `VoiceGuard`; the vendor seam, `GuardedVoice`), `backend/app/voice_guard_api.py` (routes), wired in `backend/app/api/main.py` (`voice_guard`, built right after the voice adapter is chosen, which it then wraps). Errors are `VoiceGuardError(code, message, status, **data)`; `failures.classify` reads them as the person's input (their `message`), `failures.http` turns one into an HTTP answer with the structured detail, and the app's handler answers any that reaches it as `{"detail": {"code", "message", ...}}` with its status. Everything is a no-op unless `voices.cloning_verified` is on for the owner (`VoiceGuard.enabled`).

| Plan function | Code | Fails with (status) | Adaptation |
| --- | --- | --- | --- |
| `can_clone(user, video, speaker)` | `can_clone(owner, video_id, speaker_label, speaker_name, reference=None)` | `clone_not_allowed` (403), `data.reason`: email_unverified, suspended, daily_limit, monthly_limit, no_go, no_go_review | Verified email: an `acct:` owner needs `accounts.verified_at`; other sign-ins (Google, sign-in off) carry their own identity. Limits 5 a day, 30 in 30 days, counted from `voice_records` with origin clone or upload; `set_limits` (admin) raises them, kept in `meta` `voice_clone_limits:<owner>`. No-go: `NoGoCheck` interface, today `NameListNoGo` over `app/safety/figures.py` |
| `require_attestation(user, video, voice)` | `require_attestation(owner, video_id, voice_id=None, speaker_label=None)` | `attestation_required` (409) with `voice` (what to post to), `voice_id`, `video_id`, `source_video_id`, `speaker_label`, `speaker_name`, `statement_version` | Cloned voices only. A voice proven to be the user's own (library with a passed check) needs none. Before a clone exists the attestation is for the speaker (`voice` is the speaker's label); it then covers the clone made for them. Matches the current `STATEMENT_VERSION` only, so bumping it asks everyone again |
| `check_scope(voice, video)` | `check_scope(voice_id, video_id, owner=None)`, `usable(...)` | `voice_out_of_scope` (403); `voice_unavailable` (403, `reason` withdrawn, suspended, account_suspended) | The family is the video, its variants (`settings.variant_of`) and language versions (`master_id`): two videos are one family when they share the same first video. A voice with no record (stock) passes; someone else's voice is out of scope |
| `check_line(user, voice, text)` | `check_line(owner, video_id, voice_id, text)` | `line_blocked` (422, `category`), `line_in_review` (409) | `LineChecker` interface; today `PassThroughLines` (every line passes and is still written, its text hash only). Runs for every voice, cloned or not (open decision 7) |
| `log_synthesis(...)` | `before_synthesis(owner, video_id, voice_id, text) -> Ticket`, then `log_synthesis(ticket, take_id, cost_usd)` | never fails; a write error goes to `failures.report` (admins told) | `before_synthesis` runs scope, attestation, line in the plan's order and carries their ids to the log |
| `require_export_attestation(user, export)` | `require_export_attestation(owner, video_ids)`, `confirm_export(owner, export_ref, label_on, ip)` | `export_confirm_required` (409) with `export_ref`, `voices` (voice, video, speaker), `videos`, `label_default` true, `statement` | There is no export id before an export is made, so the refusal hands back `export_ref` (a hash of what it covers, its details kept in `meta` until confirmed). A confirmation covers each video's content (`video_id:edit-set hash`), so the same edits never ask twice and changed ones do; one confirmation covers a whole batch |
| `strike(user, category)` | `strike(owner, category)`, `suspend(owner, reason, by)`, `restore(owner, by)`, `suspended(owner)` | n/a | 3 blocked lines in 24 h suspend: no new clones, every cloned voice `suspended` (reason `account`), until an admin restores. The suspension is a `meta` row (`voice_suspension:<owner>`), not a sixth table |
| (routes) | `attest`, `promote`, `withdraw`, `own_voice_check`, `record_voice`, `backfill`, `drain_vendor_deletes`, `at_start`, `describe`, `export_label` | | `promote` needs a passed check of the real gate (`liveness_attempts`, method verified) for the voice's source video and speaker: `own_voice_check_required` (403) without one. `withdraw` marks it withdrawn at once and deletes it at the vendor (left `delete_queued` if that fails; `drain_vendor_deletes` retries at app start, only for owners with the flag on). `record_voice` is written by every clone path whatever the flag; `backfill` (at start) adds a record for any voice the lists hold without one |

`GuardedVoice` wraps the adapter: `synthesize`, `speak_like`, `revoice` and `create_clone` reach the vendor only inside `vendor_pass(synth_key(video))` or `vendor_pass(clone_key(owner))`, for an owner with the flag on; otherwise `guard_bypassed` (500, our side). Every other attribute, read or written, is the adapter's, and a method the adapter lacks is missing on the wrapper too.

**Routes** (`app/voice_guard_api.py`; 404 with the flag off, admin routes admins only and audited):

| Method | Route | Notes |
| --- | --- | --- |
| GET | `/voices/attestation/statement` | `{version, title, body, choices, confirm, warning, cancel, accept, export: {...}}`, the plan's copy word for word |
| POST | `/videos/{id}/voices/{voice}/attest` | `{choice: my_voice or have_permission, statement_version}`; 409 `statement_changed` with the new statement when it moved on |
| POST | `/exports/{export_ref}/confirm` | `{label_on}` (default true) |
| GET | `/voices/scopes` | the owner's voices with scope, status, `video_only` (for step 6's chips) |
| POST | `/voices/{id}/promote` | library after a passed check, and kept in My voices |
| POST | `/voices/{id}/withdraw` | withdrawn, deleted at the vendor, and the speaker's clone forgotten so a new one can be made with new checks |
| POST | `/admin/users/{id}/suspend-cloning`, `/restore-cloning` | `{reason}`; audited `voice_suspend`, `voice_restore` |
| POST | `/admin/users/{id}/clone-limits` | `{day, month, reason}`; audited `voice_clone_limits` (not in the plan: open decision 2 says admins raise it) |

Seams for later steps: `LineChecker` (step 4: replace `voice_guard.lines`), `NoGoCheck` (step 5: replace `voice_guard.no_go`, it gets `reference` audio), `export_label(owner, video_id)` (step 7: the label choice), `describe` and `GET /voices/scopes` (step 6's badges).

Tests: `backend/tests/safety/test_voice_guard.py` (33: every function, the flag off, the vendor seam, the routes).

## Step 3: every enforcement point

| Plan path | Where | Checks |
| --- | --- | --- |
| Clone a speaker: agent `clone_speaker`, the own voice of a line, a batch child | `CloneService.resolve` (`app/orchestrator/clones.py`) through `CloneService.guard` (`_CloneGuard` in main.py) | `can_clone`, then `require_attestation` for the speaker, before the reference is cut or anything paid; the vendor call inside `clone_pass`; `record_voice` (video scope) after |
| Clone from the UI: your own recording | `POST /voices/mine` | `can_clone` (limits), the vendor inside `vendor_pass(clone_key)`; recorded as library (origin upload). Still needs `voices.cloning` (the admin-opened path) |
| Save to My voices from a speaker | `POST /voices/mine/from-speaker` | a passed own-voice check (`own_voice_check_required` without one), which also opens it under `voices.cloning_verified` alone; `can_clone`; library, linked to the check |
| Save to My voices a clone made in a video | `POST /voices/mine/keep`, `POST /voices/{id}/promote` | `promote`: a passed own-voice check |
| Any synthesis: `synthesize_take`, Voice it (retry), fast path, language versions, Sync, speech to speech, the Voice Changer | `main._generate`, the only caller of the pipeline (`run_edit`) | `before_synthesis` (scope, attestation for cloned voices, the line), the vendor inside `vendor_pass(synth_key(video))`, then `log_synthesis` with the take id and cost |
| A voice picked by hand for a speaker | `PUT /videos/{id}/speakers/{label}` | `check_scope` |
| Export, batch export, share link, review link with download | `POST /videos/{id}/export` (purpose export), `POST /projects/{id}/exports`, `POST /projects/{id}/shares` (video or project scope; a reviewer link only with Download), `POST /videos/{id}/review-links` (with Download) | `require_export_attestation`, one for all the videos a batch or link covers. A link to a batch export (`scope: export`) shares what was confirmed when it was made. Labels and metadata are step 7 (`export_label`) |
| Agent planning | `list_voices` and `synthesize_take` (`app/agent/tools.py`) through `Workbench.voice_refusal` | `list_voices` lists only voices `check_scope` allows here; `synthesize_take` refuses another video's clone (or a withdrawn or paused one) with the guard's sentence, before anything is paid |
| Consent withdrawn now (G6) | `withdraw_consent_now` | the video's clones' records follow (`mark_withdrawn`) |

Not a voice-vendor path: lip-sync (it moves the picture to a take already voiced, so the take's own checks stand) and voice design (a designed voice is not a clone; it has no record). Both noted for the owner.

**The vendor behind the guard.** `main.voice` is `GuardedVoice(adapter, voice_guard)`, and the CloneService holds the same object. A structural test reads every Python file under `backend/app` (but the adapters, offline benches and tools): every `synthesize`, `speak_like`, `revoice` and `create_clone` call must be one of six known places, each inside a guard pass, and the pipeline must be reached only from `_generate`. A new call or route without the guard fails it.

**The contract for the front end (step 6).**

- A route refusal: HTTP status and `{"detail": {"code": "<code>", "message": "<plain sentence>", ...facts}}`. `attestation_required` is 409 with `voice`, `voice_id`, `video_id`, `source_video_id`, `speaker_label`, `speaker_name`, `statement_version`: the modal posts `{choice, statement_version}` to `/videos/{video_id}/voices/{voice}/attest`, then the action is tried again. `export_confirm_required` is 409 with `export_ref`, `voices`, `videos`, `label_default`, `statement`: the reminder posts `{label_on}` to `/exports/{export_ref}/confirm`, then exports again.
- An agent turn: the turn ends on a question (the card), never on Voltage's words about it. `question.kind == "attestation_required"`, `question.attestation` the same facts as above, `question.text` "Use <speaker>'s voice?", `options` ["Use this voice", "Cancel"], `gate` false (so a typed "go" is not an attestation). The editor opens the modal from it; after the attest call it answers "Use this voice" and the next turn voices the line. In a batch the card waits on that video like any other question. The fast path hands it to a full turn, which then pauses on the card.
- Every other guard refusal reaches Voltage as the guard's sentence (`voice_out_of_scope`: "This voice can only be used in the video it came from."), and a job or line row shows the same sentence (`failures.say`).

Tests: `backend/tests/safety/test_voice_enforcement.py` (15: the structural four, then no attestation then attested, the agent's pause, the fast path, out of scope from another video, the agent and a batch child and a hand-picked speaker voice, variants and language versions, export and batch export and links, Save to My voices, withdraw, a new statement version, the clone path's order, flag off).

## Step 5: the public-figure block on clone, the no-go list admin

Code: `backend/app/safety/no_go.py` (`VoiceListNoGo`, the guard's `no_go`), `backend/app/no_go_api.py` (routes), migration `backend/app/store/migrations/m0055_no_go_matches.py`, `similarity.speaker_embedding` and `similarity.cosine` (`app/continuity/similarity.py`), wired in `backend/app/api/main.py` (`no_go`). Front end: `frontend/src/pages/admin/VoiceSafetySection.tsx` (a minimal Voice safety tab) holding `NoGoHoldsQueue.tsx` and `NoGoVoicesList.tsx`, calls in `noGoApi.ts`.

| Plan item | Code | Adaptation |
| --- | --- | --- |
| On clone, the speaker embedding (same WavLM as consent) against `no_go_voices` | `VoiceListNoGo.check`, from `VoiceGuard.can_clone` (the speaker clone: `CloneService` now hands the cut reference to `guard.before_clone`) and `VoiceGuard.check_no_go` (the two My voices routes, once they have the audio) | `similarity.speaker_embedding` is the same model and cosine as SIM-o, so the score is the consent check's number. An entry stores its unit vector (JSON) and the model it came from; an entry from another model is not compared (unmeasured) |
| 0.92 or more: block | `clone_not_allowed`, reason `no_go`, "This voice is on the list of voices Voltage does not clone. Pick a voice from the catalogue, or design one from words." | The entry is never named to the user (the name list still names the figure, as before) |
| 0.84 to 0.92: hold for admin review | `clone_not_allowed`, reason `no_go_review` (the step 2 copy), with `hold_id`; a `no_go_holds` row, the admins told (bell, `consent_review`) | The clone waits: nothing is cut or paid. Approve: the next try of the same clone (this video's speaker, or this exact uploaded audio) goes through. Reject: it is blocked as above. The person is told either way (`consent_decided`). A retry while waiting reuses the hold. Each borderline entry needs its own approval |
| Below 0.84: continue | pass | |
| Same bands as consent, logged | `BLOCK_AT = consent.PASS_AT`, `REVIEW_FROM = consent.REVIEW_FROM`; one `no_go_checks` row per check that compared anything (verdict, how, the closest entry, every score) | An empty list compares nothing and writes nothing |
| Keep the name list | `VoiceListNoGo.names` (`NameListNoGo` over `app/safety/figures.py`) runs first | |
| No speaker model | List empty: nothing to compare, the clone continues. List not empty: the clone is held for a person (`how` unmeasured), like the consent check's unmeasured voice | |
| Interface for a vendor check in V2 | `VoiceListNoGo.vendor`, a `VendorVoiceCheck` (`check(reference) -> NoGoVerdict or None`); its block or review counts like the list's | None today |
| The list starts empty, admin managed | no seed; `GET/POST/DELETE /admin/no-go-voices` | |
| Add from an uploaded clip or a reported export | `POST /admin/no-go-voices` (multipart): `name`, `reason`, and `file`, or `mark` (a provenance mark), or `abuse_report_id` (the report's text names a mark), optional `start`/`end` | The clip is read into a 16 kHz WAV in a temporary folder, embedded, and deleted with the folder in the same request; at least 3 s of voice; 503 without the speaker model |
| Remove with a reason | `DELETE /admin/no-go-voices/{id}` `{reason}` | Clones still waiting on it are closed and their clips deleted |
| The borderline queue, Approve or Reject with a required reason | `GET /admin/no-go-holds?status=waiting or decided`, `GET /admin/no-go-holds/{id}/audio`, `POST /admin/no-go-holds/{id}` `{decision, reason}`; `GET /admin/no-go-checks` (the log) | A held clip is copied to `data/no-go-holds/` only while it waits and deleted once decided. An admin cannot decide a clone of their own (allowed with sign-in off, where one person is everyone) |
| Audit trail for every action | `no_go_add`, `no_go_remove`, `no_go_approve`, `no_go_reject` | |

Migration 0055 adds `model`, `source`, `source_ref`, `seconds` to `no_go_voices` and the tables `no_go_checks` and `no_go_holds` (both with `workspace_id` and 0034's RLS policy on Postgres). 0049 to 0054 are left for the other steps of this run (`RESERVED` in `tests/store/test_migrate.py`). `down` refuses while any of the three holds rows.

With the flag off, `can_clone` and `check_no_go` return at once: nothing is embedded, compared or written.

Tests: `backend/tests/safety/test_no_go.py` (14), `frontend/src/pages/admin/VoiceSafetySection.test.tsx` (7).

## Step 4: line checks

| Plan item | Code |
| --- | --- |
| Rules: keyword and pattern lists per category, English, Hindi, Hinglish, versioned | `app/safety/line_rules.py`: `check(text) -> RuleResult(verdict, categories, hits)`, `VERSION`; rule ids with the version go to `line_checks.rule_hits` |
| Model: Haiku 5.5 reads the line, neighbours and brief, returns `{verdict, categories, reason}` | `app/adapters/claude_lines.py` `ClaudeLineReader.read(lines, context)`: one structured-output call for a list of lines by id; context is the project's brief and what the video says (`main._line_context`) |
| Only rule-passing lines reach the model | `LineChecks.check`: a rule block returns before the model; a rule review still goes to it |
| Verdict | `LineChecks.combine`: block if either blocks; review on a rule claim, a model review, or a line the model left out (`unclear`); else pass |
| Batch and language versions in one call | `VoiceGuard.prepare_lines(owner, video_id, texts)` from `_queue_lines` (a Go), `make_languages` (the master's lines), `sync_language` (the changed lines); a single check also takes the video's pending planned lines (`main._pending_lines`). Translations of a fully passed master take the rules only (`master_of`) |
| Model call fails | `LineVerdict.model_failed`; `VoiceGuard._model_failed`: held (`unclear`) for a cloned voice, pass with a log warning otherwise |
| Line text only for block or review | unchanged from step 2; `reason` and `model_ms` added |
| Blocked line never reaches the vendor | `check_line` raises before `_generate` opens the vendor pass (tested with the adapter's `synthesize` patched) |
| Block copy names the category | `voice_guard.BLOCKED` (fraud is the plan's sentence), `block_copy` picks by `BLOCK_ORDER` (minors first) |
| Minors also reported | the guard's `tell("minor")`: an `abuse_reports` row and an `abuse_report` notice to admins (`main._line_news`) |
| Strikes: 3 blocks in 24 h suspend cloned-voice synthesis | step 2's `strike`, now fed by real verdicts |
| Review queue `GET /admin/line-checks?verdict=review` | `app/voice_guard_api.py`: `state=waiting` (oldest first, with `due_at`) or `decided`; `POST /admin/line-checks/{id}` `{decision, reason}` |
| Owners can't approve their own; audit; notify on clear; auto-reject at 48 h | `VoiceGuard.decide_review` (`own_line` 403), `admin.audit` `line_approve`/`line_reject`, notice `line_decided`; `expire_reviews` (every 10 minutes, at start, on reading the queue) |
| A held line, once approved, voiced without a re-check | `check_line` finds the approved row by owner, video and text hash and writes a pass with `model = approved:<id>` |
| Admin UI: Voice safety tab | `frontend/src/pages/admin/VoiceSafetySection.tsx` (`VOICE_SAFETY_QUEUES`, one entry per queue; step 5 adds its own), `voiceSafetyApi.ts`, registered in `admin/sections.tsx` |

Migration 0050 (`m0050_line_review.py`): `line_checks.reason`, `review_state`, `reviewed_by`, `reviewed_at`, `review_reason`, `model_ms`, index on `(review_state, created_at)`; down drops them and refuses while any line was held. 0049 is left for step 5.

Notification kinds `line_review` (admins) and `line_decided` (owners), on by default, not yet in the settings list (`inbox.UNLISTED`; step 6).

Acceptance eval: `python -m evals.line_checks` over `backend/evals/line_checks/lines.json` (50 block lines, 10 per category, English, Hindi, Hinglish; 100 ordinary ad lines). Results of the shipped configuration: `backend/evals/results/20261031T130736Z-line-checks-tuned.json`.

Tests: `backend/tests/safety/test_line_checks.py` (29: each category by rules in three languages and by the model with its copy, ordinary lines and warnings pass, rules under 5 ms, minors reported, review, model failure defaults, stock voices checked, blocked line never at the vendor, one call per batch and per plan, language translations, the queue, approve, reject, 48 h, strikes and restore, flag off, the mock), `frontend/src/pages/admin/VoiceSafetySection.test.tsx` (5).

## Step 7: labels and metadata on export, Trace, suspend and restore

| Plan item | Code | Adaptation |
| --- | --- | --- |
| "AI voice" label on by default, a small corner tag for the first 3 seconds | `app/render/label.py` (`geometry`, `overlay`, `burn`), the picture `app/render/assets/ai-voice-tag.png` (from `ai-voice-tag.html`); batch files: `deliver(..., label=True)` in `_deliver_one`; the Export page's file: `label.burn` in `_provenance_export` | ffmpeg here has no drawtext, so the words are a picture in the design system's display face, overlaid with `enable='lt(t,3)'`, 5% of the short side tall (at least 22 px), top left (lower on 9:16). On when the export has a cloned voice and the reminder kept it on: `VoiceGuard.export_facts(owner, video_id)` (the seam `export_label` reads the same confirmation) |
| A line in the export's description file | `label.description`, written beside each file as `<name>.txt` by `_stamp_export`; batch zips carry them (`_zip_response`); `GET /videos/{id}/artifacts/{sha}/description` for the Export page's file | There was no description file: added, flag on only. The label's line only when the label is on |
| Permanent metadata on every export: export id, "contains AI-generated voice", Voltage, timestamp, in the container and the C2PA stub | `provenance.stamp(..., export={export_id, ai_voice, label_on})`: `provenance.tag` (mp4 mdta `voltage_export_id`, `voltage_generator`, `voltage_created`, `voltage_ai_voice`, after the watermark, which stays), the manifest's `voltage.export` assertion; `provenance.read_tags` reads them back | Export id: a batch file carries the batch export's id; the Export page's file its own `ve_` id (one per render and label choice). Every export of an owner with the flag on is stamped, even with `golive.g6` off |
| On an export: "Trace" shows the voices, attestations, line checks and user behind it | `VoiceGuard.trace(ref)`, `GET /admin/exports/{ref}/trace` (`app/voice_guard_api.py`), audited `voice_trace`; front end `frontend/src/pages/admin/TraceSection.tsx` (admin section `trace`), a Trace link on each abuse report (`AdminPage.tsx`, `openTrace`) | `ref`: an export id, a provenance mark, the reminder's reference or confirmation id, or an abuse report's number (the marks and export ids its words name). Lists the files, the voice records with every attestation for them, the export confirmations, the synthesis log rows of the takes the export plays and their line checks, and the people (emails, cloning suspension, limits) |
| On a user: "Suspend cloning" disables all their cloned voices and blocks new clones; "Restore" reverses it | step 2's routes; `GET /admin/users/{id}/cloning` (`VoiceGuard.cloning_state`); front end `frontend/src/pages/admin/CloningControls.tsx` on the People view | Restore now needs a reason (422 without). A suspension also stops voices cloned from an uploaded recording (`CLONE_KINDS`). The box shows the state, the limits and use, voices by status, Change limits, then Suspend cloning or Restore cloning |
| Every action audited | `voice_suspend`, `voice_restore`, `voice_clone_limits`, `voice_trace` | |

Migration 0053 (`m0053_export_trace.py`): `provenance_marks.export_id`, `ai_voice`, `label_on`, `export_attestation_id`, `voices`, `takes`, index on `export_id`; down refuses while a mark carries an export id.

With the flag off, `export_facts` is None: no label, no metadata, no description file, the manifest and the stamp exactly as before.

Tests: `backend/tests/safety/test_export_trace.py` (22: the tag there in the first 3 s and gone after by frame diff, at every preset and aspect ratio, absent when not asked; the metadata read back with ffprobe and from the manifest; the Export page's file and a batch with the label on by default, off from the reminder, no cloned voice, flag off; Trace by export id, mark, reminder reference and abuse report, audited, admins only; suspend and restore with reasons), `frontend/src/pages/admin/TraceSection.test.tsx` (7).

## Step 6: the attestation modal, the export reminder, line copy, voice chips

Front end: `frontend/src/consent/` (`ConsentHost.tsx` mounted around the app in `App.tsx`, `context.ts`, `copy.ts` the plan's words, `AttestationForm.tsx`, `AttestationModal.tsx`, `ExportReminder.tsx`, `LineRefusal.tsx` with `AttestationCard` and `RefusalNote`, `ProveVoice.tsx`, `types.ts`); `api.ts` `send` and the four calls (`attestVoice`, `confirmExport`, `getVoiceScopes`, `promoteVoice`). With the flag off `ConsentHost` installs nothing and `useConsent().on` is false everywhere.

| Plan item | Code | Adaptation |
| --- | --- | --- |
| Attestation modal, the plan's copy with the speaker's name | `AttestationModal` (a Radix Dialog: focus on the title, Tab stays inside, Escape cancels, focus back) over `AttestationForm` (two labelled radios in a fieldset, the confirmation box, the warning, Cancel then Use this voice, off until both) | The name: `speaker_name`, else "Speaker N" from the label, else "this speaker". A 409 `statement_changed` on the post says so and asks again |
| Opened from any 409 wherever a voicing starts, then the original action tried again once | `api.ts` `send` (POST, PUT, PATCH, multipart) hands the 409 to the asker `ConsentHost` installs; one dialog at a time; after a confirmation the same request is sent again | Routes that used to find the missing attestation only inside their job now ask first: `quick_line` (`_quick_attestation`), `retry_job` (the job's voice), `make_languages` (the master's clones, voice `same`) |
| If Voltage started it, the turn pauses on the card | `VoltagePane`: a question of kind `attestation_required` (facts in `attestation`) is `AttestationCard`, the form in the gate card's frame; Use this voice posts the attestation, then answers "Use this voice"; Cancel answers "Cancel". `BatchPanel` rows show the same card | `_question_of` and the batch row keep `kind` and `attestation` (`_guard_card`) |
| The fast path opens the modal directly | `quick_line` answers 409 before its job (no turn, no planning call); the editor's modal, then the same quick request | The job's own GuardPause fallback stays for a race (an attestation withdrawn in between) |
| Export reminder: label on by default, permission required, one per export, once per batch; share and review links with Download | `ExportReminder` (Radix Dialog), posts `{label_on}` to `/exports/{export_ref}/confirm`, then the export request again | The title names every voice of the export ("Asha's and Ravi's voices" for two). Back or Escape: the guard's sentence stands as the error |
| Blocked, held and suspended copy, in the chat and on the line, with [Edit the line] | `LineRefusal` on a failed row whose reason is the guard's sentence (`LineDoc` `lineBlock`); `RefusalNote` in the turn for a step carrying `data.refusal` (`synthesize_take`'s ToolResult `data`, also on the fast path's step message); [Edit the line] opens the line editor on the refused words (`voltage:edit-line` from the chat) | The sentence is recognised from the guard's words (`copy.refusalKind`): the row has `item.error`, not a code |
| Held lines show held, and clear when the notification arrives | `LineRefusal` held state; `ConsentHost` reads `/me/notifications` every 15 s while a held line is on screen; a `line_decided` for the video with the line's words settles it (Cleared: Voice it now; Not cleared: the reason and Edit the line) | Needs the bell (`golive.g4`); without it the line stays held until the page reloads |
| Show the two notification kinds in Settings | `inbox.kinds_for(admin, consent)`, `notify_api._consent` | Listed only with the flag on; `line_review` admins only, as before |
| "This video only" on voice chips | `GET /voices/scopes` read once by `ConsentHost` (`scopeOf`); the Voices page's made voices, the line editor's voice picker | The pane has no per-voice chips; these are the two places a voice is shown to pick or keep |
| Save to My voices opens the own-voice check, "Prove it's your voice"; pass promotes; review or fail keeps it video-scoped with the reason | `ProveVoice` (Dialog) over `LivenessStep` (new `speaker` and `onSettled` props), then `POST /voices/{id}/promote`; the Voices page keeps "Kept for this video only. <reason>" on the voice | |
| Using a video-scoped voice elsewhere | the picker says "This voice can only be used in the video it came from." when the voice's source is not this video, its master or what it is a variant of; the guard still refuses with the same sentence | |

Tests: `frontend/src/consent/consent.test.tsx` (24: the copy and the server's copy, the modal, the reminder, the 409 retry and cancel and flag off, a batch asks once, the host, held lines clearing, blocked and suspended, the pane's card and refusal, the transcript's Edit the line, the picker's tag and sentence, Prove it's your voice pass and fail), `frontend/e2e/voice-consent.spec.ts` (9: clone, attest, voice, reminder, export against the same journey with the flag off; the agent's pause; a blocked line; at 1440x900, 1280x720, 1920x1080), backend `tests/safety/test_voice_enforcement.py` (the fast path route, Retry, language versions, the batch row card), `tests/safety/test_line_checks.py` (the step's refusal), `tests/golive/test_inbox.py` (the listed kinds).

## Step 8: Terms, Acceptable Use, Help, RUNBOOK, statement versioning

| Plan item | Code | Adaptation |
| --- | --- | --- |
| Terms: users warrant rights and consent for every voice and indemnify Voltage; cloned voices suspended or deleted on a credible complaint | `frontend/src/pages/legal/terms.ts` draft v3: Voices and consent (rewritten for the attestation, video scope, own-voice proof, the warranty), Suspending and deleting voices (new), Your responsibility to us (indemnity names the voice warranty), Using Voltage fairly | The v2 text said the speaker's read-aloud check was required for every clone; v3 describes V1 (attestation for a voice in its own video, the check for My voices). It describes the flagged flow, which stays off until review (counsel note) |
| AI voice labels and metadata | Terms, What Voltage makes | Label on by default, switchable; metadata permanent; the user still discloses where the law or platform requires |
| Retention (decision 6) | Terms, Records we keep about voices; Privacy, Voice confirmations and line checks (new) | 7 years attestations and export confirmations, 2 years line checks and synthesis log. Nothing enforces them yet (no purge of these rows): a launch blocker |
| Acceptable Use bans impersonation, fraud, robocalls, political and election content, sexual content, harassment | `acceptableUse.ts` draft v3: Consent comes first, No impersonation, No deception, Elections and public life, No fraud, No harm to others (rewritten), Lines we check (new: the five block categories and the held ones in plain words, the strike rule), What we do (voice actions) | v2 allowed labelled political advertising; v3 bans political and election lines outright, as the line checks block them. Sexual content in a synthetic voice is banned outright for the same reason |
| Grievance officer and contact on the site | `acceptableUse.ts` Grievance Officer (new; the Privacy policy already had one) | Placeholders only: `[Grievance Officer name]`, `[... email]`, `[... phone]`, `[Registered address]`, timelines in brackets. The owner fills them |
| Draft marking | `Section.draft` (`legal/types.ts`), shown by `LegalPage` as a "New, pending legal review" stamp under the section's heading, plus a source comment and a counsel note opening "Draft v3 (31 October 2026), pending legal review." on each | Visible to readers: see DECISIONS.md |
| Version and date | file comments draft v3 (2026-10-31); the page's line "Drafted 24 October 2026; the sections on voices revised 31 October 2026."; `AVE_TERMS_VERSION` default `draft-2026-10-31` (`accounts_api.py`, `.env.example`, the Terms counsel note) | As the pages did for v2 |
| Help article "Using voices responsibly" | `help/articles/voices/using-voices-responsibly.md` (section Voices, order 406): whose voice, Use this voice?, This video only, Prove it's your voice, the export reminder and label, held and blocked lines, Report misuse | Served and searched like every article (`app/help`); no index file to edit. Its last line points flag-off readers to The speaker's own voice and consent |
| Linked from the modal and the export reminder | `frontend/src/consent/LearnMore.tsx` ("Learn more", new tab, so the dialog keeps its choices); after the warning in `AttestationForm` (so in the modal, the pane's card and the batch row), and above the buttons in `ExportReminder` | The plan's sentences are unchanged and still each their own element; the buttons stay last |
| RUNBOOK "Abuse and takedown" | `RUNBOOK.md` section 7: the plan's 5 steps on the real tools (Trace, the evidence rows and a backup, links, Suspend cloning, the reply, No-go voices from a mark or report, the audit trail), the 3-hour target for orders, what to preserve; plus Changing the consent wording, and Regions | |
| Disable share and review links | New `POST /admin/links/revoke {video_id, reason}` (`app/admin_api.py`): every live link that opens the video (its own share and review links, a project link that lists it, a batch export link with a file of it), whoever made it; one `share_revoke` audit row per link | `POST /admin/shares/{id}/revoke` existed for one link by id; a takedown needs all of a video's |
| Disable the voice | Suspend cloning (step 7) | No admin switch for one voice alone; Suspend cloning disables all the user's cloned voices, Restore brings them back, the owner's Withdraw deletes one at the vendor. A per-voice admin disable is a follow-up |
| Statement versioning: one source | `STATEMENT`, `EXPORT_STATEMENT`, `STATEMENT_VERSION` in `app/safety/voice_guard.py` (step 2); `copy.ts` mirrors the words and its vitest reads them from `voice_guard.py` | Added `statement_hash()` (both statements, version left out) |
| A wording change without a version bump fails | `backend/tests/safety/test_statement_version.py` `PINNED` (version to hash) | |
| A bumped version forces re-confirmation | step 2 and 3 tests (attestation); `test_statement_version.py` adds the export confirmation and the confirm-again path | |
| How to bump | RUNBOOK.md, Changing the consent wording | |

**Regions (decision 5).** Cloning opens in India first. No country gate exists on an account or a deployment; today it is who an admin gives `voices.cloning_verified`. The cheap V2 gate: `can_clone` refuses with `clone_not_allowed` reason `region` when the account's billing country (`billing_accounts.country`, already set at checkout, self-declared) is set and not in a deployment list `AVE_CLONING_COUNTRIES` (default `IN`), with a sign-up country question for accounts that never paid. Not built.

Tests: `backend/tests/safety/test_statement_version.py` (6), `backend/tests/launch/test_admin_tools.py::test_an_admin_takes_down_every_link_that_opens_a_video`, `frontend/src/consent/consent.test.tsx` (Learn more), `frontend/src/pages/LegalPage.test.tsx` (the draft stamps, the indemnity, retention, robocalls, the grievance placeholders), `backend/tests/test_help.py` (every article's front matter, unchanged).

## Status against the plan

**Tests that must pass**

| Plan test | Status | Evidence |
| --- | --- | --- |
| Voicing with a cloned voice and no attestation returns `attestation_required`; after attesting, it works | done | `tests/safety/test_voice_enforcement.py` (no attestation then attested, the agent's pause, the fast path), `tests/safety/test_voice_guard.py`, `e2e/voice-consent.spec.ts` |
| A video-scoped voice on another video returns `voice_out_of_scope`, including from the agent and batch | done | `test_voice_enforcement.py` (out of scope from another video, the agent, a batch child, a hand-picked speaker voice) |
| Variants and language versions can use the source video's voice | done | `test_voice_enforcement.py::test_variants_and_language_versions_can_use_the_source_voice` |
| Exporting with a cloned voice needs the confirmation; batch export asks once | done | `test_voice_guard.py::test_an_export_with_a_clone_asks_once_and_a_batch_once_for_all`, `test_voice_enforcement.py` (export, batch export, links), `consent.test.tsx` (a batch asks once) |
| Exports carry the label (default on) and the metadata with the export id | done | `tests/safety/test_export_trace.py` (frame diff in the first 3 s, ffprobe, the manifest) |
| Each block category is blocked by rules or model with the right copy; review lines wait for an admin | done | `tests/safety/test_line_checks.py` |
| Three blocks in 24 hours suspend cloned-voice synthesis; admin restore works | done | `test_line_checks.py` (strikes and restore), `test_export_trace.py` (suspend and restore) |
| A no-go voice above 0.92 cannot be cloned; 0.84 to 0.92 waits for review | done | `tests/safety/test_no_go.py` |
| Save to My voices requires a passed own-voice check | done | `test_voice_enforcement.py` (Save to My voices), `consent.test.tsx` (Prove it's your voice) |
| Withdraw deletes the vendor voice and blocks use | done | `test_voice_enforcement.py` (withdraw) |
| Trace on an export lists voice, attestation, line checks and user | done | `test_export_trace.py` (by export id, mark, reminder reference, abuse report), `TraceSection.test.tsx` |
| Changing the statement version forces re-confirmation | done | `test_voice_guard.py::test_a_new_statement_version_asks_again`, `test_voice_enforcement.py::test_a_new_statement_version_forces_reconfirmation`, `test_statement_version.py` (the pin, the export too) |
| Migration on a copy: counts match, nothing lost, down restores | done | `tests/store/test_m0048_voice_consent.py`; the dry run on the live copy (step 1) |

**Acceptance before turning it on for the public**

| Item | Status | Evidence or what is left |
| --- | --- | --- |
| All tests green, plus the rehearsal journeys with a cloning step | partial | `make launch-check` green on each step; `e2e/voice-consent.spec.ts` is a clone, attest, voice, export journey. The rehearsal journeys (`e2e/rehearsal/*`, `scripts/rehearsal.sh`) have no cloning step yet |
| 50-line test set across the block categories in English, Hindi and Hinglish: every block caught, under 5% false blocks on 100 ordinary lines | done | step 4 eval, 3 runs: 50/50 caught, 0 false blocks in 100 (`backend/evals/results/20261031T130736Z-line-checks-tuned.json`) |
| A beta user can clone, attest, voice and export in under 30 s of extra time | partial | step 6 estimate from the Playwright journey: 5 extra clicks, about 0.75 s of waits, 12 to 22 s for a first-timer. Not measured with a beta user |
| Lawyer has reviewed the copy, Terms and retention | not done | Every new section is marked "New, pending legal review" |

**Launch blockers left**

- Lawyer review of the attestation and export copy, Terms v3, Acceptable Use v3, the Privacy addition and the retention periods; then remove each `draft`, bump `AVE_TERMS_VERSION`, and bump `STATEMENT_VERSION` if the consent words change.
- The owner fills in the Grievance Officer (name, email, phone, address) on the Acceptable use and Privacy pages, and the bracketed timelines.
- A purge for `voice_attestations`, `export_attestations` (7 years), `line_checks`, `synthesis_log` (2 years): today nothing deletes them.
- A cloning step in the rehearsal journeys, and a timed beta run.
- `voices.cloning_verified` stays off for the public until all of the above; when it opens, India only (decision 5), by who gets the flag until a country gate exists.
