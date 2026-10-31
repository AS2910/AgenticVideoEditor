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
