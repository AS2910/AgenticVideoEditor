# Voltage · Projects Build Plan (Oct 20, 2026, from the user)

Saved verbatim in substance from the user's message so every overnight agent reads the same spec.

## Working rules for every item
1. Read the existing code first. Reuse the Phase 20 agent loop, the guard classes (free, spend, commit), the content-addressed artifacts and the spend reservations. Do not build a parallel system.
2. Every long-running action is a Job (F1). No feature runs work outside the Job model.
3. Every agent action that changes more than one video goes through one plan, one gate and one proposal per video. A turn still edits only its own video unless it is a batch turn (F4).
4. No em dashes in any UI copy, prompt or model output, unless the user typed one.
5. A migration for every schema change, with a down step. Old routes keep working for one release as aliases.
6. Every new screen follows the Volt design system. When a screen has no board, match the nearest one and list it under "Needs a design" (NEEDS_DESIGN.md).
7. Feature flags for every phase (`projects.consistency`, `projects.batch`, `projects.review`, `projects.reuse`), on for internal accounts first.

## Definition of done for each item
- Schema, API and UI shipped behind its flag
- Unit tests for the logic, one integration test for the main flow, one end-to-end test in the browser
- Costs go through the spend guard and appear in Usage under the right video and project
- Loading, empty, error and "in progress" states all drawn and reachable
- Help article and one tour tip updated
- Event names added to analytics (G7)
- Screenshots or a short recording

## Foundations
| ID | Building block | What it is | Used by |
|---|---|---|---|
| F1 | Job model | (DONE before this plan: jobs table, SSE, status strip, row states, badge) One jobs table and SSE stream for every long action: voicing, render, export, check, batch. | everything |
| F2 | Brief versions | `project_briefs(project_id, version, text, created_by, created_at)`. The project points to its current version. Each turn stores `brief_version` it read. | A1, A2, D2 |
| F3 | Project rules store | `project_rules(project_id, kind, data, version)`. Kinds: `pronounce`, `banned`, `required_line`, `style`. Read into every turn's opening view. | A2, A3, D1, D2 |
| F4 | Batch turn engine | A parent turn that plans across N videos, opens one gate, then runs one child turn per video. Children use the normal turn code. Parent holds the shared budget. | B1, B2, A1 |
| F5 | Video stage | `videos.stage`: Draft, In review, Changes asked, Approved, Exported. Changed only through one service that logs who and when. | C1, C2, B3 |
| F6 | Share tokens | Signed, revocable, expiring links scoped to a project or video, with a role: viewer or reviewer. No account needed for a reviewer. | C2, B3 |
| F7 | Activity log | `project_events` with actor (user, Voltage, reviewer), verb, target, payload. Drives the project feed and notifications. | A1, C1, C2, G4 |
| F8 | Soft delete | `deleted_at` on projects, videos and voices. Every query filters it. A nightly purge removes rows and storage after 30 days. | D3 |

Rules across them: keyed to a workspace (workspace_id, default = owner's own; RLS waits for G5). F4 children each reserve their own spend inside the parent's reservation; a child that would cross a ceiling stops and the parent reports which videos finished. F7 events are written in the same transaction as the change they describe.

## Phase A · Keep a campaign consistent (needs F1, F2, F3, F7)
### A1 · Brief versions and stale videos
- Each brief save creates a new version (F2). Each video stores `made_with_brief` = the version its last shipped edit used.
- Project page: brief shows "v4 · edited by Ashish, 2 days ago" and a History link with a diff between versions.
- Stale: when the brief changes, every video on an older version gets a "Brief changed" chip on its card and in the editor header. Project page: "3 videos made with an older brief · Bring up to date".
- Bring up to date: starts a batch turn (F4) with goal "Apply brief changes v3 to v4". Voltage reads the diff, proposes only lines the change touches, skips videos it does not affect, saying why. (A1 lands before F4: wire the button to F4 when F4 exists; until then it may run per-video turns sequentially or be disabled with a note.)
- Voltage proposes brief changes: keep the existing rule; applies only when accepted, creates a new version.
- Tests: saving a brief bumps the version; stale count correct after a move in or out; a video with no affected lines is marked current without spending.
### A2 · Project check
- Checks across all videos, using transcripts and shipped edits only (no new audio): facts that disagree (prices, percentages, dates, offer names, phone numbers, URLs); the same role voiced by different voices; pronunciation breaking an F3 rule; banned words or a missing required line; loudness more than 2 LU apart between videos.
- A Job (kind "check") that runs a cheap text pass with Claude over transcripts plus deterministic checks for loudness and rules. Cost shown before running; free when only rule checks are needed.
- UI: "Check project" button and an Issues panel on the project page. Each issue names videos and timecodes, with "Fix in this video", "Fix in all" (batch turn) or "Ignore".
- Auto-run after a brief change, and before batch export (B3) as a warning, never a block.
- Tests: a seeded project with known conflicts returns exactly those issues; ignored issues stay ignored until the text changes.
### A3 · Glossary and word rules
- Project page section "Words": table Term, How to say it, Respell, Example audio. Plus Banned words and Required lines ("T&C apply" in every video).
- Turn behaviour: rules go into the opening view. Before a take is kept, the fit check runs a rule check on the take's words and its transcript (Whisper). A take that breaks a rule is marked "Breaks a word rule" and is not offered as Voltage's pick.
- Pronunciation: pass respellings/phoneme hints to the TTS vendor where supported; otherwise rewrite the line's text for synthesis only, display text unchanged.
- Learn a word: in the editor, select a word, "Add to project words". Optional 2 s clip of the right pronunciation.
- Tests: a take that mispronounces a glossary term fails the check; a banned word in a user-typed line warns but does not block.

## Phase B · Work across many videos (needs F1, F4, F5, Phase A)
### B1 · Batch goals
- Entry: chat box on the project page ("Ask Voltage about all videos"), and "Fix in all" from the project check.
- Flow: pick videos (all by default; checkbox list shows stage). Voltage plans once, one gate card: "5 videos · 11 lines · about $0.42 · about 2 min". After Go, one child turn per video, 3 at a time.
- Results: batch board, one row per video: Queued, Working, Ready to review, Nothing to change, Failed. Each row opens that video's proposals. "Add all that passed" applies every passing proposal, one undo per video.
- Rules: a child edits only its video. A child that hits a question pauses alone and shows it on the board; others continue. Parent cap = sum of child caps, shown before Go.
- Tests: 5-video batch with one failure finishes the other 4; cancelling stops queued children, running ones finish; Usage spend equals the sum of children.
### B2 · Language sets
- `videos.master_id`, `videos.language`. A language child is a variant linked to its master.
- "Make language versions": pick languages (Hindi, Tamil, Hinglish, Marathi to start), voice handling: same cloned voice speaking the new language, or a designed voice per language. One batch turn writes and voices every line.
- Translation rules: glossary per-language terms; brand names never translate; lines fit original timing (fit ladder, then shorter rewrite).
- Keep in sync: master ships a new edit -> each child "Out of sync with master" chip + "Sync this change" (only changed lines).
- UI: master + children as one stacked card with language chips.
- Tests: master edit marks all children out of sync; sync touches only changed lines; brand term stays untranslated.
### B3 · Batch export
- Presets on the project: platform (YouTube 16:9, Reels 9:16, Feed 1:1), codec, loudness (-14 LUFS web, -24 broadcast), burned-in captions on/off, file name pattern like `{project}_{video}_{lang}_{preset}_v{version}`.
- Flow: choose videos (Approved only by default), one or more presets, export. One Job per video x preset, grouped in one parent Job with total progress.
- Delivery: zip download, plus a share link (F6) listing every file with a preview player. Links expire after 30 days by default.
- Pre-flight: runs project check (A2) as warnings; non-Approved videos flagged.
- Tests: file names follow the pattern; loudness within 1 LU of target; a failed render retries once, then Failed with a reason without blocking the rest.

## Phase C · Review and hand-off (needs F5, F6, F7)
### C1 · Stages and the project board
- Stages Draft, In review, Changes asked, Approved, Exported. Manual moves, except: sending a review link -> In review; reviewer approval -> Approved; any new edit on an Approved video -> Draft, with a warning before the edit is added.
- Board toggle beside Grid on the project page. Columns = stages; cards: thumbnail, length, open comments, chips "Brief changed"/"Out of sync". Drag a card to change stage.
- Feed: right-hand Activity panel from F7.
- Tests: an edit on an Approved video drops it to Draft and logs it; drag and drop writes one event.
### C2 · Client review link
- "Send for review" on a video or set creates a reviewer link (F6), optional name, expiry, "Allow download" off by default.
- Reviewer page, no login: player with current render, version picker (v3, v4, v5 with "what changed"), comment box pinned to current time, Approve and Ask for changes.
- Comments arrive in the editor as timeline items at their time; reply, resolve, or hand to Voltage ("Do what the client asked") which opens a normal turn with the comment as goal.
- Notify: email owner on comments, approvals, change requests, batched every 10 min. Reviewer gets an email when a new version is ready, if they gave one.
- Safety: revocable links; watermark with reviewer's name when download is off; nothing beyond the render exposed.
- Tests: expired link shows a clear message; comment lands at the right timecode; approving sets the stage and logs the reviewer's name.

## Phase D · Reuse and housekeeping (needs F2, F3, F8)
### D1 · Project templates
- "Save as template" copies brief, words (A3), export presets (B3), defaults and ceiling. Voices referenced not copied; project-owned voices ask the same "copy or keep in my voices" question as a move.
- "New project": Blank or From a template. Templates in a list, renamable, deletable.
- 3 starter templates: Festive ad, Product explainer, Interview cleanup.
- Tests: a project from a template has no videos and the same brief text and rules.
### D2 · Learned style
- Log each proposal decision with reason: added, rejected, edited before adding, text difference.
- After every 10 decisions in a project, Voltage looks for patterns and suggests one line for the brief or rules. Applied only on accept, creates a new brief version.
- "What Voltage has learned" list on the project page, each item removable.
- Tests: suggestions never apply without accept; removing an item takes it out of the next turn's opening view.
### D3 · Bin
- Deleting a project, video or voice moves it to the Bin for 30 days (F8). Deleting a project with videos asks the existing question.
- Bin page: items, who deleted them, days left. Restore puts a video back in its project, or standalone if the project is gone.
- Voices with consent records: the record stays for the legal retention period after purge. Purge deletes the vendor voice too.
- Usage history never deleted; charges keep the deleted item's name.
- Tests: restore brings back turns, edits and renders; purge after 30 days removes storage keys; a deleted voice cannot be picked.
### D4 · Pin, archive, search, sort
- Pin projects and videos to the top of Home's sidebar (per user).
- Archive a project: hidden from Home, still searchable, read-only until unarchived.
- Search across project names, video names, transcripts and brief text, grouped by project. Keyboard: / to focus.
- Sort by last edited, created, name, stage. Filter by stage and "needs attention" (brief changed, out of sync, open comments).
- Tests: an archived project blocks new turns with a clear message; transcript search finds a spoken word and jumps to its time.

## Go-live items in scope tonight
- G1: sample project preloaded with the bhaji-cam ad; upload from a link (Google Drive, Dropbox, YouTube you own) behind an interface.
- G2: roles Owner, Editor, Reviewer; workspace invites; per-member spend limits (email sign-in exists? Google exists; invites without real email: fake provider).
- G4: in-app notification bell plus email behind an interface (fake provider): job done, job failed, review comments, approvals, spend alerts; per-user settings.
- G7: event tracking for every key step; funnel sign-up to first export; take acceptance rate, cost per exported minute; internal admin page.
- G8: thumbs up/down with a reason on every take and turn; an error-reporting hook (Sentry-like interface, fake/no-op provider).
- G3 billing (plans, credits, top-ups, ceilings, Stripe/Razorpay, GST invoices, trial credits, 50/80/100% alerts) and G6 (consent liveness, public-figure block, invisible watermark + C2PA, abuse report, data export/deletion) ONLY behind interfaces with fake providers.

## Open decisions (use these recommendations)
1. First customer: agencies. 2. Pricing: credits with a monthly plan, shown as "about N minutes"; reviewers free. 3. Batch: 3 videos at a time; a batch cannot start above the project ceiling without the owner raising it. 4. Languages: Hindi, Hinglish, Tamil, Marathi, English. 5. Fallback TTS: OpenAI TTS. 6. Reviewer access by signed link, no login. 7. Bin: 30 days. 8. Stripe international, Razorpay India. 9. Invisible watermark and C2PA always on; visible watermark only on the free plan.

## Approved by the user for tonight
- workspace_id on every table, defaulting to the owner's own workspace. Postgres and RLS wait for G5.
- A numbered migration runner first, with up and down steps. Move today's startup ALTERs into it.
- A minimal feature-flag store, on per owner.
- F2 moves projects.brief to versions; keep projects.brief as a read-only alias for one release; record brief_version on each turn.
- Screens with no board: match the nearest screen and list them in NEEDS_DESIGN.md.

## Order (finish each before starting the next)
0. Migration runner, flags, workspace_id
1. F2, F3, F5, F7, F8 (schema and services, then tests)  [F6 share tokens: build with C2]
2. Phase A: A1, A3, then A2 (adds the "check" job kind)
3. F4 batch engine (adds the "batch" job kind), then B1, B3, B2
4. C1, then C2 (F6 with C2)
5. D3, D4, D1, D2
6. G1, G2, G4, G7, G8; G3 and G6 behind interfaces with fake providers.
