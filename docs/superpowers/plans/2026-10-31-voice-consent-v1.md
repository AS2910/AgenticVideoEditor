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
