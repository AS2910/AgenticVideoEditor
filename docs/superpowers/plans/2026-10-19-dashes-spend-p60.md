# Em dashes, spend scopes, and the p60 mismatch (2026-10-19)

Evidence first, as asked; nothing below the "As built" heading existed when this was written.

## A. p60: Voltage and the editor disagree (investigation)

Video `p60` (8.0 s, project f1), plan `plan1`, two spoken lines; the goal "swap the voice for the deewar voice".

**Items (as stored):**

| Item | Line | Status | Take | Error shown |
|---|---|---|---|---|
| i1 | 1 (0.00–5.64) | approved (e1) | c1 (also c4 tried) | none |
| i2 | 2 (5.64–7.98) | dismissed | none | "The new line is too long for the selection — widen the selection or shorten the line. (needs 3.84s, selection is 2.34s)" |
| i3 | 2 (5.64–7.98) | **failed** | **c3 (a good take)** | "… (needs 3.76s, selection is 2.34s)" |

**Every attempt on line 2, from Voltage's own tool calls (`turns` table):**

| Time (UTC) | Call | Item it landed on | Result |
|---|---|---|---|
| 17:17:13 | synthesize_take `line: 2`, v4, speed 1.1 (no item_id) | new item **i2** | failed: span too long (3.84 s in 2.34 s) |
| 17:17:37 | synthesize_take `line: 2`, v2, speed 1.2 (no item_id) | new item **i3** | **c3 made, i3 ready** (picture 0.89×, speech 0.91×) |
| 17:18:15 | synthesize_take `line: 2`, v4, speed 1.2 (no item_id) | **i3** (latest item on the line) | failed: span too long (3.76 s) → **i3 set to failed, c3 left on it** |
| 17:18:24 | drop_item i2 | i2 | dismissed |
| 17:18:29 | reply | | "Line 2 only fit its short gap with the steadier model at a faster pace, and the picture slows a little" |

**Which suspects hold:**
- **(b) yes.** A retry that names the line but not the item creates a second item for the same line (i2, then i3). The 20d rule "one line, one item" is not enforced in code.
- **(a) yes, in a variant.** Not an out-of-order job, but the same effect: a later attempt that failed overwrote a ready item that had a good take, so the item's state became "failed" while its take was fine. Writes have no attempt order and a failure does not consider the take already there.
- **(c) partly.** The panel takes the plan from the turn's result (so items were current), but nothing re-reads items after the actions that change them outside a turn; edits are synced, items are not.
- **(d) yes.** The Phase 4a `SpanMismatch` wording ("widen the selection or shorten the line") is still raised by `media/ffmpeg.py` and shown as the row's error.
- **The reply was not checked** against the record: Voltage described c3 as waiting while the record said i3 failed.

## B. Em dashes (audit, step 1)

97 em dashes (U+2014, `&mdash;`, ` -- ` as a dash) in 80 lines across 30 files; code comments, docstrings and SQL comments excluded. User-facing: the agent's system prompt (10), the reading and look prompts (6), tool results, step lines and gate questions in `agent/tools.py` (30), the span-mismatch errors (2), "Stock voice — …" (1), the level-check note (1), the consent sheet's button, the timeline's empty state, and a lone "—" as the empty value on Billing, Export, Settings, Usage and the depth view. Not shown to users: the bench report, the chaos log line, the eval grader prompt, the ElevenLabs check tool. The help articles have none. Tests and the tutorial fixture assert on the step-line wording.

<details><summary>The full list (file: line: string)</summary>

```
97 dashes in 80 lines across 30 files

## backend/app/adapters/claude_planner.py (6)
  34: """\
You look at a few frames of a short video that has no speech, and describe \
what the picture shows for a person about to write a voice-over for 
  59: """\
You read the transcript of a short video and introduce it to the person about \
to edit its dialogue. Return `opening`: one plain sentence, under

## backend/app/agent/context.py (10)
  9: """\
You are Voltage, the editor inside a video dialogue editor. The user has a \
finished video and tells you, in their own words, what it should say

## backend/app/agent/tools.py (30)
  178: "Listened — no one speaks"
  187: " — own voice made"
  234: "Looked for voices — none"
  270: "Searched the voice library — unavailable"
  277: "Searched the voice library — nothing"
  283: f"Searched the voice library — {len(hits)} found"
  302: f"- {i.item_id} at {i.selection.start:.1f}–{i.selection.end:.1f} s: “{i.new_text}” — {i.status}"
  337: f"- {e.edit_id} at {sel.start:.1f}–{sel.end:.1f} s: {words} — {_MIX_WORDS.get(e.plan.mix, e.plan.mix)}"
  346: "Looked for sister videos — none"
  349: "Looked for sister videos — none"
  350: f"The other videos in {project.get('name')} (read only — this turn changes only its own video):"
  393: "Looked for reference files — none"
  396: "Looked for reference files — none"
  406: f"Searched the reference files for “{query[:40]}” — nothing"
  409: f"Searched the reference files for “{query[:40]}” — {len(found)} found"
  436: "Looked in Help — unavailable"
  439: f"Looked in Help for “{query[:40]}” — nothing"
  516: " — nearly full; delete a voice before making more."
  631: f"Could not voice “{text[:40]}” — {reason[:80]}"
  655: f" — {direction}"
  705: f"Design a voice from “{description}” — three previews to hear, about ${usd:.2f}?"
  713: f"Could not design a voice — {reason[:80]}"
  716: "Designed a voice — nothing came back"
  735: f"Designed a voice from “{description[:56]}{'…' if len(description) > 56 else ''}” — {len(rows)} previews to hear"
  753: f"Could not keep the voice — {reason[:80]}"
  771: f"Could not add {name} — {reason[:80]}"
  903: f"{item_id} is in the video; name its edit (edit_id) instead — project_state lists them."
  934: f" — {'; '.join(scores)}"
  1034: "`settings` as the vendor's dials, and for v3/v4 audio tags inside `text` — [sighs], [laughs], [whispers], [exhales], "
  1062: "Who is speaking: age, gender, accent, texture, manner — e.g. an Indian woman near fifty, unhurried, a smile in the voice, slight rasp."

## backend/app/bench/runner.py (2)
  144: "—"
  146: f"| {r.name} | {r.label} | {r.ratio:.2f} | {r.rung} | {'—' if r.passed is None else ('yes' if r.passed else 'no')} "

## backend/app/chaos.py (1)
  199: "CHAOS ON: %s — nothing is charged for an injected fault; unset AVE_CHAOS to stop"

## backend/app/continuity/measured.py (1)
  218: f"Level is {gain:+.1f} dB off the surrounding speech — too far to correct."

## backend/app/media/ffmpeg.py (2)
  54: "The new line is too long for the selection — widen the selection or shorten the line."
  56: "The new line is too short for the selection — narrow the selection or lengthen the line."

## backend/app/orchestrator/pipeline.py (1)
  21: "Stock voice — this is not the speaker's voice yet."

## backend/app/tools/agent_eval.py (1)
  42: """You grade one turn of Voltage, an agent that edits a video's dialogue through tools.
You see the brief, the clip's facts, every step the agent took

## backend/app/tools/check_elevenlabs.py (3)
  83: f"  --   {what} ({permission}): not tested here — it spends credits or changes your account"
  103: "No ELEVENLABS_API_KEY in backend/.env — Voltage will use its offline mock voice."

## backend/tests/agent/test_context.py (1)
  15: "- e3 at 0.0–7.4 s: “Golden sands.” — layered over the picture and sound"

## backend/tests/agent/test_loop.py (3)
  27: "Listened — no one speaks"
  27: "Voiced “Welcome to Goa.” with Varsha — warm"
  171: "Designed a voice from “an older woman” — 3 previews to hear"

## backend/tests/agent/test_project_tools.py (2)
  47: "The other videos in Spring sale (read only — this turn changes only its own video):"
  58: "Searched the reference files for “price” — 1 found"

## backend/tests/agent/test_tools.py (5)
  29: "Listened — no one speaks"
  49: "Voiced “Welcome to Goa.” with Varsha — warm and unhurried, a half-smile"
  138: "- e1 at 0.4–7.3 s: “Where the sand runs wide.” — layered over the picture and sound"
  241: "Design a voice from “An Indian woman near fifty, unhurried, a smile in the voice” — three previews to hear, about $0.10?"
  245: "Designed a voice from “An Indian woman near fifty, unhurried, a smile in the vo…” — 3 previews to hear"

## backend/tests/api/test_endpoints.py (1)
  1716: "Voiced “Get 30% off today only.” with Test tone — brisk and confident"

## frontend/src/App.test.tsx (7)
  724: it('asks one thing, and the answer — a pick or "go" — is the next turn', async () => {
  971: { role: 'assistant', text: 'Listened — no one speaks', kind: 'step', seq: 2 },
  973: { role: 'assistant', text: 'Voiced “Welcome to Goa.” with Varsha — warm and unhurried', kind: 'step', cost: 0.03, seq: 4 },
  995: it('sends the composer to a turn, shows each step as it comes, then the take on its row — and no voice picker', async () => {
  1009: '├Listened — no one speaksfree', '├Looked through 25 voicesfree', '└Voiced “Welcome to Goa.” with Varsha — warm and unhurried$0.03',

## frontend/src/App.tsx (1)
  440: /** Add it (20e): the proposal under a line goes into the video — its plan

## frontend/src/components/ConsentSheet.tsx (1)
  40: <Button variant="outline" onClick={onCancel} disabled={busy}>Not yet — keep it as a draft</Button>

## frontend/src/components/LineDoc.test.tsx (1)
  195: it('shows what is happening to a line, and the state of one that needs you or failed — nothing to answer here', () => {

## frontend/src/components/LineDoc.tsx (2)
  599: const fact = (label: string) => facts.grid.find((f) => f.label === label)?.value ?? '—'
  1074: // Volt: the heading — how many lines, how many proposed, how many in the video.

## frontend/src/components/Timeline.tsx (1)
  141: <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-muted-foreground">No speech found in this video — there are 

## frontend/src/lib/dates.test.ts (1)
  5: it('shows Not recorded for null, undefined, booleans, zero, empty and garbage — never 1970', () => {

## frontend/src/pages/BillingPage.test.tsx (1)
  41: expect(screen.getAllByText('—').length).toBeGreaterThan(0)

## frontend/src/pages/BillingPage.tsx (4)
  45: <span className="disp text-[30px] font-bold">{report ? usd(report.spent_usd) : '—'} <span className="text-base text-muted-foreground">/ {report ? usd(
  50: <span className="disp text-[30px] font-bold">{report ? usd(report.project_cap_usd) : '—'}</span>
  55: <span className="disp text-[30px] font-bold">{settings ? usd(settings.turn_usd) : '—'}</span>

## frontend/src/pages/ExportPage.tsx (3)
  168: <Tile label="Turns" value={receipt ? receipt.turns : '—'} size="md" className="rise" />
  169: <Tile label="Takes" value={receipt ? receipt.takes : '—'} size="md" className="rise d1" />
  170: <Tile label="Spent" value={receipt ? usd(receipt.spent_usd) : '—'} size="md" tone="volt" className="rise d1" />

## frontend/src/pages/SettingsPage.tsx (1)
  156: <span key={cents} className="tnum inline-block min-w-16 animate-[pop_.3s_ease] text-center text-xl font-semibold" data-testid="turn-cap">{settings ? u

## frontend/src/pages/UsagePage.test.tsx (1)
  30: expect(screen.getByTestId('spent')).toHaveTextContent('—')

## frontend/src/pages/UsagePage.tsx (1)
  34: const dash = '—'

## frontend/src/styles/theme.test.ts (2)
  43: it('spells no colour in a component — every colour is a token', () => {
  52: it('uses no gradients, glows or blurs — the look is flat; offset shadows come only from the component classes', () => {

## backend/app/tutorial/fixture/script.json (1)
  56: "text": "Voiced “Get 30% off today only.” with Sarah — Match the original read: upbeat ad delivery, same pace and energy, weight on \"thirty percent\"

```
</details>
