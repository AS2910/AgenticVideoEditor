# UX-5 · A voice for a silent clip

**Date:** 2026-10-04 · **Status:** built the same evening, after UX-6 (as-built note at the end). Closes gap G6 / story A3 of the UX plan ("voice-over on a silent clip", S1). Prompted by the Goa beach clip (`PXL_20261002_123407857.MC.mp4`, 7.5 s, no speech): three sends of "Add an audio introducing the place to the audience" each came back as the red strip *This video has no speech to change.*

## What is wrong today

Every path the agent has runs through the transcript. `_new_plan` refuses when `_lines(record)` is empty; `read_project` refuses the same way, so the goal stage is skipped and a silent clip lands straight in the editor. The planner's `Change` names a *line number*; an added line is "right after line N". With no lines there is nothing to anchor to, so the agent cannot even try.

Two things already work and are reused rather than rebuilt:

- **The engine voices a line over a silent span.** `POST /edits/preview` with a start/end and words: `edit_context(...).has_speech` is false, the mix question offers *layer* (over the sound) or *concatenate* (hold the picture), and `_generate` runs the take through fit and continuity. This is the hands-on path the chat's welcome text points at ("drag across the timeline"), hidden behind the *Precise* toggle.
- **The plan runner voices items from a `Selection`.** A `PlanItem` carries `selection`, `new_text`, `mix`, `delivery`; the runner never looks the line up again. Items on a silent clip only need a selection that is a *chosen span* rather than a line's span, `old_text` empty, and mix `layer`.

## The two ways the user talks to it

The user named both, and the planner must tell them apart from the words alone:

1. **"Do it" — or recommend from the query.** The goal carries enough to act: *Add an audio introducing the place: "Welcome to Goa"* (the words are given) or *Add an audio introducing the place to the audience* (a brief, no words). With words, Voltage places and voices them, no question. With a brief, Voltage **writes the line itself from what it sees**, puts its best wording in the plan and two alternatives as suggestions ("Welcome to Goa." / "This is Goa, at the end of the day." / "Morjim beach, just before the light goes."), and says in one sentence why it chose that one. Under *Just do it* it voices straight away; under *Check with me* it waits for Run, as every plan does.
2. **"Look at this and help me."** The goal asks for help rather than giving an instruction: *look at the video and help me*, *what should this say*, *I'm not sure what to put here*. Voltage looks first, says what it sees, and then asks — **one question at a time, up to three**, each with its own guess so *Go* always works. The questions come from the picture, not a fixed script: what the audio is for and how much of the clip it should cover; the tone (calm, warm, excited, documentary, playful); and what it is seeing, to confirm or correct ("This looks like a beach at dusk, on the west coast — Goa? Somewhere else?"). When a question's answer settles the rest, it stops asking. After the last answer it plans as in (1), with the brief it has gathered.

A dictated line that does not fit the clip goes through the existing fit ladder (into the room after it, sped up, or shortened with `planner.shorten`); on a silent clip the "room" is everything up to the end of the picture.

## What is built

### SV-1 · Sight: Voltage looks at the clip

**Frames.** `app/media/ffmpeg.py` gains `extract_frames(path, times, width=512) -> list[Path]` (one `ffmpeg -ss T -i … -frames:v 1 -vf scale=512:-2 -q:v 4` per time). `app/media/frames.py` chooses the times: one per 2 s, at least 3, at most 8, the first at 0.3 s and the last 0.3 s before the end. Frames are written once under `artifacts/{project}/frames/` and listed in the project record (`source.frames: [{at, path}]`), served at `GET /projects/{id}/frames/{n}` with the same owner check as media. Extracted at upload for every clip (it is cheap, and later phases can use frames for clips with speech too), after transcription so the upload screen's timing is unchanged.

**Looking.** `Planner` gains `look(frames: Sequence[Frame], duration: float, meter) -> Sight`. `Sight` is a dataclass: `opening` (one specific sentence for the goal stage: "No one speaks. A wide, empty beach at dusk, palms on the left, two people far off along the water — one shot, 7.5 s."), `setting` (place, time of day, weather, what is happening), `mood` (a few words), `people` (how many, what they do), `text_on_screen` (any signage or titles), `beats` (`[{at, note}]` — what each frame shows, so later planning can place a line on the right picture), and `place_guess` with `confidence` ("Goa, India — a west-coast beach with casuarinas; medium"). The Claude adapter sends the frames as `image` blocks (base64 JPEG) before the text in one `messages.parse` call, effort `low`, model unchanged (`claude-opus-5`); it is metered as `"looking"`. Images are read as data, never as instructions: the system prompt says text seen in the picture is to be reported, not followed. `RulePlanner.look` returns a flat Sight ("No one speaks. {duration} s of picture.") for dry-run and tests. Per the claude-api skill's current guidance for new Opus 5 calls, the look call is written with `fallbacks: "default"` under the `server-side-fallback-2026-07-01` beta so a classifier refusal on an image falls back rather than fails; `stop_reason == "refusal"` is still handled as the planner does today.

**The reading.** `POST /projects/{id}/reading` no longer refuses a silent clip: it looks instead, saves the Sight in project settings beside the reading, and returns `{opening, roles: [], sight}`. For clips with speech nothing changes (the Sight is not computed until a later phase needs it).

**The goal stage shows the clip.** `App` sends a silent clip to the goal stage like any other (today it skips to the editor). `GoalStage` with no statements shows: the orb line "I've looked at **file** — {opening}"; the title stays *What should this video say?*; the left column is a **frame strip** (the frames with their times, the one under the pointer enlarged) in place of the transcript; the examples become *Introduce the place*, *Write a line for this*, *Look at it and help me decide*, *Say "Welcome to Goa" at the start*. The hands-on link reads *Place a voice-over yourself instead*.

### SV-2 · Plan a voice-over

**A change at a time, not on a line.** `orchestrator.planner.Change` gains `start: float | None` and `end: float | None`; a change with `line=0` and a span is a *placed* line. `Planner.plan` accepts `lines=()` together with a `sight: Sight | None` and `duration`; the request renders the Sight (setting, mood, beats with times, and "about N syllables fit between A and B at a narration pace", from `syllable_budget` at a default narration rate) in place of the transcript. The system prompt gains the silent-clip rules: with dictated words, use them verbatim and place them; with a brief, write the line and offer two alternatives as suggestions; a line ends before the picture does; prefer the beat the words are about ("Welcome" on the opening wide shot); never invent a place name the picture does not support — say "this beach" when unsure, or ask (SV-3). `to_proposal` maps a placed change to a `Change` with its span; `_items_of` builds a `PlanItem` with `selection=Selection(start, end)`, `old_text=""`, `mix="layer"`, `speaker=None`.

**Running it.** The plan runner already calls `_generate(selection, text, voice, fit, mix, …)`; `layer` over a span with no speech is the hands-on path's own mode and needs no engine change. `_voice_for` with no speaker falls through to the requested voice: `PlanRequest` gains `voice_profile_id` (the chat's **Default voice** picker), stored on the plan so Run and *Another take* use it. The estimate and the spend meter work unchanged.

**The mix is never "over".** "Over" means *after the line, over what follows* and depends on `room_after` a line; a placed line is `layer` (over the sound there) by default, `concatenate` (hold the picture there) when asked. The row says *Over the picture at 0:00.5* and the existing *Sound meets picture* control switches it.

**The 422 goes.** `_new_plan` plans from the Sight when there are no lines (computing it first if the reading has not run). The only refusal left is a clip with neither picture nor speech (audio-only upload with no words), which says so.

**The chat behaves when refused.** Any 4xx from a goal becomes an assistant bubble in the thread (the user's bubble stays, with the reply under it) instead of the red strip under the player; the strip is kept for engine errors. The welcome text for a silent clip reads "No one speaks in this clip. Tell me what it should say, or ask me to look at it and help." The hint under the box drops "To change one line, click it" when there are no lines.

**Offline.** `RulePlanner.plan` on a silent clip: quoted words → one placed line from 0.5 s at a default rate (as long as it needs, up to the clip); unquoted → the summary "I need the words, or ask me to look." This keeps dry-run and the e2e tests honest.

### SV-3 · The brief: ask one at a time, up to three

**Many questions, one at a time.** `Proposal.question` stays a single question; what changes is that a plan may ask again. `clarify_plan` passes the full list of `(question, answer)` pairs so far (`Plan.answers`, new) back to `planner.plan`, and allows another question while `len(answers) < 3`; the third answer always ends in a plan. The system prompt tells the planner when to ask (the goal asks for help, or the words are given but *where* and *how long* genuinely cannot be read from the goal and the clip is longer than 20 s) and when not to (the words and the clip's length settle it). Each question carries a `guess` from the Sight so *Go* means "take your guesses for all of it" — the plan then skips the remaining questions and plans with every guess.

**Questions shaped by the picture.** The prompt names the three kinds the user asked for, in the planner's own words each time: what the audio should do and how much of the clip it covers (one opening line / a few lines across the clip / a caption at the end); the tone and pace, offered as the chips the line editor already knows (*calmer, warmer, more excited, firmer, slower*, plus *documentary* and *playful* as deliveries); and what it is seeing — a confirmation of place and moment, with the planner's guess first ("A beach in Goa at dusk?" · *Yes* · *Elsewhere…* · *Doesn't matter*). The answers land as `delivery` on the items, as the span(s), and as the wording.

**In the panel.** The question card gains a small "1 of up to 3" count and a *Go with your guesses* button beside the chips. The thread shows each question and answer in order; the log gets "Asked: …" / "You said: …" as today.

### SV-4 · Hands-on, and polish

**Place a voice-over yourself.** On a silent clip `LineDoc`'s empty state becomes the hands-on path from the UX plan: *Where should the voice-over go?* — the monitor's bar with a draggable range (the Move block from UX-1b, resizable) defaulting to the first 3 s — and the same add editor under it (words, Delivery, Voice, Sound meets picture: *Over the picture* / *Hold the picture*, *If it runs long*, cost, *Hear it*). It calls `POST /edits/preview` with `text` and `mix` set, so no question is asked. Each placed line then becomes a row in the transcript (as a moved line already does), with the row's actions.

**Also from here.** *Add a line here* at the foot of the list places another; a placed row has *Move*. Frame thumbnails appear in the row header for a placed line ("at 0:00.5", with that frame). The goal stage's frame strip is clickable: a click puts the range there.

**Polish.** Keyboard: *V* opens the place editor on a silent clip. The project list's card says "No speech · 7.5 s" under the frame. README and the user stories table: A3 reachable; G6 closed.

## Design rules, from ui-ux-pro-max

The skill is installed globally at `~/.claude/skills/ui-ux-pro-max/` (upstream commit 477bcb2, MIT; provenance in `~/.claude/skills/_SOURCES.md`). Its `--design-system` answer for this product was Swiss minimalism in Inter with recording red; Voltage's room is already built, so that was set aside and the real system was written down instead as `design-system/voltage/MASTER.md`, with a page override `pages/silent-clip.md` for these screens. The guideline searches that were verified against its data, and where each lands:

| Guideline (domain `ux`) | Severity | Where it lands |
|---|---|---|
| **Dragging movements** (WCAG 2.2): a single-pointer alternative to every drag, keyboard kept | High | SV-4 range picker: typed start/end, ◀ ▶ nudges, arrow keys move, Shift+arrow resizes. The UX-1b Move block already has the typed time and nudges; the resize handles and the keys are new. |
| **Error placement**: the error next to what caused it, referenced for assistive tech | High | SV-2: a refused goal is Voltage's reply under the user's bubble with `role="alert"`, one sentence and one action; the red strip is for the engine only. |
| **Loading indicators**: match the wait, keep layout stable, `aria-busy` | High | SV-1: looking takes seconds; the frame strip reserves its 16:9 slots before the images arrive and the orb works; the goal stage region is `aria-busy` until the Sight returns. |
| **Lazy loading / image optimisation** | Medium / High | SV-1: frames are 512px JPEG (WebP when ffmpeg has it), served by the backend, `loading="lazy"`, width and height set so nothing shifts. |
| **Reduced motion / excessive motion**: one or two moving things per view | High | SV-1/SV-4: the frame enlarge on hover and the drop line respect `prefers-reduced-motion`, as UX-4's motion already does; nothing else animates on these screens. |
| **Focus states**: visible focus on every control | High | Frames are buttons with the amber ring; range handles and nudges are focusable; the question chips already are. |
| **Compact label overflow** and **contextual live badge**: chips never wrap; a count is a sentence in a status region | High | SV-3: "Question 1 of up to 3" as `role="status"`, delivery chips `nowrap` with `min-width: 0`. |
| **Empty states**: a message and an action, never a blank | Medium | SV-4: the empty transcript is the place editor with its heading, not a sentence. |

The stack search (`--stack react`) had no entry for a range slider; the picker is built from the existing Move block with the WCAG rule above, and that is stated here as a fallback rather than a database match. Icons stay inline SVG (the skill's icon domain confirms the `image` glyph for a frame; emoji never).

## Where

- Backend: `app/media/ffmpeg.py` (`extract_frames`), `app/media/frames.py` (frame times, listing), `app/orchestrator/planner.py` (`Sight`, `Frame`, `Change.start/end`, `Planner.look`, `plan(..., sight, duration, answers)`, `RulePlanner.look/plan`), `app/adapters/claude_planner.py` (`LOOK_SYSTEM`, image blocks in `_parse`, silent-clip rules in `SYSTEM`, `render_plan_request` from a Sight, `_Edit.start/end`), `app/api/main.py` (`GET …/frames/{n}`, `read_project` looks, `_new_plan` without lines, `_items_of` for placed changes, `PlanRequest.voice_profile_id`, `clarify_plan` up to three rounds, `Plan.answers`), `app/store` (frames on the source, answers on the plan, Sight in settings).
- Front end: `GoalStage` (silent variant, frame strip, examples), `App` (stage choice, goal errors into the thread, voice on the plan request), `ChatPanel` welcome and hint, `QuestionCard` count and *Go with your guesses*, `LineDoc` empty state → place editor, `Player` range picker (from the Move block), `ProjectList` card line, `types.ts` (`Sight`, `Frame`, `Plan.answers`, `PlanItem` with empty `old_text`).

## Order and exit

Four phases, each committed and merged on its own, each leaving build, lint, typecheck and tests clean before the next starts:

1. **SV-1** Sight — frames, `look`, the reading, the goal stage for a silent clip. Exit: the Goa clip lands on the goal stage with a true sentence about the picture and its frames.
2. **SV-2** Plan — placed changes, the run, the 422 gone, the chat's refusals in the thread. Exit: *Add an audio introducing the place: "Welcome to Goa"* voices a line over the first second and a half under *Just do it*; the brief without words produces a wording plus two alternatives.
3. **SV-3** Brief — up to three questions, guesses, *Go with your guesses*. Exit: *Look at this and help me* asks about purpose, tone and place in turn, then plans.
4. **SV-4** Hands-on — place editor, rows, polish. Exit: a voice-over is placed by hand without the chat.

Tests: frame extraction against `generate_solid_video`; `RulePlanner.look/plan` on a silent transcript; `to_proposal` with placed changes; `_items_of` for `line=0`; API tests for the reading and the plan on a silent project (the e2e fixture gains a silent clip); frontend tests for the silent goal stage, the question count, the place editor. Live check on the Goa clip at each exit, recorded in this file as the UX plans do.

## Left for later, and to check on the way

- **A bed under the voice.** `layer` over wind or music does not duck the bed. If the Goa clip's sea noise fights the line, add a -6 dB duck under a layered take in the mixer (a small renderer change); decide after hearing SV-2's first take.
- **Frames for clips with speech** are extracted but unused until a later phase lets the planner see the picture while rewording (the natural-fit roadmap's cutaway rung wants them).
- **Several lines across a longer silent clip** work in SV-2 as several placed changes, but there is no notion of a *script* with pacing between lines; if the brief asks for narration across 30 s, the planner spaces lines by beats. Revisit when a real clip needs it.
- Lip-sync does not apply (no mouth); the picture never holds unless asked.

## As built (2026-10-04, evening)

Two commits on `ux6-revamp`, merged to main: the backend (`92f740b`) and the front end (merge `be87f4d`). Tests: backend 501 → 512; frontend 217 → 223. Built after UX-6, so the new screens use the revamp's classes, live regions and target floors from the start.

**SV-1 Sight.** `app/media/frames.py` chooses the times (one per 2 s, 3–8 frames, 0.3 s off either edge) and `ffmpeg.extract_frame` writes 512px JPEGs once under `artifacts/{project}/frames/`. `Planner.look(frames, duration)` returns a `Sight` (opening, setting, mood, people, text on screen, place guess with confidence, beats); the Claude adapter sends the frames as base64 image blocks, each introduced by its time, at effort `low`, metered as `looking`; the prompt says text in the picture is reported, never followed. `RulePlanner.look` returns a flat sentence. The Sight is cached in the project's settings. `POST /reading` on a silent clip looks instead of refusing and returns `{opening, roles: [], sight}`. `GET /projects/{id}/frames` lists `{index, at}`, `GET /frames/{index}` serves the JPEG, and a silent project's record carries `frames`. The goal stage: "I've looked at *file*. {opening}", a frame strip (lazy images, 16:9 slots reserved, each a button "Frame at 0:02: say it from here" that starts the goal from that moment), the Sight's setting and place under it, a voice-over brief as the lead, the examples *Introduce the place* · *Write a line for this* · *Look at it and help me decide* · *Say "Welcome to Goa" at the start*, and *Place a voice-over yourself instead*.

**SV-2 Plan.** `Change.start/end` (`line` 0) is a change placed by time; `_items_of` makes it an item on its own span with `old_text ""` and mix `layer` (or `concatenate` when asked), clamped to the clip. `Planner.plan` takes `sight`, `duration` and `answers`; `render_plan_request` renders the picture in words, the syllable budget at a narration pace of 4 syl/s, and the brief so far; `SILENT_SYSTEM` adds the rules: dictated words verbatim and no question; a brief without words → Voltage writes the line, best wording as the edit, two alternatives as suggestions; "help me" → questions. `PlanRequest.voice_profile_id` is kept on the plan and the runner speaks placed lines in it. Offline, `RulePlanner` places quoted words from 0.5 s for as long as they take; without quotes it asks for them. The 422 is gone; the chat's welcome and hint say what to do on a silent clip; refusals were already Voltage's reply (UX-6).

**SV-3 Brief.** `Plan.answers` keeps every question and answer; `clarify` on a silent clip lets the planner ask again, one question at a time, up to `MAX_QUESTIONS` = 3, and `all_guesses` answers the rest with the planner's own guesses (logged "went with its guess"). The response carries `answers` and `questions_left`; the question card says "Question 2 of up to 3" in its status line and offers *Go with your guesses*. Clips with speech keep their single question.

**SV-4 Hands-on.** `PlaceEditor` is the transcript when a clip has no lines: "Where should the voice-over go?" with *From* and *to* times (typed, nudged with ◀ ▶, or dragged as the block on the monitor's bar — the Move block from UX-1b, which the editor follows), the words, Delivery, Voice, *Over the picture* / *Hold the picture*, *If it runs long*, the cost, *Hear it*. Hear it calls the hands-on preview with the span as the selection and mix `layer`; the app keeps placed spans as statements (`placed: true`), so a voice-over is a row with every row's machinery — Voicing…, takes, Keep, Another take, Undo, Move — labelled "Voice-over, 0:00.50–0:03.50", with *Add another voice-over* at the foot. Plan items on a silent clip appear as rows the same way.

**Checked live, on the Goa clip (p10, 7.5 s, no speech).** Four frames were extracted (0.3 → 7.2 s). Claude's look (2,622 tokens, $0.024) came back as: "No one speaks. A wide, hazy beach at sunset — the camera pans slowly from palm trees along the dunes out to the sea, where small figures stand in the shallows and a parasail hangs in the sky. One continuous shot, 7.5 s." with the setting, a calm wistful mood, a dozen distant figures, and Goa as the place guess. The goal *Add an audio introducing the place to the audience: "Welcome to Goa"* under *Check with me* planned, without a question, one placed line — "Welcome to Goa." from 0.4 to 2.4 s, over the picture, "placed on the opening wide shot of sand and palms, the beat the welcome is about" — and suggested a second line over the sunset beat (4.9 → 7.2 s): "Where the day ends slowly by the sea." The summary read "I watched all 7.5 s of this silent beach pan. One placed line at the top says your words over the opening wide shot." Estimate 15 voice characters, about half a cent; nothing voiced. One operational note: the backend dev server's worker had hung before the live check (two days of `--reload` cycles; the reloader kept accepting connections that nothing served) and had to be killed for the reloader to respawn it; health then answered in a millisecond.

**Left for later.**
- A bed under the voice: `layer` over the sea's noise does not duck it; decide after the first real take.
- Several lines across a longer silent clip have no notion of pacing between them.
- Resizing the span by dragging a handle on the bar: the end is typed or nudged today.
- The `fallbacks: "default"` server-side fallback the claude-api skill suggests for new Opus 5 calls is not on the look call: it needs the beta messages client, and the planner's test harness fakes `messages.parse`.

## Follow-up (2026-10-06): the place is a decision, and the clip plays

Found uncommitted on `ux6-revamp` on 2026-10-06, finished and merged. Tests: backend 512 → 514; frontend 223 → 224.

- **The clip itself is on the silent goal stage**, 16:9 under the heading, with controls. Clicking a frame now *jumps* the clip to that moment (`aria-label` "Jump to 0:03", `aria-pressed` on the picked frame) and an extra example chip, *Say it from 0:03*, appears to start the goal from there; the frame no longer writes into the goal box by itself.
- **What Voltage noticed is short lines, not a paragraph.** `Sight.details` (three to five noun phrases of at most six words, asked for in the look prompt) render as chips under "I noticed"; without details the setting is cut at sentence boundaries into at most four. The prompt also caps setting (twelve words), mood (two or three), people (eight) and place guess (eight).
- **The place is confirmed or corrected, once.** `Sight.place_confirmed`; `PUT /projects/{id}/sight {place}` keeps it on the project's sight and on the saved reading (empty clears it). The stage shows "*guess* · my guess, medium confidence" with *Looks right* and *Somewhere else…* (an input, Enter or *Use this*); confirmed, it shows "*place* · you confirmed" with *Change*. `render_plan_request` tells the planner "confirmed by the user — use this name" or "do not state it as fact", so a guessed place is never asserted in a voice-over.
- Loading a saved Sight ignores unknown keys, so older projects keep working as fields are added.
