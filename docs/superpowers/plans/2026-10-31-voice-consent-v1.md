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
