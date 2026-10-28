# COSTS: cost and pricing sheet for Voltage

Written 2026-10-23. Analysis only. No code, price or config was changed. Every price in `backend/app/billing/prices.py` is still a placeholder.

How to read this sheet:
- "Vendor cost" means what the usage ledger records in USD. One credit buys $1 of that.
- "Measured" means real spend from the four live agent-eval runs of 2026-10-17 or the live ledger copy. "Mock" means the rehearsal mock. "Assumption" means my estimate. Each number says which it is.
- All assumptions are collected in section 7.

## 1. Vendor prices as the code has them

| Vendor and step | Price in code | Where |
|---|---|---|
| Transcription (Whisper) | $0.006 a minute of audio | `backend/app/usage.py:26` |
| Claude, `claude-opus-5` | $5 input, $25 output per million tokens | `backend/app/usage.py:27` |
| Claude, `claude-haiku-4-5` (no longer a default; kept for `AVE_CHECK_MODEL`) | $1 input, $5 output per million tokens | `backend/app/usage.py:29` |
| Claude, `claude-haiku-5-5` (2026-10-24: project check, learned style, question turns) | $0.10 input, $0.50 output per million tokens (list price, prompts up to 100k tokens) | `backend/app/usage.py:31` |
| Claude cache read / cache write | 0.10x / 1.25x the input rate | `backend/app/usage.py:34` |
| Claude fallback for any model not in the table | $5 / $25 per million tokens | `backend/app/usage.py:38` |
| ElevenLabs speech | $0.30 per 1,000 characters | `backend/app/config.py:53` (env `AVE_ELEVENLABS_USD_PER_1K`) |
| Takes per voiced line | 3, each billed | `backend/app/config.py:46` (env `AVE_TAKES_PER_LINE`) |
| Voice design from words | about 350 characters per design (three previews) | `backend/app/adapters/elevenlabs.py:72`, method at about line 619 |
| Saving a designed voice / an instant clone | a voice slot, no characters | `backend/app/adapters/elevenlabs.py:20-21, 67` |
| Voice Changer (clone re-voices a take) | about 1,000 characters a minute of audio (17 a second) | `backend/app/adapters/elevenlabs.py:49-55` |
| Renders and transcodes | no vendor cost, server compute only | ffmpeg on our own server |
| Lip-sync (Phase 17) | not live in the public profile; optional | the plan file `docs/superpowers/plans/2026-10-14-phase-17-the-mouth.md` is not in this worktree, so no price is given here |

Note on the agent model. The agent runs on `claude-opus-5-5`. That id is not a key in `CLAUDE_USD_PER_MTOK`, so `claude_usd` charges it at the fallback ($5, $25). If Opus 5.5 list prices differ from that, every "agent" number below moves with them.

What each step uses:
- Upload: transcription per minute of audio (plus diarization, also per minute; the eval shows the same $0.0049 for a 49 s clip).
- Each chat turn: several Claude calls (the eval shows 2 to 13 per turn). Image looks ("looking") are Claude calls too.
- Each voiced line: characters x 3 takes x $0.30 per 1k. A 23 character line costs 23 x 3 x 0.0003 = $0.0207. This matches the eval's "Make it 30% off" speech spend exactly.
- Design: about 350 characters, so about $0.105.
- Clone: a slot, no characters. Using it through the Voice Changer bills audio seconds.
- Render or export: compute only.

## 2. Cost per scenario and per finished minute

Sources: the eval runs at `AgenticVideoEditor/backend/bench/agent-evals/20261017T152405Z.json`, `...153620Z.json`, `...154945Z.json`, `...160047Z.json` (10 goals each, one turn per goal). Goals are defined in `backend/app/tools/agent_eval.py`. Clips: a 48.9 s shop dialogue with 19 lines, a 7.46 s silent beach clip, and a 2.3 s one-line offer clip.

"Per finished minute" assumes a 60 s finished video with one such edit, unless the row says it scales with length. Low / typical / high are the min / median / max of the four runs where measured.

| Scenario | Steps | Vendor cost per edit, low / typical / high | Per finished minute (60 s clip) | Source |
|---|---|---|---|---|
| Cut one line (no voice) | 1 turn, 2 Claude calls, 0 characters | $0.023 / $0.024 / $0.024 | $0.036 (adds $0.012 upload on 60 s) | Measured: "Remove the line where the customer asks about tomatoes", 4 runs |
| One-line fix (new words, re-voiced) | 1 turn, 6 to 9 calls, 32 chars x 3 takes (one run voiced twice: 208 chars) | $0.125 / $0.134 / $0.192 | $0.146 | Measured: "Replace 'Feed is live' with 'We're live, sir'", 4 runs |
| One-line fix, short clip | 1 turn, 2 to 5 calls, 23 chars x 3 | $0.048 / $0.060 / $0.072 | $0.07 | Measured: "Make it 30% off" on the 2.3 s clip |
| Re-voice one line (warmer) | 1 turn, 11 to 12 calls, 60 to 163 chars billed | $0.179 / $0.217 / $0.225 | $0.23 | Measured: "The shopkeeper should sound warmer in his first line" |
| 5-line rewrite | 1 turn, 11 to 13 calls, 253 to 584 chars billed (84 to 195 per take) | $0.222 / $0.328 / $0.338 | $0.34 | Measured proxy: "Turn this into our Diwali ad" (number of changed lines not recorded; treated as about 5) |
| New voice-over, one line on a silent 7.5 s clip | 1 turn, 4 to 9 calls, 28 to 588 chars billed | $0.077 / $0.142 / $0.310 (16 samples, 4 goals) | n/a | Measured: the four voice-over goals |
| New voice-over, a full 60 s script | about 900 chars x 3 takes, agent 1 to 2 turns | $0.45 / $0.75 / $1.40 | $0.75 (scales with length) | Assumption: speech 15 chars a second, scaled from the measured 7.5 s clip |
| Clone voice-over, 60 s | clone (slot, $0), TTS takes as above, Voice Changer 1 to 3 passes | $1.15 / $1.40 / $2.00 | $1.40 (scales with length) | Assumption from code rates: TTS $0.81 + Voice Changer $0.31 a pass + agent $0.10 to $0.30 |
| Language version, 60 s | translate in 1 to 2 turns, re-voice all lines, 900 chars x 3 | $0.90 / $1.10 / $1.50 | $1.10 (scales with length) | Assumption: no eval goal covers it |
| Voice design (optional) | about 350 chars | $0.105 | n/a | Code: `DESIGN_CHARS` |
| Export | render only | $0.00 vendor | $0.00 vendor | Code: no vendor call |

Cross-checks:
- Live ledger (measured, 7 real turns, 2026-10-19 to 20): average $0.47 a turn, low $0.09, high $2.20. Agent calls average $0.046 each (90 calls, 2.4M tokens). Speech rows average 45 characters at $0.0134. Real use runs longer than the eval goals, so plan for about $0.50 a turn in practice.
- Mock (rehearsal): two calls a turn (9,200 in + 420 out, then 600 in + 9,400 cache read + 90 out) give $0.0565 + $0.0100 = $0.066 Claude. "Fresh every morning." (20 characters) x 3 takes gives $0.018 voice. That sits inside the measured one-line fix range, near the low end.
- Agent spend is half to two thirds of every voiced scenario. Speech is most of the rest. Transcription is under 1%.

Server compute, shown apart (assumption):
- VM: 4 vCPU / 8 GB at $48 a month (a typical cloud price; Hetzner-class hosts are near $15). That is $0.067 an hour.
- Renders are seconds for short clips. Assume 15 s of full VM time to render a 60 s 1080p export, and 3 renders per finished video.
- Compute per finished minute: about 45 s of VM, so about $0.001. It is negligible next to vendor cost. The real cost is the fixed $48 a month, which needs about 30 credits a month of paid use at 2.5x to cover (assumption: margin covers it).

## 3. Payment fees and FX (assumptions to confirm)

| Gateway | Assumed fee | Notes |
|---|---|---|
| Stripe, international cards in USD | 2.9% + $0.30, plus 1.5% international card, so 4.4% + $0.30 | Confirm against the account country of the selling entity. Currency conversion may add 1% to 2% more. |
| Razorpay, India, INR | 2% of the amount charged (GST included), plus 18% GST on the fee, so 2.36% | UPI and RuPay debit may be lower. International cards through Razorpay are about 3% + GST. |

- GST on our invoices (code, `backend/app/billing/gst.py:18, 59-66`): 18% is added on top of the price. Same state: CGST 9% + SGST 9%. Other state: IGST 18%. Outside India: export, 0%, under an LUT the seller must file.
- GST collected is passed to the government. It is not revenue. The gateway fee is charged on the GST-inclusive total.
- FX: `INR_PER_USD = 84.0` (`backend/app/billing/prices.py:24`). INR top-up prices are the USD price x 84, rounded (`backend/app/billing/__init__.py:235-245`). Plans carry their own INR price.
- Assumption: the GST on Razorpay's fee is treated as a cost (no input tax credit claimed). If the business claims it, India net goes up by about 0.4%.

## 4. Pricing table at 2.5x vendor cost

Target: net revenue per credit, after GST and gateway fees = 2.5 x $1 = $2.50 (Rs 210 at 84).

Formulas (P = price before GST, C = credits):
- USD (Stripe, no GST on export): P x (1 - 0.044) - 0.30 = 2.5 x C, so **P = (2.5 C + 0.30) / 0.956**.
- INR (Razorpay, GST on top): the buyer pays 1.18 P; the fee is 0.0236 x 1.18 P; net = 0.97215 P. So **P = 2.5 x C x 84 / 0.97215 = Rs 216.02 x C**. Invoice total = 1.18 P.

Proposed prices vs today's placeholders:

| Item | Credits | Proposed USD | Proposed INR (before GST) | INR invoice with 18% GST | Today USD | Today INR | Margin today, USD | Margin today, INR |
|---|---|---|---|---|---|---|---|---|
| One credit (bulk rate) | 1 | $2.62 (single purchase $2.93, the $0.30 fixed fee) | Rs 216 | Rs 255 | $1.20 | Rs 101 | 1.1x | 1.17x |
| Top-up 10 | 10 | $26.46 | Rs 2,160 | Rs 2,549 | $12 | Rs 1,008 | 1.12x | 1.17x |
| Top-up 25 | 25 | $65.69 | Rs 5,401 | Rs 6,373 | $30 | Rs 2,520 | 1.14x | 1.17x |
| Top-up 50 | 50 | $131.07 | Rs 10,801 | Rs 12,745 | $60 | Rs 5,040 | 1.14x | 1.17x |
| Starter, a month | 15 | $39.54 | Rs 3,240 | Rs 3,824 | $19 | Rs 1,599 | 1.19x | 1.23x |
| Studio, a month | 50 | $131.07 | Rs 10,801 | Rs 12,745 | $59 | Rs 4,999 | 1.12x | 1.16x |
| Agency, a month | 160 | $418.72 | Rs 34,563 | Rs 40,784 | $179 | Rs 14,999 | 1.07x | 1.09x |

Margin today = net after fees and GST / vendor cost of the credits. **Every placeholder falls short of 2.5x.** They give 1.07x to 1.23x. Agency is the thinnest. `TOPUP_MARKUP = 1.2` (`prices.py:25`) alone cannot reach 2.5x; it would need to be about 2.62 for USD, and INR would follow at x 84 (Rs 220, a little above the Rs 216 target).

Plans at exactly 2.5x carry no discount over top-ups. If plans should be cheaper per credit than top-ups, the top-ups must sit above 2.5x or the plans below it.

Breakage: unused plan credits lapse at month end, and top-ups lapse after 12 months (`prices.py:17, 27`). Lapsed credits are pure margin, but none is counted above. Trial credits (5 free, `prices.py:23`) are a cost of $5 vendor spend per new account at most, also not counted.

What each scenario costs a user at the proposed prices (typical vendor cost = credits used; USD at $2.62 a credit, INR at Rs 216 before GST):

| Scenario | Credits | USD | INR before GST | INR with GST |
|---|---|---|---|---|
| Cut one line | 0.02 | $0.06 | Rs 5 | Rs 6 |
| One-line fix | 0.13 | $0.35 | Rs 29 | Rs 34 |
| Re-voice one line | 0.22 | $0.57 | Rs 47 | Rs 55 |
| 5-line rewrite | 0.33 | $0.86 | Rs 71 | Rs 84 |
| New voice-over, 60 s | 0.75 | $1.97 | Rs 162 | Rs 191 |
| Clone voice-over, 60 s | 1.40 | $3.67 | Rs 302 | Rs 357 |
| Language version, 60 s | 1.10 | $2.88 | Rs 238 | Rs 280 |
| Export | 0 | $0 | Rs 0 | Rs 0 |
| A real turn (ledger average) | 0.47 | $1.23 | Rs 102 | Rs 120 |

So Starter (15 credits) buys about 110 one-line fixes, about 20 one-minute voice-overs, or about 30 real turns.

## 5. Sensitivities

| Lever | Change | Effect |
|---|---|---|
| Model for the agent | Opus at $5/$25 to a Haiku-class model at $1/$5 | Agent spend falls about 80%. A one-line fix goes from $0.13 to about $0.05. |
| Opus 5.5 real list price | If above the $5/$25 fallback | Agent spend rises in proportion, and the ledger under-reports until the key is added to `usage.py`. |
| Takes per line | 3 to 1 | Speech falls by two thirds. A 60 s voice-over falls from about $0.75 to about $0.35. 3 to 2 saves a third. |
| Turns per fix | Eval is 1 turn; ledger average shows longer real turns | Each extra turn adds about $0.05 to $0.50. This is the widest spread in the data (ledger high $2.20). |
| Cache hit rate | Cached input costs 0.1x | The mock's second call is 94% cache. Losing the cache on such a call raises it from $0.010 to $0.052. Across a long turn, a cold cache can double agent spend. |
| ElevenLabs tier price per 1k characters | $0.30 in code; higher self-serve tiers are about $0.17 to $0.24, lower ones about $0.30 or more (assumption, check the plan bought) | Speech scales linearly. At $0.18 a 60 s voice-over saves about $0.32. Note the ElevenLabs bill is a monthly plan, so unused plan characters are a fixed cost. |
| Gateway fees | Stripe fixed $0.30 | Small packs lose most: a single $3 credit loses 10% to the fixed fee. Keep a minimum pack of 10. |
| FX | 84 Rs per USD | A 5% rupee drop cuts INR margin from 2.5x to about 2.38x. |

## 6. Decisions for you

Nothing in code was changed. You set the prices.

1. Accept 2.5x as the target, and pick the credit price: $2.62 / Rs 216 before GST (Rs 255 with GST), or a round number such as $2.75 / Rs 229.
2. Set `TOPUP_MARKUP` to match (about 2.62 to 2.75). Decide whether INR keeps the x 84 rule or gets its own round prices.
3. Set plan prices: at 2.5x with no discount ($39.54 / $131 / $419), or give plans a per-credit discount paid for by expected breakage.
4. Add `claude-opus-5-5` to `CLAUDE_USD_PER_MTOK` with its real list price, so the ledger and credits match the invoice.
5. Decide takes per line (3 today). It is the biggest single lever on voice cost.
6. Confirm Stripe and Razorpay rates for the selling entity, and whether GST on gateway fees is claimed as input credit.
7. Decide whether the fixed server cost ($48 a month assumed) is covered by margin or priced in.
8. Lip-sync: price it only if it goes live in the public profile.

## 7. Assumptions

1. Opus 5.5 is billed as the ledger records it: the $5/$25 fallback.
2. ElevenLabs is $0.30 per 1k characters as in config, and every take is billed.
3. The Diwali rewrite stands in for a 5-line rewrite; changed line count is not recorded.
4. Per finished minute assumes a 60 s clip with one edit; voice-over, clone and language version scale with length.
5. Speech runs at about 15 characters a second.
6. Clone voice-over: the Voice Changer runs 1 to 3 passes at about 1,000 characters a minute.
7. Language version: no eval data; it is a full re-voice plus 1 to 2 translation turns.
8. VM: 4 vCPU / 8 GB at $48 a month; a 60 s export renders in about 15 s; 3 renders per video.
9. Stripe 4.4% + $0.30; Razorpay 2% + 18% GST on the fee; both to be confirmed.
10. INR prices are before GST, with 18% added on the invoice, as the code does.
11. 1 USD = 84 INR, from `prices.py`.
12. Breakage and trial credits are not counted in the margin.

## 8. Cost evals and the cost of a turn (2026-10-24)

Measured with real vendors on a database copy, through the app's own ledger, by the cost evals in `backend/evals/` (`python -m evals run`, `python -m evals compare`; raw JSON in `backend/evals/results/`). Six scenarios, one fresh upload and one turn each, under Just do it. The clips are short: the 2.3 s sample ad, a 13 s two-speaker chai stall clip made from it with the system voices, and a 6 s silent clip. Turn cost is the agent plus speech for the turn only; the upload's transcription and first look are setup and shown apart. Costs are "warm": a run's first request that found the shared prefix (tools and system prompt, about 10,300 tokens, the same for every user) cold is counted as having read it, because that depends only on what ran in the five minutes before. The raw ledger figure is in the JSON.

Real spend for the whole night: $3.557 on the copy's ledger (Claude $2.714, ElevenLabs $0.843, under the $3.80 daily cap set on that copy), plus about $0.005 of speech to text (ElevenLabs Scribe: the OpenAI key had expired, so Whisper could not be used) for scoring the takes and about $0.003 of Haiku test calls. Total about $3.57, inside the $4 budget.

### What was changed

| Lever | What it does | What it saved, measured |
|---|---|---|
| a. Caching | The agent loop already cached the tools, the system prompt and the thread: 93% of its input tokens were cache reads in the baseline. The planner's own calls (the first look at a clip) now cache their instructions too (about 1,060 tokens). | Under a cent per upload. |
| b. Small model | A turn that only asks how the app works runs on `claude-haiku-5-5` with the read-only tools, sorted first by the same model (a request put as a question stays with the planner). The project check and learned style moved to `claude-haiku-5-5` too. | Question turn $0.034 to $0.001 (-97%, twice). Project check about 10x cheaper, same output on a live test. |
| c. Takes | Takes are voiced one at a time, stopping at the first within the fit tolerance. A wider band (`AVE_TAKE_ACCEPT=0.10`) is off: it saved takes but measured worse duration error. | Only when a second take fits; in these runs most lines needed all three. |
| d. Kept reads | A clip's transcript, first look, understanding and reading are kept by the file's hash (migration 0038). | Re-uploading a clip: setup $0.034 to $0.056 down to $0.00. |
| e. Opening view | Motion peaks on a named beat are dropped; a later turn whose brief, rules and understanding did not change points back to them. | First turn 0 to 14% fewer opening tokens; later turns 65 to 74% fewer (about 350 tokens a request). |

Not kept: a prompt line asking the agent to voice independent lines in one reply. In its one run the 5-line rewrite cost more ($0.77 against $0.48) and re-voiced lines; it was taken out.

### Cost per turn, per scenario

| Scenario | Baseline | Runs after (same request) | Typical now | Scores, baseline to after |
|---|---|---|---|---|
| One-line fix ("Make it 30% off", 2.3 s) | $0.058 | $0.059, $0.119 | $0.059 | WER 0 to 0 · SIM-o 0.63 to 0.52 / 0.62 · UTMOS 4.34 to 4.39 / 4.33 · duration error 0.11 to 0.18 / 0.45 s · plan 1 to 1 |
| 5-line rewrite (13 s, two speakers) | $0.485 | $0.772 (with the line taken out) | $0.485 | WER 0.03 to 0.24 · SIM-o 0.71 to 0.73 · UTMOS 4.14 to 3.75 · duration error 0.36 to 0.33 s · plan 1 to 1 |
| New voice-over, one line (6 s, silent) | $0.117 | $0.169, $0.159 (from the ledger: that re-check turn outran the runner's 15 minute wait) | $0.159 | WER 0 to 0 · UTMOS 4.46 to 4.46 · duration error 0 to 0 · plan 1 to 1 |
| Hinglish line (2.3 s) | $0.140 | $0.116, $0.185 | $0.140 | WER 0.63 to 0.63 · SIM-o 0.82 to 0.79 · UTMOS 3.95 to 3.97 / 2.95 · duration error 0.20 to 0.35 / 0 s · plan 1 to 1 / 0 (laid over instead of replacing, once) |
| Hindi version, 5 lines (13 s) | $0.453 | not run again (budget) | $0.453 | WER 0.33 · SIM-o 0.84 · UTMOS 3.48 · duration error 0.40 s · plan 1 |
| Question turn ("How do I make a vertical version?") | $0.034 | $0.001, $0.001 | $0.001 | plan 1 to 1 · help article used and named, both times |
| Average of the six | $0.215 | | $0.216 | |

The target (40% lower with no score more than 5% worse) was not reached. What the numbers say:
- Only the question turn moved for certain. The other levers either do not touch a single-turn edit (d and e help re-uploads and later turns) or saved nothing on these lines (c).
- One turn is not a measurement. The same one-line fix, same words, same voice, same single take, cost $0.051 to $0.151 in agent spend over three runs, and its SIM-o moved 0.63 to 0.52 on a take made the same way. Agent spend is mostly output (thinking), and how long Voltage thinks and how often it re-voices varies run to run. Every flag a 5% threshold raised in these runs is inside that spread, and none comes from a changed lever: the re-check ran the baseline's system prompt and tools, and no kept lever acts on a fresh single-line edit (c only when a second take fits, which it did not). The evals need three or more runs per scenario before a 5% bar means anything; that is about $4.50 a full pass at today's prices ($1.50 a pass with setup).

### Run 5 re-check of the scores (2026-10-28)

Three runs each, mean (lowest to highest). The 5-line rewrite's WER 0.24 above was two scoring artifacts (a line scored against a try that did not fit, and a "[excited]" tag counted as a word); rescored it is 0. One-line fix, all run-4 levers on vs off: WER 0 / 0, SIM-o 0.560 (0.550 to 0.570) vs 0.544 (0.537 to 0.556), UTMOS 4.35 vs 4.35, turn $0.115 vs $0.080 raw. 5-line rewrite, all on: WER 0.17 (0 to 0.25), SIM-o 0.72 (0.68 to 0.80), UTMOS 3.83 (3.46 to 4.17), turn $0.64 ($0.57 to $0.71). No lever is shown to hurt a score; 1c (takes) and 1e (opening view) are off by default anyway, as the owner keeps only 1b and 1d (DECISIONS.md, run 5 addendum 0a).

### What would move the cost (for you to decide, not changed)

| Lever | Effect, from these runs |
|---|---|
| The ledger's price for `claude-opus-5-5` | The ledger charges the fallback $5 / $25 and cache reads at 0.1x. The list price is $4 / $20 with reads at 0.05x. At list price the baseline's agent spend is 30% lower, about 20% of every turn (decision 4 in section 6). |
| Takes per line | Speech is 35% to 40% of a voiced turn here, and most lines took all three takes. Two takes saves about a third of that. |
| Effort | Agent output (thinking) is about half of agent spend. A lower default effort (`AVE_AGENT_EFFORT`, high today) would cut it; it needs the evals at three runs a scenario first. |
| Tool definitions | 6,600 of the 10,300 shared tokens are tool descriptions, read on every request (about 9 requests on a 5-line turn). |

### What each scenario costs a user now (at 2.5x)

Typical vendor cost from the table above; USD at $2.62 a credit, INR at Rs 216 a credit before GST (section 4, unchanged: the credit price follows from the margin, not from turn costs).

| Scenario | Credits | USD | INR before GST | INR with GST |
|---|---|---|---|---|
| One-line fix (2.3 s) | 0.059 | $0.15 | Rs 13 | Rs 15 |
| 5-line rewrite (13 s) | 0.485 | $1.27 | Rs 105 | Rs 124 |
| New voice-over, one line (6 s) | 0.159 | $0.42 | Rs 34 | Rs 41 |
| Hinglish line (2.3 s) | 0.140 | $0.37 | Rs 30 | Rs 36 |
| Hindi version, 5 lines (13 s) | 0.453 | $1.19 | Rs 98 | Rs 116 |
| Question turn | 0.001 | under $0.01 | under Rs 1 | under Rs 1 |
| Average of the six | 0.216 | $0.57 | Rs 47 | Rs 55 |

These are short clips, and the eval turns are single, fresh turns; the section 2 and 4 figures for 60 s scenarios and the live ledger's $0.47 a real turn still stand. The question turn is the one real change: a how-do-I question no longer costs a planner turn.
