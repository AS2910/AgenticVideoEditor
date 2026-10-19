# Voltage — what is built, as user and functional requirements

*As of 2026-10-18, main at the UX-9 merge (the studio, and your own voices). This is the product as it stands, not a plan. Each requirement says how it is met and where; a gap is marked as one. The phase history behind it lives in `docs/superpowers/plans/`.*

## 1. Purpose and scope

Voltage edits what a video **says**. You upload a clip, and an agent (Claude with tools) reads it, listens, looks at the picture, and can change the words of a spoken line, add a line or a voice-over, remove a line, move one, choose or make a voice, decide how a line is delivered, and render the result. Every change is a **proposal** you can hear before it goes into the video, unless you have told Voltage to just do it.

In scope today: dialogue replacement, added lines and voice-overs (layered over the picture, or with the picture holding), removals, shifts, the speaker's own voice (cloned from the clip), stand-in and designed voices, expressive delivery (direction, dials, audio tags), the picture flexing to fit a line, a measured sound check, spend caps, consent, sign-in. English. Clips up to about three minutes with an audio track.

Out of scope or not built: lip-sync (Phase 17, paused), inpainting-grade speech editing (Phase 18, needs a GPU), visual edits, pacing/filler edits, non-English.

## 2. Who uses it

- **One local owner** by default (`AVE_AUTH=off`): everything on the machine belongs to the person at the keyboard.
- **Signed-in users** (`AVE_AUTH=google`): Google sign-in, an allow-list of emails, a per-user spend ceiling, and every project owned and checked per route.

## 3. User requirements (the agreed stories, and how each is met)

The stories were agreed on 2026-10-03 (`docs/superpowers/plans/2026-10-03-ux-plan.md`). Status: **Built**, **Partly**, **Not built**.

| # | Story | Status | How it is met |
|---|---|---|---|
| A1 | See what is said, by whom, where | Built | The transcript lists every spoken line with its time, speaker (name, or Speaker 1, 2, 3 in order of appearance), and state. The player's timeline shows lines as blocks by speaker and the changed spans. |
| A2 | Know what can be done | Built | Voltage's first message reads the clip (an opening line, a role per speaker, examples to click). Every row shows its verbs on hover/focus. |
| A3 | A voice-over on a silent clip | Built | A clip with no speech opens on a place editor (where the voice-over goes, the words, voice, delivery); Voltage places lines by time; each is its own row. |
| B1 | A goal for the whole video | Built | Anything typed in Voltage's box is a turn: a goal, a brief, a change, an answer. |
| B2 | Change one line | Built | Edit it on the line → words, delivery, voice → **Voice it** sends one sentence to Voltage ("Replace the line at 0:04 (“…”) with “…”, said warmer, in Riya's voice"). |
| B3 | Change one word | Built | The Precise word timeline selects a span; the composer then speaks about those words ("At 0:04: …"). The agent snaps edits to word boundaries. |
| B4 | Add a line | Built | Add a line after (any line), a typed start time, or a placed span; over the picture or holding it. |
| B5 | Remove a line or word | Built | Discard on a spoken line proposes its removal (the room's own sound in its place); Remove it confirms. The agent's `remove_line` makes the same proposal. |
| B6 | Change delivery | Built | Delivery chips (warmer, more excited, calmer, slower, firmer) or your own words; the agent also chooses direction, the vendor's dials, the model and audio tags itself. |
| B7 | Asked only when it matters | Built | The agent asks with the `ask` tool (two or three options and its guess); under Check with me, paid and committing steps wait for your go. |
| B8 | Adjust the plan in words | Built | Every message is a turn on the same thread; the plan card is a record, not a form. |
| C1 | Hear in place, flip to the original | Built | Hear it on any row; the player plays **Final**, **With proposals** (a preview render with the proposed takes mixed in) or **Original**. |
| C2 | A verdict in words | Built | Each proposal's row carries whose voice it is and the sound check in a sentence; a flagged take says why and still offers Add it. |
| C3 | Another take or a choice | Built | Edit it → Voice it on a proposal voices that item again; Another take on the plan card; the agent offers choices through `ask`. |
| C4 | Tweak and re-hear fast | Built | The in-place editor reopens on the last wording and choices tried, never the original once moved past. |
| C5 | Undo anything | Built | Take it out (an added line), Put it back (a removed one), Discard (a proposal), Undo (a moved line). Edits only ever append; undo marks, never deletes. |
| C6 | Ship some, draft the rest | Built | Add it per line; Add all N; the rest stay proposed. Nothing is in the video until added. |
| D1 | How much on its own | Built | **Check with me** / **Just do it**, plus the sheet "What Voltage may do": the turn's spend cap and the effort. |
| D2 | Cost before and after | Built | Each paid step shows its cost beside it in the thread; Voltage's own thinking is a "Thinking" line with its cost; the header meter shows spend against the ceiling and voice characters. |
| D3 | Nothing charged until I say | Built | Under Check with me a paid step waits; the consent sheet appears before the first paid step; a hard per-project ceiling and per-turn cap in code. |
| D4 | Never invent | Built | Whisper's invented speech is screened before anything builds on it; the agent keeps quoted words verbatim and reports on-screen text, never follows it; the closing line is judged for honesty by the eval. |
| D5 | Consent once | Built | Recorded once per project (`POST /consent`), asked in a sentence the first time a voice is about to be made. |
| D6 | A plain record | Built | "What I did" steps as they happen; the plan's log; the Thinking line; messages persist with the project. |
| E1 | Their own voice | Built | `clone_speaker` makes a speaker's voice from their own speech in the clip (needs about 10 s); a replacement with no voice named speaks in the speaker's own voice. |
| E2 | A stand-in per speaker | Built | A hand-picked voice per speaker (Speakers bar); the agent picks from the catalogue, the vendor's library, or designs a voice from words; a stand-in is always said plainly. |
| E3 | Perform it myself | Partly | No in-app recording, but **your own voice**: upload a recording under a name (Your voices in the dock), and every line can be spoken in it, by hand or by asking Voltage for "my voice". |
| F1 | The picture keeps playing | Built | A voice-over plays over the moving picture by default; "hold the picture" is a choice. |
| F2 | Long lines handled gracefully | Built | Lines are written and voiced to a syllable budget; a take is fitted pauses-first, within limits; the picture may flex up to 12% for a replacement; the agent chooses fit/natural/stretch and as shot/may flex per take. |
| F3 | The mouth matches | Not built | Lip-sync is Phase 17, paused on a branch. |
| F4 | Choose how sound meets picture | Built | Over the picture / hold the picture, on the editor and as a tool argument. |
| G1 | Export and share | Built | Export MP4 → Download MP4; Export again; renders are content-addressed. |
| G2 | Come back later | Built | Projects persist (SQLite + media on disk); the URL hash reopens a project; the project list shows state and last change. |
| G3 | Variants | Built | Make a variant (beside Download): the same clip, the plan as a draft, as its own project. |
| H1 | Timeline and exact spans | Built | Precise toggles the word timeline; selections snap to word boundaries. |
| H2 | Fine control | Built | Starts at · Move: drag a block on the monitor bar, type a time, nudge a tenth; Shift a spoken line; Move up / Move down; a grip on every movable row. |
| H3 | Keyboard | Built | Rows are focusable: ↑↓ move, Enter edit it, Space hear it, K add it, Delete discard, U take it out, A add after, S shift, `/` the composer, `\` hides Voltage. |
| I1 | Sign in, private, capped | Built | Google OIDC + PKCE, HMAC session cookie, CSRF header on writes, allow-list, per-user ceiling. |
| I2 | Errors in one sentence | Built | Failures are Voltage's reply in the thread or one line under the player, with one action. |

## 4. Functional requirements

### 4.1 Projects and ingest

- **Upload** a video (`POST /projects`, multipart; up to about 3 minutes; must have an audio track). The sample ad is uploaded through the same path.
- **Transcription** by Whisper (`whisper-1`, `verbose_json` for word timestamps). Empty symbol slots are dropped; a transcribed segment is **dropped when it is probably invented** (Whisper's own `no_speech_prob`/`avg_logprob`/`compression_ratio`, the known invented sign-offs, or no speech energy above the noise floor). A clip that ends with no words is treated as silent: a voice-over clip.
- **Speakers**: detected on request (`POST /speakers/detect`), named and given a voice by hand (`PUT /speakers/{label}`); an unnamed speaker shows as Speaker 1, 2, 3.
- **Reading** (`POST /reading`): Voltage's first look — an opening line, a role per speaker, and on a silent clip what it saw in the frames (the place can be confirmed or corrected, `PUT /sight`).
- **Consent** (`POST /consent`): an attestation recorded per project; paid generation refuses without it (403) and the UI asks in a sentence before the first paid step.
- **Projects list** (`GET /projects`): a frame, state (new / draft / shipped), last change, variant-of. **Delete** removes the record and all media, and any voices Voltage made for it. **Variants** (`POST /variants`) copy the clip with the plan as a draft.
- **Persistence**: SQLite (`backend/var/ave.db`) for projects, edits, candidates, plans, messages, the agent's thread and spend; media as content-addressed files. Jobs live in memory.

### 4.2 Voltage, the agent

- **A turn** (`POST /turns`, a job): the user's words go in; the agent runs a loop over its tools (Claude Opus 5.5, adaptive thinking, strict schemas where an argument can be got wrong, server-side fallbacks, context editing of old frames past 40k tokens, compaction past 100k) and ends with a plan state and a closing sentence or a question. Steps appear live as messages (`GET /messages?after=`).
- **The thread is append-only** and persisted as the model saw it; a turn cut off mid-way is repaired (its unanswered tool calls get "not run" results) so the next turn continues.
- **The opening view** of every turn: the clip, the speakers, the plan's items and states, **what is in the video already** (every shipped edit, since layers stack), the money (spent, ceiling, this turn's cap) and the autonomy.
- **Autonomy**: **Check with me** — a paid or committing step waits for the user's go (a question card; "go" or the first option resumes with the same context). **Just do it** — the agent proceeds and ships finished work, but a **compromise is shown, not shipped**: a stand-in voice when the speaker's own was asked for, a take that failed its check, words it had to cut.
- **The sound check is advice, not a lock**: when the user says ship it as it is, the agent ships with `anyway` and says the check flagged it.
- **Guards**: free tools; paid tools charge the voice budget before the call and refund on failure; committing tools gate under Check with me. A per-turn money cap (`turn_usd`, default $0.50), a call cap and a time cap end a turn politely.
- **Money is said**: each paid step's cost beside it; the turn's own Claude cost as a "Thinking" step after the closing words; the agent is told not to guess its own cost or call a turn free.
- **Tools** (the full list in §6): look, read, find room, hear, voices (catalogue, library, design, save, add, delete, clone), estimate, project state, synthesize a take (words, voice, direction, model v2/v3/v4, dials, audio tags, placement, fit, picture), keep/drop/move an item, measure, remove a line (a proposal), shift a line, ship (with `anyway`), undo an edit, ask.
- **Settings per project** (`PUT /settings`, the "What Voltage may do" sheet): autonomy, the turn's spend cap (bounded by the project ceiling), the effort (medium / high / xhigh).
- **An eval** (`python -m app.tools.agent_eval`): ten goals over three clips, fresh uploads, one turn each under Just do it, graded by Claude against a rubric (fit, delivery, placement, nothing committed without a gate, honesty), the cap checked from the ledger in code. Standing at 7 of 10 against a 9 of 10 bar; the misses are closing-line precision.

### 4.3 The transcript (the one working surface)

- **The studio (UX-9).** Three panes: the player with **lanes** under it (V1 picture, A1 spoken, A2 added with overlapping lines in sub-rows, A3 room tone), the transcript and takes, Voltage; a dock (Projects, Workspace, Speakers, Your voices); light and dark rooms in slate/obsidian and cyan.
- **One transcript.** Four kinds of row, in time order: a **spoken line**; a **moved line** where it now plays; an **added line in the video** (every live layered edit); a **proposed or working added line** (every plan item with an added mix). Lines at the same moment are separate rows and play together; a layer over a spoken line never changes that line's words.
- **State words** beside their colour: nothing (as shot), **Proposed**, **Added**, **Voicing…**, **Needs you**, **Couldn't voice it**, **Removed**, **Moved** / **Moved away**, **Planned**, **Reading**.
- **Four verbs.** On a proposal: **Hear it · Add it · Edit it · Discard** (always visible; "Remove it" on a proposed removal). On a spoken line: Hear it · Edit it · Discard (proposes removal) · Add a line after · Move up / Move down / Shift to a time (on hover/focus, "…" on touch). On an added line: Hear it · **Take it out** · Edit it. On a removed line: **Put it back**. **Add all N** in the heading when more than one line is proposed.
- **A proposal's facts** on its own line: whose voice, the verdict in words (a flagged take says why and "Add it anyway if it sounds right to you"), Starts at · Move, and for an added line its **level** ("background (−12 dB) · Make it foreground" / "Make it background").
- **The in-place editor**: the words (with "You'd be changing" as tracked changes), Delivery (chips or your own words), Voice (the catalogue, grouped by accent), for an added line Starts at and Sound meets picture; the cost estimate; **Voice it** sends one sentence to Voltage and the take comes back proposed. On a proposal, Voice it voices that item again; on an added line, the new take swaps the old edit out.
- **Moving things**: a grip on every movable row (drag up/down, a drop line with the time), Starts at · Move (drag on the monitor bar, type a time, nudge), Shift a spoken line as spoken (two paired edits, undone together).
- **Keyboard**: see H3. Roving focus: only the focused row exposes its controls to Tab.

### 4.4 Takes and voices

- **Vendor**: ElevenLabs. Models **v2** (steadiest, finest style control, reads tags as words so they are stripped), **v3** (expressive, performs tags, no surrounding-text context), **v4** (newest, performs tags, keeps context; the default when the text carries tags). Audio tags (`[excited]`, `[sighs]`, `[whispers]`, …) with timestamps; a tag's span is kept in the audio and dropped from the word list.
- **Delivery**: free-text direction kept with the take, the vendor's dials (stability, style, speed, similarity), speed retries for fit.
- **Voices**: a catalogue (premade and library-added, four Indian voices among them; never clones), **your own voices** (uploaded under a name with your word that the voice is yours, 10 s or more, cloned once, kept per user, first in every picker as "Name (yours)"; "in my voice" means one of them to the agent), the vendor's library by accent and gender, a **designed voice** from a description (three previews to hear in the thread; one kept by name; takes a slot), the **speaker's own voice** cloned from the clip (about 10 s of their speech; a hand-picked voice is cleared with the user's knowledge), a hand-picked **stand-in per speaker**. A stand-in is always named as one.
- **Fit**: every line carries a syllable budget; a take is fitted pauses-first (trim or open silence before speeding or slowing speech, within 0.8×–1.25×); a long line may start up to 150 ms early; the agent chooses `fit` (fit / natural / stretch) and `picture` (as shot / may flex) per take. One take per tool call; retries are the agent's decision.
- **The sound check** (`continuity/measured.py`): prosody (pitch register against the surrounding speech; skipped for an added line in another voice on purpose), audio integration (level and clarity after automatic level and room-tone correction), voice match (SIM-o, wants 0.75) when the speaker's own voice was wanted, naturalness (UTMOS, wants 3.0). A failing take is **flagged, not blocked**: it is shown, not shipped, until the user says.
- **Room**: stems (Demucs, optional) so a line sits over the original's own bed; room tone from the recording's own quiet fills a removal.
- **Levels** (20g): every added line has a level, foreground (as voiced) or background (12 dB under the words), so two audios coexist and both are heard. The agent voices cheers, crowds, ambience and anything "background" at background, fixes a layer that buries a line with `set_level` without voicing again, and never lets a background layer drown the words under it. By hand: Make it background / Make it foreground on the row.

### 4.5 Proposals and commit

- **Every change is a proposal first**: a voiced take, a removal (a ready item whose take is the room's own sound), an added line. Nothing is in the video until **Add it** (`POST /plans/{id}/approve` with the item; `override` carries a flagged take on the user's word), **Add all**, or the agent's `ship`. Shift is the one hand action that is immediate and undoable.
- **Discard** a proposal (`POST /plans/{id}/items/{item}/dismiss`): it leaves the plan. **Take it out** / **Put it back** / Undo (`POST /edits/{id}/revert`): the edit is marked reverted, the render skips it, the plan item goes back to proposed with its take. A shifted line's two edits revert together.
- **A redo swaps, never piles up**: the agent's rule (and `undo_edit`) when a line already in the video is redone; an overlay the user asks for on top of what is there is a new layer.
- **Approval renders** the final at once; a hand approval turns the row Added and switches the player to Final; when Voltage ships on its own, the panel takes the render in and a sheet says what is in the file.

### 4.6 Playback and render

- **Three versions in the player**: **Final** (the added lines), **With proposals** (a preview render with the plan's proposed takes mixed in as preview edits — `POST /export` with `{"with_proposals": true}` — made on demand, keyed by the takes it carries, remade when they change, a status line while it renders), **Original**. Hear it on a proposal plays its take over the final render when the render's clock is the source's, else over the original; the original's words are muted under a replacement.
- **The render** (`render/renderer.py`, `render/compose.py`, `render/retime.py`): the source's audio everywhere outside an edit; a replacement spliced with 20 ms equal-power crossfades; **layers claim no span and are mixed additively over whatever plays there, at their level** (any number of audios coexist at one moment; a background layer sits 12 dB under); an added line with the picture holding gets a living hold (the picture's own motion steers where time is added) or, rarely, a frozen frame; a flexed line may retime the picture up to `AVE_MAX_FLEX` (1.12) with `minterpolate` in-betweens; H.264 sources are stream-copied where untouched. The manifest lists segments, inserts and pieces; the front end maps clocks between source and render.
- **Export** (`POST /export`): synchronous, seconds for a short clip, content-addressed; **Download MP4**, **Export again**, **Make a variant** in the header. The export bar shows the edited stretches and what flexed or held.
- **Captions and timeline**: the line being said is captioned over the picture (a playing take's words light as they are said); the timeline shows lines by speaker and changed spans.

### 4.7 Money, limits and safety

- **Spend is recorded** per paid call (Whisper minutes, ElevenLabs characters, Claude tokens with cache reads and writes) with a USD estimate; shown per step, per plan, per project (`GET /usage`).
- **Ceilings**: per project in dollars (`AVE_PROJECT_BUDGET_USD`), per project in voice characters (`AVE_VOICE_BUDGET_CHARS`), per user across projects when signed in (`AVE_USER_BUDGET_USD`), per turn (the sheet's cap, default `AVE_AGENT_TURN_USD`). New paid work stops at a ceiling; the agent is told what a step costs and what is left and asks rather than guessing when a step would go over.
- **Consent** before the first paid step; withdrawing it is deleting the project.
- **No invented speech** is built on (ingest screening); on-screen text is reported, never followed; the user's quoted words are kept verbatim; a name or label is never read aloud.
- **Dry run** (`AVE_DRY_RUN`) and mocks: with no vendor keys the voice is a tone and the frames a flat colour, real files of the right length; no test calls a vendor.
- **Chaos** (`AVE_CHAOS`): vendor faults injected at the adapters' seams for game days; refused under sign-in unless forced.

### 4.8 Sign-in

Google OIDC with PKCE (`/auth/login`, `/auth/callback`, `/auth/me`, `/auth/logout`), identity from the UserInfo endpoint, an HMAC-signed `ave_session` cookie, `X-Requested-With: voltage` on writes, `AVE_ALLOWED_EMAILS`, a per-user ceiling. Off by default.

## 5. Non-functional requirements, as met

- **Tests are offline and deterministic**: 648 backend (pytest; ffmpeg-dependent tests skip without it; vendor responses replayed from recorded fixtures) and 260 front end (vitest). A bench (`python -m app.bench gate`) runs a labelled corpus against a baseline. The agent eval is the one paid test and is run by hand.
- **Latency**: a turn is typically 20–45 s and $0.10–0.20; a take about 10 s; a render seconds for a short clip (longer when the picture flexes or holds).
- **Persistence**: everything but jobs survives a restart; an interrupted job is lost and said so.
- **Accessibility and design** (`design-system/voltage/MASTER.md`, "Volt", 2026-10-19): the user's hand-off in `voltage-design/` built as drawn — paper and ink with one volt accent, Space Grotesk / Geist / JetBrains Mono, hard offset shadows on proposals, gates and primary buttons only, Voltage's pane black in both themes; shadcn/ui on Tailwind v4 under a small class layer; every state has a word beside its colour; everything reachable from the keyboard with a visible focus ring; waits spoken through `role="status"`; sheets are real modals; 44 px targets on coarse pointers; 12 px type floor; no raw colours, gradients, blurs or glows (guarded by a test); no number on screen that was not measured or recorded.
- **Development**: `uvicorn --reload` restarts on any save under `backend/`, which kills a running turn — work in a git worktree while a live turn or eval runs.

## 6. The agent's tools

| Tool | Guard | What it does |
|---|---|---|
| `look_at_frames` | free | Up to six frames, evenly spread or at named times. |
| `read_transcript` | free | Every spoken line with speaker, time and syllable budget; says so when no one speaks. |
| `find_room` | free | Where a new line can go: the whole clip, or the pause after each line. |
| `hear` | free | Whether anyone speaks in a span, what they say, how loud background and speech are. |
| `list_voices` | free | The catalogue: id, name, gender, accent, age, how they sound. |
| `search_voice_library` | free | The vendor's library by accent and gender. |
| `estimate` | free | What voicing these words costs and what the turn has left. |
| `project_state` | free | The plan's items and states, what is in the video already, the money. |
| `synthesize_take` | spend | Voice a line and place it: words, voice (empty = the speaker's own or the default), direction, model, dials, line or start/end, mix, fit, picture, level (foreground / background), item to voice again. One take per call. |
| `keep_take` | free | Put an earlier take back on an item. |
| `drop_item` | free | Drop a planned or voiced line from the plan. |
| `design_voice` | spend | Three previews from a description, for the user to hear in the thread. |
| `save_voice` | commit | Keep one preview as a named catalogue voice (a slot). |
| `add_voice_from_library` | commit | Put a library voice in the catalogue (a slot). |
| `delete_voice` | commit | Remove a voice Voltage made; always asks. |
| `clone_speaker` | commit | The speaker's own voice from their speech in the clip; asks under Check with me. |
| `remove_line` | free | Proposes taking a spoken line out, the room's sound in its place. |
| `shift_line` | commit | Move a spoken line in time, as spoken. |
| `move_item` | free | Place a voiced item's take at another time. |
| `set_level` | commit | Mix a proposal (by item) or a line in the video (by edit) as background or foreground, nothing voiced again. |
| `measure` | free | The full sound check of a take. |
| `ship` | commit | Make the voiced lines part of the video and render; `anyway` carries the user's word past the check. |
| `undo_edit` | commit | Take a shipped edit back out of the video. |
| `ask` | free | One question, two or three options, the agent's guess; the turn ends. |

Limits the API taught us: at most 8 union-typed parameters across strict tools (7 in use), strict schemas only on the seven complex tools (the compiled grammar overflowed at 19).

## 6a. Projects as folders, tutorial and help (2026-10-19)

A **video** is one clip and all its work (what this document calls a project elsewhere, before the rename); a **project** is now a folder of videos that share a brief, voices, reference files, defaults and an optional ceiling. A video is in one project or none; moving it changes one field. Inside a project Voltage reads the brief, the shared voices and the sister videos in every turn, can read the reference files, and can propose a brief change that applies only when accepted. New users get a free guided run on the sample ad (a recorded turn replayed), first-time tips, a five-item checklist, a keyboard sheet on `?`, and a Help page whose articles Voltage also answers from (`search_help`). Details: `docs/superpowers/plans/2026-10-19-folders-and-help.md`.

## 6b. The screens (Volt, 2026-10-19)

Hash routes, one page each: `#projects` (upload, the sample, recent projects with Open / Delete-with-undo), `#pN` (the editor), `#pN/export` (the final render, Download, Copy link, the receipt), `#voices` (your voices: record or drop a file, clone a speaker from a project, design one from a description, keep what Voltage made; Hear it on any), `#usage` (this week / month / all time: total, by vendor, by project, turns and takes), `#settings` (defaults for new projects, what still asks under Just do it, appearance, sign out, delete everything), `#billing` (placeholder). The editor: header (file, length and voices, Final · With proposals · Original, the autonomy word → What Voltage may do, the spend → Usage, Export, account), the picture with its scrubber markers (volt proposed · ink in the video · amber waiting) and Tracks (the lanes and the word-precise timeline), the one transcript, and Voltage's pane (turns: your words, the trace of steps with tools and costs, the reply, a gate card with the step's cost and what the turn has left, suggestion chips, the composer). The first read shows Who's speaking with Voltage's guesses and one Looks right.

## 7. The API

| Route | What it does |
|---|---|
| `GET /health` | Vendors, planner, agent, auth mode, jobs, chaos. |
| `GET/POST /auth/*` | Sign-in (§4.8). |
| `POST /projects` · `GET /projects` · `GET /projects/{id}` · `DELETE /projects/{id}` | Upload and transcribe; list; detail (edits, messages, plan, settings); delete with media. |
| `POST /projects/{id}/consent` | Record consent. |
| `GET /projects/{id}/usage` · `GET/PUT /projects/{id}/settings` | Spend against ceilings; autonomy, turn cap, effort, `ask_before` (which commits still wait under Just do it), the model (read-only). |
| `GET/PUT /me/settings` | Your defaults for new projects (autonomy, turn cap, effort, `ask_before`). |
| `GET /usage?period=week\|month\|all` | What you spent across projects: total, by vendor, by project, turns and takes in the period, the ceilings. |
| `GET /projects/{id}/receipt` | The export page's receipt: turns, takes, spend, each change with a note, drafts left, the last final render. |
| `DELETE /account` | Everything of yours: projects, media, voices, settings, spend records. |
| `GET/PUT /projects/{id}/speakers[/{label}]` · `POST …/speakers/detect` | Speakers, names, hand-picked voices. |
| `POST /projects/{id}/reading` · `PUT /projects/{id}/sight` · `GET /projects/{id}/frames[/{index}]` | Voltage's first look; the place; frames. |
| `POST /projects/{id}/turns` (202) · `GET /jobs/{job_id}` · `GET /projects/{id}/messages?after=` | A turn of the agent; its job; the thread as it grows. |
| `GET /projects/{id}/plans/{plan_id}` · `POST …/approve` · `POST …/items/{item_id}/dismiss` | The plan; Add it / Add all (with `override`); Discard. |
| `POST /projects/{id}/lines/remove` · `POST /projects/{id}/lines/shift` | Propose a removal; shift a line. |
| `POST /projects/{id}/candidates/{cid}/move` · `POST /projects/{id}/edits/{eid}/move` · `POST /projects/{id}/edits/{eid}/revert` | Move a take; move an added line; undo. |
| `POST /projects/{id}/candidates/{cid}/level` · `POST /projects/{id}/edits/{eid}/level` | Mix a proposal or an added line louder or softer (`level_db`; −12 is background). |
| `POST /projects/{id}/edits` | Commit a candidate directly (`override` for a flagged one). |
| `POST /projects/{id}/export` | Render: the final, or with `{"with_proposals": true}` the preview. |
| `POST /projects/{id}/variants` | A variant project. |
| `GET /projects/{id}/artifacts/{sha256}` · `GET /voices` | Media; the catalogue and your own voices (`mine`). |
| `POST /voices/mine` · `DELETE /voices/mine/{voice_id}` | Upload or record a voice of yours under a name (consent required, ≥ 10 s); remove it. |
| `GET /voices/made` · `POST /voices/mine/keep` | Voices Voltage made inside projects (designed, cloned); keep one as yours under a name. |
| `GET /voices/speakers` · `POST /voices/mine/from-speaker` | Speakers with enough clean speech to clone; clone one into your voices (consent required). |
| `POST /voices/design` · `POST /voices/mine/from-preview` | Three designed previews from a description (paid, against your own budget); keep one as yours. |
| `GET /voices/sample/{sha}` | A voice's sample, for Hear it on the Voices page. |

## 8. Configuration

| Variable | Meaning |
|---|---|
| `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY` (+ `ANTHROPIC_WORKSPACE_ID`) | Vendors. Without a key the mock stands in; without Claude the agent and the reading answer "Voltage needs Claude". |
| `AVE_AGENT` (1), `AVE_AGENT_MODEL` (claude-opus-5-5), `AVE_AGENT_EFFORT` (high), `AVE_AGENT_TURN_USD` (0.50) | The agent and its defaults. |
| `AVE_PROJECT_BUDGET_USD` (2), `AVE_VOICE_BUDGET_CHARS` (2000), `AVE_USER_BUDGET_USD` (10) | Ceilings (raised to 10 / 20000 / 100 on the dev machine's `.env`). |
| `AVE_TAKES_PER_LINE` (3), `AVE_FIT_TOLERANCE` (0.05), `AVE_MAX_REGENERATIONS` (2), `AVE_MAX_FLEX` (1.12), `AVE_MAX_LIVING` (1.6), `AVE_INTERPOLATOR` | Fit and the picture. |
| `AVE_STEMS`, `AVE_CLONE`, `AVE_CLONE_MIN_SECONDS`, `AVE_MEASURE` | Room, cloning, the measured check. |
| `AVE_AUTH`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `AVE_SESSION_SECRET`, `AVE_PUBLIC_URL`, `AVE_ALLOWED_EMAILS` | Sign-in. |
| `AVE_DATA_DIR`, `AVE_DRY_RUN`, `AVE_CHAOS`, `AVE_CHAOS_FORCE` | Storage, dry run, chaos. |
| `SYNC_API_KEY`, `AVE_LIPSYNC`, `AVE_LIPSYNC_MODEL` | Lip-sync (Phase 17, on its branch only). |

## 9. Known gaps and what is next

- **Lip-sync** (Phase 17): built offline on branch `phase-17-the-mouth` (sync.so client, face stretches, export wiring), paused at a stalled export; resumes now that audio is the single transcript.
- **Inpainting-grade editing** (Phase 18): needs a GPU.
- **The eval bar**: 7 of 10 against 9; the fix is to give the closing words their facts (a final project state before the last line, and the source of each claim).
- **Shift** is still an immediate, undoable action rather than a proposal.
- **A variant** (`POST /variants`) has no button in the Volt screens yet; the route stands.
- **Billing** is a placeholder page: the ceilings are fixed in this build and nothing is charged; the copy says so.
- **Lip-sync is "not measured yet"** on every proposal's depth view until Phase 17 lands.
- **Ingest is synchronous**; jobs live in memory; a failed transcription orphans its upload.
- **The README's "journey" and "seams"** predate the agent and the single transcript; this document is the current description.
