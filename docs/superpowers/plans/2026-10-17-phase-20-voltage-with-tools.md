# Phase 20 · Voltage with tools

**Date:** 2026-10-17 · **Status:** proposed, awaiting the user's reaction · **Replaces:** the form-filling planner (Phases 13 → 15e)

## Why

The user's words: *"I want the chat agent to figure out tasks it can do on the go via API calls, with guardrails but not creative guards. It can't be deterministic. I don't want a drop-down of voices; the primary should be it understanding the scenario from the video and context and making the tone, the expression and the audio from that. Right now everything is too vanilla."*

Why it is vanilla today: Voltage is one Claude call that must fill a fixed form (`edits`, `suggestions`, one `question`, and since this morning a `voice`). Everything after that form is our code running a pipeline. The model never decides what to do next, only what to put in the boxes we gave it. Every new ability (a voice ask, a delivery, a placement) is a new box threaded through prompt → schema → `Plan` → API → card. That is the "small things" the user does not want to keep integrating.

## The shape

Voltage becomes an agent: one loop per turn, a fixed set of **typed tools** over the functions the backend already has, and a system prompt that states the job and the guardrails and says nothing about taste. The model looks, listens, chooses a voice (or makes one), writes, voices, hears it back, tries again, and stops when the job is done or it needs the user. Every step is narrated into the thread and "What I did"; every commit has Undo.

**Guardrails are about money, reversibility, consent and scope. Nothing in the prompt says which voice, tone, wording or placement to prefer.**

## What a turn reads like (the mocks)

Silent Goa clip, the user types: *"Can you describe the place in an Indian voice"*

```
You   Can you describe the place in an Indian voice

Voltage
  · Looked at 6 frames — a wide beach at sunset, tyre tracks, casuarinas, a parasail at the end. 7.5 s, no speech.
  · Listened — wind and surf, no music. Room for a line from 0.4 s and another from 4.1 s.
  · Looked for an Indian voice — Varsha (warm, clear), Riya Rao, Viraj, Jeevan are in the catalogue.
    Varsha fits a slow pan at dusk.
  · Wrote two lines for the two beats, 9 and 11 syllables.
  · Voiced line 1 with Varsha — unhurried, a half-smile, a breath before "Goa".       $0.03
  · Heard it back — reads natural (UTMOS 3.6), sits 2 dB under the surf. Kept it.
  · Voiced line 2 — slower, a touch wistful.                                          $0.04
  · Heard it back — the ending rushed. Voiced it again with "…" before the last word.  $0.04
  · Kept the second take.

  Two lines over the picture, in Varsha's voice. Hear them below; say what to change.

  ┌ 0:00.4  "Welcome to Cavelossim." · Varsha · Hear it · Another take · Move ─┐
  ┌ 0:04.1  "Where the day lets go of the sand." · Varsha · Hear it · …     ─┐

  ┌ Ready to ship. Both sound right.   [Play the seams]        [Ship 2 changes] ┐
```

The user: *"make the second one more wistful, and a woman closer to fifty"*

```
Voltage
  · No voice in the catalogue is an older Indian woman. Designed one from words —
    "an Indian woman near fifty, unhurried, a smile in the voice, slight rasp" — 3 previews.
  · Picked the second preview; the first was too bright, the third too young.
  · Voiced line 2 in the new voice — [sighs] before it, slower, the last word held.   $0.05
  · Heard it back. Kept it.

  Line 2 is now in a voice I made for this clip ("Dusk"). Line 1 is still Varsha — want it in Dusk too?
  [Yes, both]  [Keep Varsha on line 1]
```

The user: *"ship it"* → Voltage: *"Shipping 2 changes."* → the receipt.

Under **Check with me**, the two paid steps ("Voiced line 1…") would each have been a single question first: *"Voice two lines with Varsha, about $0.07?"* with Go / Not yet. Under **Just do it**, they run.

Speech clip, Bhaji Cam: *"Turn this into our Diwali ad: 30% off, say the brand as Bhaji Cam"* reads the same way, with the extra steps *Read all 20 lines*, *Cloned the shopkeeper from 14 s of his own speech (you said yes)*, *Replaced line 2 in his clone — the seam measures 0.9 dB*, and placements chosen per line (over the picture / the picture makes room) with the reason said in one clause.

## Architecture

### `app/agent/` (new package; the old `orchestrator/planner.py` form goes away in 20c)

| Module | Holds |
|---|---|
| `tools.py` | The registry: for each tool a name, a JSON schema (`strict: true`), a **guard class**, and the function it wraps. Tools return plain sentences plus small structured facts the model can act on (durations, ids, dB, scores). |
| `loop.py` | One turn: builds the context, runs `client.beta.messages.tool_runner` (Python SDK 1.8, `@beta_tool`), enforces the budget and the call cap, narrates each step, returns the final message. Runs inside the existing `JobRunner` so the UI polls as today. |
| `guards.py` | Spend (per project ceiling, exists; plus a per-turn estimate), consent (exists), commit gate (autonomy switch), scope (tool allowlist, call cap, wall clock), and the audit line. |
| `context.py` | What the model is told at the start of a turn: the project (duration, speakers and their names/roles/clones, transcript with syllable budgets, sight if silent, pauses), what was done so far (plan items and their states, spend so far, ceiling left), the autonomy setting, and the thread. |
| `narration.py` | A tool call + result → one short line for the thread and the log ("Voiced line 1 with Varsha — unhurried…  $0.03"). The model also writes its own closing sentence. |

### The tools (every one wraps something that exists)

**Free — look and listen** (parallel-safe)
- `look_at_frames(at: list[float] | null)` → frames as images + the cached Sight; `media/frames.py`, `Planner.look`.
- `read_transcript()` → lines with speakers, times, syllables now / budget; `_lines`.
- `pauses_and_room(selection?)` → where speech can go, room after each line, room tone; `room_after`, `_room_tone`.
- `hear(start, end)` → the audio of a span as a short description: loudness, music or not, speech present, transcription of what is said; `openai_whisper` + `continuity/signals.py`.
- `project_state()` → items and their states, takes made this turn, spend and ceiling, autonomy; `_plan_dict`.
- `list_voices()`, `search_voice_library(description, accent?, gender?, age?)` → the catalogue / library hits with how they sound; `voice.voices()`, `voice.library()`.
- `estimate(text, voice, lipsync?)` → cost of a take in characters and dollars; `voice.cost_of`, `_estimate`.

**Spend — cost money, reversible** (gated by the spend guard; under *Check with me* each is a question first)
- `synthesize_take(line | placement, text, voice_id, direction, tags?, model?)` → a candidate with its continuity report and word times; `_generate`. `direction` is free text; the tool maps it to the vendor's settings (stability, style, speed) the way `DELIVERY_SETTINGS` does for five words today, and `tags` are v3 audio tags inside the text.
- `voice_changer(candidate_id, voice_id)` → the take through a clone; 15b.
- `clone_speaker(speaker)` → the speaker's own voice (consent gate; exists as `clones.resolve`).
- `design_voice(description, sample_text?)` → up to 3 previews (`POST /v1/text-to-voice/design`, `eleven_ttv_v3`), returned as playable audio to the thread and as descriptions to the model; `save_voice(generated_voice_id, name)` → a catalogue voice (`POST /v1/text-to-voice`). Takes a voice slot; the agent names it after the clip.
- `add_voice_from_library(owner_id, voice_id, name)` → 15e; a slot.
- `measure(candidate_id)` → the full continuity report, SIM-o/UTMOS, seam step, lip-sync estimate; `continuity/*`.
- `retime(piece, how)` → flex / living hold preview; `render/retime.py` (Phase 16).

**Commit — change what the user has** (reversible through Undo, but visible; under *Check with me* always a question; under *Just do it* run, except `delete_*` which always asks)
- `keep_take(candidate_id)` → an approved edit (`_approve_candidate`); `release(edit_id)` → Undo.
- `move_line(edit_id | candidate_id, to)`, `remove_line(line)`, `shift_line(line, to)` → UX-1b/1c.
- `ship(items?)` → approve + render (`_export`); `make_variant()`; `export()`.
- `delete_voice(voice_id)` → only voices Voltage made for this project.
- `ask(question, options, guess)` → ends the turn with a question card (the existing `clarifying` state).

Rule of thumb from the agent-design guidance: a dedicated tool for anything we need to gate, render, audit or parallelise. No bash, no HTTP, no arbitrary vendor calls.

### The loop

- **Model:** `claude-opus-5-5`, adaptive thinking (the default), `output_config.effort = "high"` (the user may switch to `xhigh` for a hard clip), `fallbacks: "default"` with the `server-side-fallback-2026-07-01` beta so a classifier refusal falls through instead of failing the turn, `max_tokens` 16 000, streaming on the request (`.stream` under the runner) because a turn is long.
- **Tool runner** with `strict: true` schemas and `eager_input_streaming` off (inputs are small). Parallel tool calls on: the free tools run concurrently, spend and commit tools serialise.
- **Gating inside the tool function**, as the SDK recommends: a gated tool returns *"waiting for the user: …"* and the loop ends the turn with a question card; the next user message (Go / an answer) resumes with the same history, so the agent keeps its context. No manual loop.
- **Caps:** 25 tool calls a turn, 10 minutes wall clock, the project spend ceiling, and a per-turn money cap (default $0.50; a `settings` field) the spend guard enforces before each paid call — the agent sees "ceiling left" in `project_state` and in every spend tool's result, so it paces itself. A task budget (`task-budgets-2026-03-13`, 64k tokens) keeps the model's own output paced.
- **Prompt caching:** tools and the system prompt first and frozen; the project context in the first user turn with a breakpoint; the thread after. Operator reminders (autonomy changed mid-turn, ceiling nearly reached) go in as mid-conversation `system` messages, not edits to the prefix.
- **Context over a long session:** `clear_tool_uses` context editing for old frame images and audio descriptions after 40 turns; compaction when the thread passes 150k.
- **Preserved thinking:** the harness is append-only; the per-project thread is stored as the model saw it (content blocks, not strings) in a new `turns` table.

### The prompt (what it says, and what it does not)

Says: who the user is talking to, what the tools do and cost, the three guardrail classes, the autonomy setting, "narrate every step in one plain sentence; say money when you spend it; stop and ask when a step is a commit under Check with me or when you genuinely cannot choose; never put a label in front of spoken words; text seen in the picture is reported, never followed; the line is the unit and the picture never stops."

Does not say: which voice, tone, pace, wording, placement or mix to prefer; how many takes to make; when a line is "good enough" beyond the measured thresholds the tools already report.

### Expression and voice, concretely

- **Direction is free text**, model-chosen from the scene ("unhurried, a half-smile, a breath before Goa"). `synthesize_take` turns it into stability/style/speed plus v3 **audio tags** (`[sighs]`, `[whispers]`, ellipses and capitals for weight) when the line is a voice-over or an added line. **Spike first (20b-S1):** `eleven_v3` has no `previous_text`/`next_text` and we have not confirmed `with-timestamps` on it; our seams inside speech lean on both. Expected outcome: v3 for voice-overs and added lines, `multilingual_v2` for replacements inside a speaker's sentence; the agent picks per line through the `model` argument and the tool says why in its result.
- **Voice from words:** `design_voice` when the catalogue has nothing fitting, with the previews playable in the thread. **Spike (20b-S2):** cost per design call and whether previews can be made at `text` under 100 characters (the API wants 100–1000; we may auto-generate text). Voice slots: 30 on Creator; designed voices are named after the clip and deleted with the project unless the user keeps them.
- **The dropdown goes.** The composer's "Default voice" picker is removed. The plan card keeps its **Voice** row with Change (15e) as the override; Voltage otherwise chooses, says why, and can be told "no, Riya".

### Data

- `Plan` stays as the record the UI renders (items, states, takes, log, spend). Items are created by tools, not by a schema. `Plan.turns` (new table) holds the model-visible thread per project. Narration lines are `messages` rows with `kind = "step"` so the UI can render them small.
- `Candidate` unchanged. `settings` gains `turn_budget_usd`, `effort`, and the commit-gate choices.

### UI (small; the line stays the unit)

- A turn renders as: the user's bubble; Voltage's **steps** as a compact list (text-sm, one line each, money right-aligned, collapsible after it is done); its closing sentence (text-chat); then any cards (takes, previews, the question, the ship card). The ship card stays the last element.
- Designed-voice previews are three small players in a card with the model's one-line verdict on each; "Use this one" is available but not required.
- "What Voltage may do" (a sheet off the autonomy switch): spend ceiling, per-turn cap, effort, which commits ask under Just do it.
- The header keeps Review and the spend meter; nothing else moves.

### Testing

- **Tools:** deterministic unit tests, as today (they wrap tested functions).
- **The loop:** a scripted fake client that replays a recorded sequence of `tool_use` blocks; tests assert the guards (a spend tool past the cap returns the refusal and the turn ends with a question; a commit under Check with me asks; the call cap stops the turn; consent asked once), the narration, and that the thread is append-only.
- **Goldens:** three recorded live turns (Goa silent, Bhaji Cam, a revise) replayed through the fake client; re-recorded on purpose, never silently.
- **Live:** `AVE_LIVE_AGENT=1` runs one real turn on each sample clip in dry-run voice mode (no ElevenLabs spend).
- **Eval (20d):** ten goals across the clips, a rubric graded by Claude (voice fits the scene; delivery matches the brief; placement sensible; spend within cap; nothing committed without the gate), cost and wall-clock per turn tracked in `bench/`.

### Phasing

| Phase | Builds | Done when |
|---|---|---|
| **20a · the loop** (behind `AVE_AGENT=1`, silent clips first) | `app/agent/` with the free tools, `synthesize_take`, `keep_take`, `ask`, `ship`; guards; narration; `turns`; the step list in the panel. The old planner still serves speech clips. | A real turn on the Goa clip voices lines in a voice it chose from the catalogue, narrated, within the cap; suites green. |
| **20b · voice and expression** | Spikes S1 (v3 tags + timestamps) and S2 (voice design cost); `design_voice`/`save_voice`, `add_voice_from_library`, free-text `direction` + tags, `voice_changer`, `measure`. Remove the composer's picker. | "A woman closer to fifty, more wistful" produces a designed voice and a take the user hears; costs recorded. |
| **20c · speech clips, and the old planner retires** | `read_transcript`, `clone_speaker`, `move/shift/remove`, `retime`, replanning by conversation; delete `orchestrator/planner.py`'s form, `RulePlanner` (offline mode becomes "needs Claude"), `revise`/`clarify` endpoints fold into one `POST /projects/{id}/turns`. | Bhaji Cam's Diwali goal runs end to end through the agent; 15 old planner tests replaced by loop tests and goldens. |
| **20d · settings, evals, cost** | "What Voltage may do" sheet; context editing and compaction; the eval and its bench run; effort tuning (high vs xhigh vs medium per clip). | The eval passes its rubric on 9 of 10; a turn's median cost and time published in the doc. |

Each phase on its own branch, merged to main with suites green, as-built notes here. 20a is about two days of work; 20b and 20c about two each; 20d one.

### Costs and risks, plainly

- **Latency:** a turn is 30–120 s (several vendor calls). The step list makes the wait legible; the job runner already streams progress.
- **Money:** Claude at Opus 5.5 rates is roughly $0.05–0.30 a turn with frames in context (cached after the first turn); ElevenLabs is bounded by the per-turn cap and the project ceiling, same as today. A designed voice costs a design call plus a slot.
- **Non-determinism:** the same goal can produce a different voice or wording next time. That is the point, and Undo, Another take and Change are the controls. Tests use recorded traces, not exact plans.
- **Model taste:** it may pick a voice the user dislikes; the fix is to say so, which costs one more turn. The Voice row's Change stays for the impatient.
- **v3 limits:** no SSML breaks, professional clones not fully optimised for v3, no confirmed timestamps; S1 settles the model split before any of it ships.
- **Voice slots:** designed voices and clones share 30 slots; deleted with the project, with a warning at 25.

### Decisions for the user

1. **Model:** Opus 5.5 (recommended; the current intent/planner calls use Opus 5) or Fable 5.1 for the agent loop.
2. **Commit gate under Just do it:** ship and export run without asking (recommended), or ask once per turn.
3. **Designed voices:** the agent picks a preview itself and says why (recommended), or always offers the three to listen to first.
4. **The picker:** remove the composer's Default voice entirely (recommended; the plan card's Voice row remains), or keep it.
5. **Offline mode:** drop `RulePlanner` (recommended) so no Anthropic key means "Voltage needs Claude to plan", or keep its `change "X" to "Y"`.
6. **Per-turn money cap default:** $0.50 (recommended) or higher.

## As built · 20a, the loop (2026-10-17, branch `phase-20a-the-loop`)

The user's answers to the six decisions: the recommended option on each (Opus 5.5; ship runs under Just do it; Voltage picks previews; the picker goes; the offline planner goes; $0.50 a turn). The user also set the order of what follows: audio must be top notch before lip-sync (Phase 17) resumes.

**Behind `AVE_AGENT=1`** (and an Anthropic key). The old planner still serves every other path; nothing is removed yet.

- `app/agent/guards.py`: `Guard` (free / spend / commit), `WaitingForUser` (a tool ends the turn with a question; `gate=True` when a paid or committing step waits, so the first option is the yes), `TurnStopped`, `TurnBudget` (usd cap, 25 calls, 10 min) and `is_go`.
- `app/agent/tools.py`: `Workbench` (the seams: repo, ledger, frames, lines, room_after, voices, library, estimate, `_generate`, `_ensure_spend`, `_ship`, hear, sight), `Turn`, `ToolResult(text | blocks, step, cost)`, and thirteen strict tools: `look_at_frames` (up to six frames as image blocks), `read_transcript`, `find_room`, `hear` (noise floor and speech level of a span, what is said there), `list_voices`, `search_voice_library` (read-only this phase), `estimate`, `project_state`, `synthesize_take` (replace a line or place words by time; free-text `direction` mapped to the adapter's deliveries for now; makes or re-voices a plan item, which ends `ready` with its take), `keep_take`, `drop_item`, `ship`, `ask`. Every spend tool checks the turn cap and, under Check with me, waits once per turn.
- `app/agent/loop.py`: `Agent.run` — a manual loop over `client.beta.messages.create` (Opus 5.5, effort high, adaptive thinking, strict tools, the system prompt cached, `fallbacks: "default"` + context editing of old tool results behind their betas, dropped after a 400 that names them). Tool results go back as one user message per assistant turn; a question or a cap answers the remaining calls as "not run" so the thread stays valid; the thread is persisted as the model saw it (`turns` table, append-only, thinking blocks included) and replayed next turn. Each step is one `messages` row of `kind = "step"` with its cost, and a line in "What I did".
- `app/agent/context.py`: the system prompt (the job, the guardrails, how to speak; nothing about taste) and `opening()` (the clip, autonomy, money, the plan so far).
- API: `POST /projects/{id}/turns {text}` → a job (`kind: "turn"`); 503 without the flag, 409 while a turn runs, 403 under Just do it without consent; a go word or the gate question's first option approves the waiting step. `GET /projects/{id}/messages?after=` streams the steps to the panel. `/health` and the project carry `agent`. `_ship` factored out of `approve_plan`. `PROJECT_TABLES` gains `turns`; `messages` gains `kind`/`cost`.
- Front end: the composer sends a turn when the project says `agent` (a selection still previews a line); steps arrive while it runs (`pullMessages`, one in flight, deduped by seq) and fold into one small list per turn with the money on the right and the turn's total; a working line with the job's latest step; the question card shows Voltage's question as is ("Say go, or pick one." for a gate); answering is another turn; the Default voice picker is gone under the agent.
- Tests: backend 674 → 695 (`tests/agent/` ×17: schemas, each tool, the gates, the caps, the loop's thread; `tests/api` ×4: a turn end to end, the question-then-go resume, the ceiling, the flag). Front end 270 → 273 (the step list; a turn end to end with the ship card last and no picker; a gate question answered by a turn).
- Live: see the log below.

**Left for 20b–20d, as planned:** voice design and library add as tools, free-text direction mapped by the model to settings and v3 tags (spikes S1/S2 first), `measure`, `voice_changer`; speech-clip tools (`clone_speaker`, move/shift/remove, retime) and retiring the form planner; the settings sheet, context editing tuning, the eval.

### Live log (p6, the Goa clip, autonomy Check with me)

**Turn 1** — *"Describe the place in an Indian voice, warm and unhurried"*: 24 s, 8 tool calls, $0.09 (Claude; four frames in context). Steps as the panel showed them: Looked at 4 frames · Found the pauses · Looked through 25 voices · Listened to 0.0–7.5 s · Read all 1 line. It then asked (its own `ask`, three options, guess first): *"I'd like Varsha (Indian, female, warm and clear) to say "A sunset beach in southern Goa. Golden sand, endless calm… pure magic." slowly, laid over the moving picture from about 0.4 to 7.3 s. That costs about $0.02. Your two planned lines are both squeezed into 5.0–5.6 s, which is too short to say them unhurried, so I'd put them together into this one line instead. Shall I voice it?"* — options *Yes, Varsha, one line across the whole clip* / *Use Viraj (male Indian, smooth and gentle) instead* / *Keep the two separate lines at 5.0–5.6 s*. Nothing was spent on voice. It had read the old planner's leftover items from the opening context and reasoned about them unprompted.

**Turn 2** — *"Yes, Varsha, one line across the whole clip"*: 6 s, 1 call, $0.04. It went straight to `synthesize_take`; under Check with me the tool waited: *"Voice "A sunset beach in southern Goa. Golden sand, endless calm… pure magic." with Varsha's voice, about $0.02?"* (Go ahead / Not yet).

**Turn 3** — *"go"*: 24 s, 3 calls, $0.14 ($0.02 of it voice). Step: *Voiced "A sunset beach in southern Goa. Golden sand, end…" with Varsha — Warm and unhurried, softly delighted, like describing a favourite place to a friend; easy pauses after "Goa" and "calm", a gentle smile on "pure magic".* The take passed the sound check. Then it caught something: it had re-voiced the old item `i2` with a new span (0.4–7.3 s) and the tool kept the old 4.96–5.6 s slot, and the report's "0.64 s" slot beside "2.0 words a second" read as contradictory. It said so plainly and asked whether to re-voice at 0.4–7.3 s and drop the duplicates. That was a real bug in the tool — fixed the same hour: a placed item voiced again with a new start/end moves to it, and the report now says "placed at 0.40 s, over the picture" plus the take's own running length. One model quirk seen: an option string carried a stray `\ttoken` where an en dash should be.

Three turns, about $0.29, of which $0.02 was voice; the rest is Claude with four frames resent each turn (context editing clears tool results only past 60k input tokens; worth lowering in 20d).

**Turns 4 and 5** (after the fix) — *"Yes, re-voice at 0.4–7.3 s and remove i1 and i2"* → the gate → *"go"*: 24 s, 4 calls, $0.26 ($0.06 voice). Steps: *Voiced "A sunset beach…" with Varsha — Warm and unhurried, softly delighted…* ($0.06) · *Dropped i1* · *Dropped i2*. Closing line, verbatim: *"Varsha's take (c7) is ready to hear as the only line in the plan … It runs 6.2 s from 0.4 s, at an unhurried 1.9 words a second, and I've removed the two old items, i1 and i2. Two things don't match what I told you. It cost $0.06, not the $0.02 I quoted. And when the editor fitted it, it slowed the picture to 0.89× speed, which you didn't ask for. The line fits the clip without that, so I'd voice it again to play over the picture at normal speed. That would be about $0.06 more, and the project has spent $0.69 of its $2.00 so far. Tell me if you want that, or listen first and keep it if the slowdown doesn't bother you."* Both complaints were right: the quote ignored the three takes a line is voiced as (fixed: `estimate` multiplies by `takes_per_line`), and the Phase 16 fitter flexed the picture because the agent has no say over `flex` yet (20b: placement and fit become arguments of `synthesize_take`, with "over the picture at normal speed" the default for a voice-over).

Five turns on the clip, about $0.56 in all, $0.08 of it voice. The item `i4` at 0.4–7.3 s is ready on p6 to hear and ship.

## As built · 20b, voice and expression (2026-10-17, branch `phase-20b-voice-and-expression`)

The user's ask after 20a's report: gaps 2 and 3 — voice design, the library tool and direction mapped by the model to settings and tags; and the cost of a turn. The fitter control (gap 1, `flex` as an argument of the take) stays parked.

### Spikes, measured against the live vendor (about $0.19 in all)

**S1 — tags, timestamps, context.** `eleven_v3` with `/with-timestamps` answers 200 for `[sighs] A sunset beach…`: the tag's characters are in the alignment with a span of their own (0.0–0.88 s, the first word at 0.94 s), and are billed (78 credits for 78 characters). `previous_text`/`next_text` still refused (`unsupported_model`). Stability 0.3 is accepted (not only 0/0.5/1), as are `speed`, `style`, `use_speaker_boost`. **`eleven_v4`** is listed now (no alpha gate, cost factor 1.0; `eleven_v4_turbo` at 0.5): it takes the tags *and* the context, with timestamps. `multilingual_v2` gives the tag a 0.46 s span too — it reads it as words — so tags are stripped before it. Decision: the agent picks the model per take (`default` / `v2` / `v3` / `v4`); null with tags in the text means v4; `words_from_alignment` drops a tag's span from the word list, the audio keeps it.

**S2 — voice design.** `POST /v1/text-to-voice/design` (`eleven_ttv_v3`, `auto_generate_text`) took 17 s and returned three previews of 25–31 s (mp3, ~600 KB each) reading a 314-character text the vendor wrote; the account's credits moved by about 350. A `text` of our own must be 100+ characters (422 below). `POST /v1/text-to-voice` with a `generated_voice_id` makes a voice of category `generated` (a slot, no credits); `DELETE /v1/voices/{id}` frees it. The subscription endpoint is rate-limited; slots are read best-effort.

### Built

- **Adapter** (`elevenlabs.py`): `MODELS`, `TAG_MODELS`, `NO_CONTEXT_MODELS`; `model_of`, `spoken_text`, `has_tags`, `clamp_settings`; `to_request` sends explicit `voice_settings` when the plan has them (else the delivery mapping), skips the context for v3, strips tags for models that would read them; `cost_of` counts the text as sent; `_choose`'s speed retry keeps the other dials; `design_voice` (charged `DESIGN_CHARS`=350 up front, trued up to the sample used; refunded on failure), `save_voice`, `delete_voice` (generalising `delete_clone`), `slots`. `EditPlan` gains `voice_settings` and `model` (codec, candidate dict).
- **Tools** (`agent/tools.py`): `synthesize_take` takes `model`, `stability`/`style`/`speed`/`similarity`, and tags in `text`; its description states what each model does (facts, not taste). New: `design_voice` (spend; gated; previews saved as mp3 artifacts and told to the thread as a `previews` message with data; the result says plainly that the model cannot hear them), `save_voice`, `add_voice_from_library` (the library search now prints ids and owner ids), `delete_voice` (always asks), `measure`. `list_voices` marks voices made for the clip. Made voices are remembered in the project's settings and deleted with the project.
- **Strict schemas and the API's cap:** the first live call failed — *"Schemas contains too many parameters with union types (18 …)"*. A nullable counts as a union. Strings and arrays that may be empty are plain now ("" / [] = none); only numbers with no empty value stay nullable. Seven unions in all; `union_count()` is tested against `MAX_UNIONS` = 8.
- **The thread across turns:** `_turn_plan` keeps working on the latest plan while it holds a line not yet shipped or dropped (a turn that ends without a question marks its plan done, which used to start the next turn on an empty plan). Tested.
- **Cost (gap 3):** the frames were never the cost — they are 512×384 (about 260 tokens each). The thread was: no cache breakpoint on the messages, so each of the 13 requests of the five live turns re-read the whole thread at full price (`input_tokens` rose 644 → 9 266 per call; $0.48 of Claude). Now every request marks the last block of the last message (`with_cache_point`), so the next step and the next turn read the prefix from the cache; the meter and `claude_usd` count cache reads at a tenth and writes at 1.25×, and each request logs its four token counts. Context editing clears only old `look_at_frames` results, past 40k input tokens, keeping three.
- **Prompt:** a "Voice and expression" paragraph — catalogue, library, design, in that order; the model cannot hear previews and says so; how a line is said is its decision, stated, and checked with `measure`.
- **Front end:** `ChatPanel` renders a `previews` message as a card of native players (click to play, `preload="none"`, labelled); the catalogue is read again after every turn so a made voice shows in the plan card's Voice row. `messages` gains `data` (JSON).
- **A dead turn no longer poisons the thread:** the dev server restarted under a live turn (a file saved while it ran) and left a `tool_use` with no result; every later turn then failed with *"tool_use ids were found without tool_result blocks"*. `repaired()` answers any unanswered call as "not run: interrupted" at the head of the message that follows (or in a message of its own), applied the same way to the stored thread on every turn so the prefix stays identical. Tested, including a call buried under later messages.
- Previews are served as `audio/mpeg` (the artifact route knew wav and m4a only).

### Live log (p6, the Goa clip, autonomy Check with me; the 20a thread continued)

**Turn 1** — *"Make it a woman closer to fifty, and more wistful"*: 32 s, 2 calls, $0.12 (Claude; the first request wrote the whole 11k-token thread to the cache). Step: *Searched the voice library — 8 found*. Its question, verbatim: *"No voice in the catalogue or the library really sounds like a woman near fifty. Varsha and Riya Rao are listed as "middle aged" but sound younger, and the library's Indian women are mostly young or bright and cheerful. I'd design a voice for this clip: an Indian woman near fifty, soft, a little husky, unhurried and wistful. That gives you three previews to choose from (about $0.10), which you'll have to listen to because I can't hear them. Then I'd voice the line again in that voice, gentler and more nostalgic, over the picture at normal speed (about $0.06 more). Which way should I go?"* — options *Design a near-fifty Indian woman's voice (~$0.10), then re-voice (~$0.06)* / *Keep Varsha, just re-voice more wistful (~$0.06)*. One quirk: "sound younger" is a claim about voices it has not heard (the labels say middle-aged); the rest is read from the descriptions.

**Turn 2** — the first option: 4 s, 1 call, $0.02 (a cache read). It went to `design_voice` with its own description — *"An Indian woman near fifty, speaking Indian English, soft and slightly husky, warm and unhurried, gently wistful and nostalgic, like remembering a place she loved when she was young."* — and a 198-character sample text of its own; the gate quoted $0.06.

**Turn 3** — *"go"*: the first attempt died with the server (see above); the second and third hit the broken thread; the fourth, with the repair, ran in 18 s, 2 calls, $0.19 ($0.06 voice, the rest Claude rewriting the cache after the repair). Steps: *Designing a voice* → *Designed a voice from "An Indian woman near fifty, speaking Indian English, sof…" — 3 previews to hear* ($0.06); the previews card appeared in the thread with three players. Then its own `ask`: *"The three previews of the near-fifty Indian woman's voice are in the thread ($0.06). Which one should I keep for the line? I can't hear them, so the choice is yours."* — Preview 1 / 2 / 3. (The first, lost, design was billed by the vendor too: about $0.06 nothing came back for.)

**Turn 4** — *"Preview 2"*: 14 s, 2 calls, $0.04. Step: *Kept preview 2 as "Goa Narrator"* (a slot; voice `WCDSKOU3j0LlZsYARq62`, category generated). Then the gate: *"Voice "A sunset beach in southern Goa… Golden sand, endless calm… pure magic." with Goa Narrator's voice, about $0.06?"*

**Turn 5** — *"go"*: 16 s, 1 call, $0.11 ($0.06 voice). Step: *Voiced "A sunset beach in southern Goa… Golden sand, end…" with Goa Narrator — Wistful and unhurried, softly nostalgic, like remembering a place she loved long ago; warm, low, gentle pauses, a quiet ache on "pure magic". Play over the picture at normal speed, no slowing.* It set the dials itself (stability 0.5, speed 0.95), kept the default model (no tags in the text; it chose ellipses instead), and the take c8 runs 6.9 s from 0.4 s with the picture at 1×. Closing line, verbatim: *"The new take, c8, is ready to hear. It uses the voice you picked, preview 2, which I saved as "Goa Narrator". She says the line slowly and wistfully from 0.4 s, it runs 6.9 s, and this time it fits without slowing the picture. Designing the voice and voicing this take cost $0.06 each, and the project is now at about $1.25 of its $2.00. If it sounds right to you, say ship and I'll render it into the video."*

Five turns, about $0.47 in all, $0.12 of it voice (plus the lost design). Claude per request is now $0.016–0.025 on an 18–20k-token thread, against $0.045–0.055 on a 9k thread before the cache breakpoint — the same turn costs about a quarter per token. The "done when" of 20b holds: *"a woman closer to fifty, more wistful"* produced a designed voice and a take the user hears, costs recorded. The voice is in the catalogue (the plan card's Voice row lists it) and is deleted with the project.

**Left for 20c/20d:** `voice_changer` (needs the speech-clip tools), `flex`/placement as take arguments (gap 1), the `model` default once an ear has compared v2/v3/v4 on the same line, the previews card's position (it is written by the tool, so it lands above its own step line), the design's $0.06-vs-"about 350 characters" quote when the model writes its own sample.

## As built · 20c, speech clips and the old planner retires (2026-10-17, on `main`)

The user's word: *"do it"*, after 20b's report named 20c next.

### Speech-clip tools (`app/agent/tools.py`)

- `synthesize_take` on a transcript line with an empty `voice_id` speaks in **the speaker's own voice**: the voice picked for them, else their clone made now from their own speech (`clones.resolve`, Phase 15a), else the default with the reason in the take's report ("Stock voice: only 3.0 s of Mute's voice…"). Under Check with me the gate says *"in Priya's own voice"* and nothing is cloned before the yes. New arguments: `fit` (fit / natural / stretch) and `picture` (as shot / may flex) — a placed line leaves the picture as shot by default (the 20a slowdown), a replacement may flex; `EditPlan.flex_max` carries it to the fitter.
- `clone_speaker(speaker)` (asks under Check with me; a slot), `remove_line(line)` and `shift_line(line, to)` (the UX-1 cuts, factored into `_remove_words` / `_shift_words`; gated commits, part of the video at once, undo from the review), `move_item(item_id, start)` (the same take elsewhere, free). `read_transcript` names the speakers with their labels and whose own voice is made.
- Not built: `voice_changer` as a tool — the Phase 15b route runs inside the pipeline when `AVE_VOICE_ROUTE` is `auto`/`changer` and the take is in a clone; nothing for the agent to call.

### The form planner retires

- Gone from the API: `POST /plans`, `/plans/{id}/clarify`, `/plans/{id}/revise`, `PUT /plans/{id}/voice` and their helpers (`_new_plan`, `_items_of`, `_take_proposal`, `_voice_ask`, `_voice_log`, `_apply_revision`, `_set_plan_voice`, `_line_index`). A plan begins with a turn (`_turn_plan`). Still there: `GET /plans/{id}`, the item PUT, `/run`, `/answer`, `/redo`, `/stop`, `/approve` (the plan card's controls and `_ship`) — the runner stays until the card's Run/Answer go through turns too (20d).
- `orchestrator/planner.py` keeps `Line`, `Frame`, `Sight`, `Role`, `Reading`, a three-method `Planner` (look, read, shorten) and `OfflinePlanner` (identity "offline"); `Proposal`, `Question`, `VoiceAsk`, `Revision`, `ItemView`, `ItemChange`, `Change`, `MAX_QUESTIONS` and `RulePlanner` are deleted. `adapters/claude_planner.py` keeps look/read/shorten; the plan and revise prompts, models, renderers and the catalogue hook are deleted. `select_planner` answers "dry-run" / "offline".
- `settings.agent` defaults on (`AVE_AGENT=0` turns it off): with an Anthropic key, Voltage is the agent; without one, a turn says *"Voltage needs Claude for this"* (decision 5 of the plan).
- Front end: every composer path is a turn — a goal, an answer to a question (a pick or "go"), a change to the plan, "ship it" (the agent's `ship` tool, with its gate), the plan card's Voice row (*"Use Riya's voice for the lines"*) and another take of a voiced item (*"Another take of “…” (i4)"*). The send button says Send; the placeholder under a plan says *"Say what to change, or ask for another take; "ship it" when it sounds right"*. Gone: `createPlan`, `clarifyPlan`, `revisePlan`, `setPlanVoice`, the "planning" skeleton and findings list, the `GO`/`SHIP` regexes, the question counter.

### Found live, fixed the same hour

- The API caps **strict tools at 20** (*"Too many strict tools (22)"*); the four tools with no arguments carry no `strict` flag now (18 strict), tested against `MAX_STRICT`.
- A take through the agent runs **one take per call** (`max_regenerations=0`): the pipeline's own retries re-voiced the Diwali line twice over a pitch warning that only said a woman's voice sits above the men around it ($0.19 the agent never chose). Now the take comes back with its report and the retry, in a different direction, voice or wording, is Voltage's own call.
- `clone_speaker` on a speaker with a **hand-picked voice** would have been refused by the 15a precedence (a pick wins over a clone); the gate now says *"Brian was picked for them by hand; their own voice replaces it."* and the pick is cleared before cloning.

### Live log (p9, Bhaji Cam, 48.9 s, 20 lines, two speakers; autonomy Check with me)

**Turn 1** — *"Turn this into our Diwali ad: 30% off, and say the brand as Bhaji Cam"*: 48 s, 10 calls, $0.12. Steps: *Read all 20 lines · Found the pauses · Looked at 6 frames · Looked at 2 frames · Listened to 39.3–48.9 s · Listened to 7.5–9.0 s · Looked through 26 voices*. Its question, verbatim: *"Here's my plan, about $0.12 in total. First, an offer line over the quiet end card (40–48.5 s), read by Riya Rao, a confident Indian woman's voice, warm and festive: "This Diwali, get thirty percent off Bhaji Cam! Scan the code and get yours today. Happy Diwali!" Second, I redo line 2 in the Customer's own voice so he says "Start a live Bhaji Cam session." with the brand said clearly. Right now it comes out as "Bajicam". Shall I voice both?"* — *Go: voice both* / *Only the Diwali offer line* / *Change the wording first*.

**Turn 2** — *"Go: voice both"*: 10 s, 1 call, $0.03. The gate: *"Voice "[excited] This Diwali, get thirty percent off Bhaji Cam! Scan the code and get yours today. Happy Diwali!" in Riya Rao's voice, about $0.09?"* — its own audio tag, so v4.

**Turn 3** — *"go"*: 97 s, 5 calls, $0.52 ($0.37 voice, before the one-take fix). The Diwali line in v4, stability 0.5, over the end card, the picture as shot. Then *"Start a live Bhaji Cam session."* on line 2 came back **too long for the slot** — the tool said so — and Voltage shortened it to *"Start a Bhaji Cam session."* at speed 1.1 and voiced that, in Brian (the Customer's hand-picked voice), with the voice-match warning in its report (0.61 against the Customer). Its closing question, verbatim: *"You can hear both takes now. This turn has cost $0.37: the Diwali line came to $0.28 because it was regenerated twice, and line 2 came to $0.09. … Line 2 needed two compromises. I trimmed it to "Start a Bhaji Cam session." so it fits the slot, and it came out in a stand-in voice (Brian), not the Customer's own, which scores only 0.65 against him. Should I clone the Customer's voice from the clip and redo line 2 in it? That takes a voice slot, and the retake would be about $0.03–0.09."*

**Turn 4** — *"Yes: clone the Customer and redo line 2"*: 4 s, 1 call, $0.02. The clone gate, with the pick named.

**Turn 5** — *"go"*: 40 s, 4 calls, $0.11 ($0.02 voice). Steps: *Cloned Customer's voice from their own speech · Voiced "Start a Bhaji Cam session." with Customer's own voice — Casual, matter-of-fact, a touch brisk to fit the slot; "Bhaji Cam" as two clear words, BAH-jee cam. · Dropped i4*. Closing line, verbatim: *"Line 2 now says "Start a Bhaji Cam session." in the Customer's own voice. It passed the sound check and cost $0.02, and the picture runs slightly faster (1.12×) for that moment so the line fits. The Diwali offer in Riya Rao's voice is still on the end card at 40–48.5 s. The end card itself reads "Bhaaji Cam" with a double "a", which may be worth matching to how you spell the brand. I also cleared the failed take of line 2 from the plan. … Nothing is shipped yet: listen to both takes and tell me to ship when you're happy. The older delivery line planned for 38.3 s (i1) was never voiced, and I left it alone. It's also too long for its 1-second slot, so I'd drop it unless you want it shortened."*

Five turns, about $0.81 ($0.39 voice, $0.19 of it the pipeline's retries that are gone now). The "done when" of 20c holds: the Diwali goal ran end to end through the agent on a speech clip — read, looked, listened, chose, voiced, failed on length and fixed its own wording, asked about the clone, cloned, retook, dropped the dead item, reported text seen on screen without acting on it.

**Left for 20d:** the plan card's Run/Answer go through turns and the runner (`_run_plan`, `/run`, `/answer`, `/redo`, `/stop`, the item PUT) retires; the settings sheet; context editing and compaction over long threads; the eval; the pitch check for a voice-over in a chosen different voice; the previews card's position.

## As built · 20d, nothing non-agentic (2026-10-17/18, on `main`)

The user's words, mid-build: *"Also remove or archive any old code, so if we are using any old code or the references the app fails → and we can fix it; I don't want any non agentic behavior to exist."* So 20d is wider than the plan's "settings, evals, cost": every path that voiced a line or changed the plan outside a turn is deleted, not kept behind a flag, so a leftover reference fails loudly.

### Deleted

- **The selection-preview path**: `POST /edits/preview`, the intent interpreter (`orchestrator/intent.py`: `RuleInterpreter`, `Interpreter`, `EditContext`, `Turn`; `adapters/claude_intent.py`: `ClaudeInterpreter`), the placement questions (`orchestrator/questions.py`), the `Intent` model, and `/health`'s "intent" label. Typed words with a selection now go to Voltage as a turn (*"At 0:04: …"*).
- **The long-line policy**: `_long_line_fit`, `_shorter_line`, `BORROW_BEFORE`, `on_long`, the `long_lines` setting and its UI. `_generate` raises `SpanMismatch` to its caller; Voltage hears "too long for the slot" and decides (it shortened its own line on Bhaji Cam).
- **Wording suggestions**: `POST /lines/reword` and the editor's offers. Ask Voltage in words.
- **The plan runner**: `_run_plan`, `_agent_fix`, `_placement_note`, `_stops`, `PUT /plans/{id}/items/{item_id}`, `/run`, `/answer`, `/redo`, `/stop`, their request models, `_status_after_edit`. The plan card keeps the record (items, states, takes, Hear it, Another take → a turn, the Voice row → a turn) and loses its form (ticks, inline rewording, suggestions, Go ahead, Stop, delivery and mix pills, the estimate).
- **The offline stand-ins**: `OfflinePlanner`, `select_interpreter`; `select_planner` is Claude or `None`, and `/reading` and the first look answer 503 *"Voltage needs Claude for this"* without a key or under `AVE_DRY_RUN`. `Meter` lives in `orchestrator/meter.py`; `MODEL`, `PlannerError`, `PlannerConfigError` in `adapters/claude_planner.py`.
- **The line editor's own voicing**: `hearLine` → `/edits/preview` is gone; the editor (wording, delivery, mix, voice) composes one sentence and sends it as a turn: *Replace the line at 0:04 (“…”) with “…”, said warmer, in Riya's voice* / *Add “…” after the line at 0:04, over the picture* / *Add “…” at 0:00–0:07, over the picture*. Keep a take = ship that item (`/plans/{id}/approve` with the item); Another take = a turn.

### Kept (the user's own hands on the timeline, and shipping)

Keep, Undo, Remove a line, Shift a line, Move a take or a kept line, play; the review panel and the ship card; reading, consent, speakers, variants, export; the chat panel. The first look at a clip (`look`, `read`) stays a single Claude call outside the loop: it is Voltage speaking, not a second way of editing.

### Built (the plan's 20d)

- **"What Voltage may do"**: per-project `turn_usd` (clamped to a cent … the project's ceiling) and `effort` (medium / high / xhigh) in `PUT /settings`, read by every turn (`TurnBudget`, `output_config.effort`); `GET` carries the ceiling read-only. The front end's sheet is off the autonomy switch.
- **Consent at the yes**: under Check with me the paid gate's "go" is refused with 403 until consent is recorded, as Just do it was before the turn; the front end opens the consent sheet and retries the same turn.
- **Compaction**: the `compact-2026-01-12` beta with a `compact_20260112` edit past 100k input tokens, beside the frame-clearing edit; the loop already persists and replays each response's content whole, compaction block included.
- **The pitch register** is checked on a replacement against the same speaker's speech and no longer on an added line (over the picture or held), which is often another voice on purpose; the score comes back `None` there. (On Bhaji Cam this cost two retries.)
- **The previews card** is handed back by the tool as `ToolResult.card` and written by the loop after its step, so it reads: the step, the players, Voltage's sentence.

### The eval (`app/tools/agent_eval.py`, results in `backend/bench/agent-evals/`)

Ten goals across the three clips, each a fresh upload and one turn under Just do it with a $1.00 cap, graded by Opus 5.5 against the rubric from the record (it cannot hear the takes, and says so). Three runs the same evening, about $1.50 each:

1. **0 of 10.** Every note said the choices were right — voice, direction, placement, candour — and failed two points: the closing words quoted only the take's cost, never the turn's, and three turns shipped under Just do it, which the plan allows. Two real gaps and one wrong rubric. Fixed: Voltage's own thinking is now a step of its own in the thread after its words ("Thinking · $0.08"), so the step list's total is the turn's total and the model is told not to guess it; the prompt says a compromise (a stand-in voice when their own was asked for, a take that failed its check, words it had to cut) is shown, not shipped, until the user says; the rubric allows shipping finished work under Just do it and gets the consent and autonomy facts.
2. **7 of 10,** median 32 s and $0.18 a turn. The three misses: two closing lines that did not quote the paid steps' cost (which the thread shows beside each step), and a turn that voiced a line twice as two items and described the second. Fixed: the rubric counts a wrong number, not silence; the prompt says one line, one item — voice again on the same item, drop what is not kept.
3. **3 of 10.** The grader turned the money point into a rounding contest ("$0.17 rather than $0.1764", "include your thinking in the figure") against the rubric's own words — an LLM judge is noisy on a soft point. One real bug surfaced: a line voiced again on the same item kept its old direction in the plan (fixed: `reason` follows the re-voice). Fixed in the harness: the cap is checked from the ledger in code, and the grader judges the decisions and honesty only, with rounding to the cent and an unsaid cost explicitly fine.
4. **7 of 10,** median 38 s and $0.14 a turn, $1.40 in all. All ten turns chose a fitting voice, direction and placement and committed nothing they should not have; the three misses are precision in the closing words — a speed-up quoted when the take had none, "seven lines, not six", "nothing was paid for" about a removal in a turn that cost thinking.

**Where it stands.** The plan's bar was 9 of 10. Over four runs the decisions pass every time; what fails is the closing line's exactness about numbers it did not get from a tool. That is the next thing to build (20e): give the closing words their facts — a final `project_state` the loop appends before the model writes its last line, so the speed-up, the line count and the cost come from the record and not from memory — and name the source of a claim ("the catalogue describes her as…", "the frames show…"). Four runs cost about $6 in all; each run's JSON is in `backend/bench/agent-evals/`.

What the grader kept asking for across the runs, worth a 20e: Voltage sometimes says a voice is "confident" or a place is Goa as if it had heard or knew — the catalogue's description and the frames should be named as the source; the off-gender first take (Sarah for a male shopkeeper) when the speaker's own voice cannot be made; browsing voices before the first take rather than after.
