# Phase 4a — Real Voice (stock voice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-23
**Status:** Done 2026-09-23 — see the roadmap for the exit evidence
**Roadmap:** Phase 4 of `2026-09-22-real-pipeline-roadmap.md`, split in two because the ElevenLabs account is on the **free tier**, which refuses voice cloning (`can_use_instant_voice_cloning: false`, checked against the live API 2026-09-23).

- **4a (this plan):** everything in Phase 4 except cloning — real ElevenLabs TTS in a *stock* voice, fitted to the selected span, conditioned on the surrounding words, behind a cost guardrail and a dry-run switch.
- **4b (later, after a plan upgrade):** instant voice clone from the reference audio this plan extracts. A new adapter method plus a `voice_id` swap; nothing in 4a is thrown away.

**Goal:** the edited span contains a real, audible voice saying the new words, at the right length, with every vendor call metered, capped, and switchable off.

**Exit criteria (4a):**
1. Preview on the sample ad with `change "20%" to "30%"` produces a WAV that is intelligible speech of the new words, within ±5% of the selected span's duration.
2. The candidate card plays that audio in the browser.
3. A project over its character budget is refused *before* a vendor call, with a clear message — and no job is created.
4. `AVE_DRY_RUN=1` runs the whole flow with zero ElevenLabs calls.
5. The suite never calls the vendor: it blanks `ELEVENLABS_API_KEY` and replays a recorded response.
6. The candidate is honestly labelled: a stock voice gets a continuity warning saying it is not the speaker, rather than the mock's untroubled 0.9 voice match.

**Explicitly not the 4a exit:** "genuinely the speaker's voice". That is 4b.

**Spend for the whole phase:** the live checks below use well under 1,000 of the free tier's 10,000 monthly characters.

---

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Model | `eleven_multilingual_v2` default; `ELEVENLABS_MODEL` override | Best prosody of the models that accept `previous_text`/`next_text` context. `eleven_flash_v2_5` is half the character cost and the fallback if quality is fine — Task 1 compares both on the sample line. `eleven_v3` is excluded pending Task 1 confirming whether it accepts the context fields. |
| Voice | `ELEVENLABS_VOICE_ID`, default a premade voice chosen in Task 1 | Stock voices are all the free tier allows. Auto-matching gender/accent to the speaker is not worth building when 4b replaces it. |
| Output format | Raw PCM (`pcm_24000` or best free-tier rate) wrapped to WAV locally | Lossless, and every downstream step (tempo fit, continuity, render) wants PCM. Free-tier availability confirmed in Task 1; `mp3_44100_128` decoded by ffmpeg is the fallback. |
| Fitting to the span | ffmpeg `atempo`, ratio bounded to **[0.8, 1.25]** | Beyond that speech sounds visibly sped or dragged. Outside the bound the job fails with a message the user can act on ("the new line is too long for the selection — widen it"), which is **not retried** — retrying cannot change it. |
| Budget unit | ElevenLabs characters × model cost multiplier, per project | It is what ElevenLabs actually bills. Default ceiling `AVE_VOICE_BUDGET_CHARS=2000` per project. |
| When the budget is charged | Before each vendor *attempt*, including retries | Retries are real spend; charging only on success would let a flaky vendor exceed the cap. |
| Retries | Only 429, 5xx and network errors are `VendorError` (retryable). 401/403/422/quota errors are a non-retryable `VoiceConfigError` | Retrying a bad key or an exhausted quota 3× is just a slower failure. |

---

## File structure

- Modify `backend/app/config.py` — `elevenlabs_api_key`, `elevenlabs_model`, `elevenlabs_voice_id`, `voice_budget_chars`, `dry_run`
- Create `backend/app/adapters/elevenlabs.py` — `ElevenLabsVoiceAdapter`, `to_request()`, error mapping
- Create `backend/app/budget.py` — `VoiceBudget` (thread-safe per-project ledger), `BudgetExceeded`
- Modify `backend/app/adapters/base.py` — `VoiceAdapter.identity` (`"mock" | "stock" | "clone"`); `NonRetryableError` base
- Modify `backend/app/media/ffmpeg.py` — `pcm_to_wav()`, `fit_duration()`, `extract_segment()`
- Modify `backend/app/orchestrator/pipeline.py` — stock-voice warning onto the report
- Modify `backend/app/jobs/runner.py` — surface a `NonRetryableError`'s own message instead of the generic one
- Create `backend/app/media/reference.py` — `extract_reference_audio()` (consumed by 4b)
- Modify `backend/app/api/main.py` — adapter selection, budget check at preview, `/health`
- Modify `backend/tests/conftest.py` — blank `ELEVENLABS_API_KEY`, force `AVE_DRY_RUN` off
- Create `backend/tests/fixtures/elevenlabs-tts.pcm` + `.json` — one recorded response and its request metadata
- Create tests: `tests/adapters/test_elevenlabs.py`, `tests/test_budget.py`, `tests/media/test_reference.py`; extend `test_ffmpeg.py`, `test_pipeline.py`, `test_runner.py`, `test_endpoints.py`, `test_config.py`
- Frontend: `CandidateCard.tsx` — `<audio>` player for the candidate's audio; warning line already renders

---

### Task 1: Spike — confirm the vendor facts this plan assumes *(live, ~200 characters)*

Not TDD; it produces facts and the test fixture.

- [x] One TTS call per candidate model (`eleven_multilingual_v2`, `eleven_flash_v2_5`) saying "30% off" with `previous_text="Get"` / `next_text="today only."`, requesting `pcm_24000`.
- [x] Record: HTTP status, whether the context fields are accepted, whether the PCM format is allowed on free tier, the `character-cost` / `x-character-count` response header if present, and whether context characters are billed (compare `/v1/user/subscription` `character_count` before and after).
- [x] Listen to both; pick the model and the default premade voice. Save the chosen response as `tests/fixtures/elevenlabs-tts.pcm` with a `.json` sidecar (model, voice, format, sample rate, text, status).
- [x] Write findings into this plan's *Spike results* section before Task 2 starts. Any assumption above that turns out false is corrected here first.

### Task 2: Config

- [x] **Test first** (`test_config.py`): key absent ⇒ `has_elevenlabs` false; model/voice defaults; `AVE_VOICE_BUDGET_CHARS` parses as int and rejects negatives; `AVE_DRY_RUN` accepts `1/true/yes`; real env beats `.env`.
- [x] Implement in `config.py`; `conftest.py` blanks `ELEVENLABS_API_KEY` and `AVE_DRY_RUN` before the app imports, exactly as it already does for OpenAI.

### Task 3: ffmpeg helpers

- [x] **Tests first** (`test_ffmpeg.py`), all on generated media, no vendor:
  - `pcm_to_wav(bytes, rate)` → probes as WAV, mono, correct rate, duration = len/2/rate.
  - `fit_duration(wav, target)` → output within ±2% of target for ratios 0.8 and 1.25.
  - `fit_duration` outside [0.8, 1.25] raises `SpanMismatch` carrying the natural and target durations.
  - `extract_segment(src, start, end)` → WAV of `end-start` seconds.
- [x] Implement. `atempo` accepts 0.5–2.0 in one filter, so the bounded range needs no chaining.

### Task 4: Budget ledger

- [x] **Tests first** (`test_budget.py`): `charge(project, n)` accumulates; a charge that would cross the ceiling raises `BudgetExceeded` and records nothing; `remaining()`; per-project isolation; 20 threads charging concurrently never overshoot.
- [x] Implement `VoiceBudget` with a lock. In-memory like everything else until Phase 9 — a restart resets it, noted in the README.

### Task 5: ElevenLabs adapter

- [x] **Tests first** (`test_elevenlabs.py`) with an injected `post`, as the Whisper adapter does:
  - `to_request(plan, transcript)` — `text` is `new_text`; `previous_text` / `next_text` are the transcript words before and after the selection (up to ~200 chars each, whole words); model, voice and output format from config.
  - Replaying the recorded fixture produces a stored `audio`/`wav` `MediaArtifact` whose duration matches the span within ±5%.
  - The budget is charged `len(text) × multiplier` *before* `post` is called; `BudgetExceeded` means `post` is never called.
  - 429 / 500 / timeout → `VendorError` (retryable). 401 / 403 / 422 / `quota_exceeded` → `VoiceConfigError` (non-retryable) with a user-fit message.
  - The API key never appears in an exception message or a log line.
- [x] Implement. `identity = "stock"`. The adapter needs the transcript for context, so `synthesize` gains a `transcript` argument across the protocol, the mock, and the pipeline — a small signature change, done in this task with its callers.

### Task 6: Non-retryable failures surface their own message

- [x] **Tests first** (`test_runner.py`): a `NonRetryableError` is attempted exactly once and the job's `error` is its message; `VendorError` behaviour is unchanged; `BudgetExceeded`, `SpanMismatch` and `VoiceConfigError` all subclass `NonRetryableError`.
- [x] Implement in `runner.py`.

### Task 7: Honest labelling in the pipeline

- [x] **Test first** (`test_pipeline.py`): with a voice adapter whose `identity == "stock"`, the report carries the warning *"Stock voice — this is not the speaker's voice yet."* and `voice_match` is not presented as a pass for identity. Mock identity leaves the report untouched, so existing tests stand.
- [x] Implement. `passed` is **not** flipped to false by this warning, or no stock-voice edit could ever be approved and 4a could not be exercised end-to-end.

### Task 8: Wiring, preflight budget check, health

- [x] **Tests first** (`test_endpoints.py`, with an injected fake voice adapter):
  - Over-budget preview → **402** with the remaining-budget message, and no job created (same shape as the consent 403).
  - Dry-run ⇒ mock voice even when a key is set; `/health` says `"voice": "dry-run"`.
  - Key set, not dry-run ⇒ `/health` says `"voice": "elevenlabs:<model>:stock"`.
- [x] Implement adapter selection in `main.py` alongside the transcriber's.

### Task 9: Reference audio extraction *(for 4b)*

- [x] **Tests first** (`test_reference.py`): given a transcript, extracts the speech spans *outside* the selection, concatenated, as a stored WAV artifact; returns `None` below a minimum length (ElevenLabs instant clone wants roughly a minute; the exact floor is pinned in 4b); never includes audio from inside the selection.
- [x] Implement. Not called by the API in 4a.

### Task 10: Frontend — hear the candidate

- [x] **Test first** (`CandidateCard.test.tsx`): renders an `<audio>` whose `src` is `/projects/{id}/artifacts/{audio.sha256}`; warnings render as today.
- [x] Implement. The README limitation "a candidate still has no playable preview" is half closed (audio yes, video still a flat colour until Phase 5).

### Task 11: Live verification + docs

- [x] Run both suites; record counts.
- [x] Live, against the real API, in a browser: upload sample → consent → `change "20%" to "30%"` → hear the candidate → approve → export. Probe the stored WAV: duration within ±5% of the span.
- [x] Live: set `AVE_VOICE_BUDGET_CHARS=5`, preview → 402, confirm via `/v1/user/subscription` that no characters were spent.
- [x] Live: `AVE_DRY_RUN=1` → full flow, zero characters spent.
- [x] Record characters consumed by the phase. Update the roadmap (Phase 4 split into 4a done / 4b pending upgrade), README current-state, limitations and test counts. Commit.

---

## Spike results

Run 2026-09-23 against the live API. Line: `"30% off"`, context `"Get"` / `"today only."`, voice **Sarah** (`EXAVITQu4vr4xnSDxMaL`, premade, female, American — closest to the macOS default voice the sample clip was made with).

| Model | Result | `character-cost` header | Output |
| --- | --- | --- | --- |
| `eleven_multilingual_v2` | 200 | **7** (= `len("30% off")`) | 0.789 s, −15.2 dB mean; Whisper heard `30% off.` |
| `eleven_flash_v2_5` | 200 | **4** (half rate) | 0.789 s, −12.0 dB mean; Whisper heard `30% off.` |
| `eleven_v3` | **400** `unsupported_model` | — | "Providing previous_text or next_text is not yet supported with the 'eleven_v3' model." |

- **`pcm_24000` is allowed on the free tier.** Raw little-endian s16 mono; the response is `audio/pcm`.
- **Context is not billed.** `character-cost` counts only `text`. So conditioning on neighbouring words is free, and the budget charges `len(new_text)` scaled by model.
- **Bill from the `character-cost` header**, not from `/v1/user/subscription`: the subscription counter had not moved 2 s after each call.
- **Intelligibility was checked by transcribing the outputs with Whisper**, not by ear. Both models are intelligible. Choosing between them on *quality* needs a human listen; default stays `eleven_multilingual_v2` (7 characters is negligible), `ELEVENLABS_MODEL=eleven_flash_v2_5` halves cost.
- **`eleven_v3` is excluded** — it cannot take the context fields at all.
- **Sample-ad fit:** "20% off" spans 0.40–1.30 s (0.9 s) in the sample; the generated 0.789 s needs a 0.88× fit, inside [0.8, 1.25].
- Fixture: the `eleven_multilingual_v2` response, `tests/fixtures/elevenlabs-tts.pcm` + `.json`.
- Spike spend: 11 characters.

## Risks

- **Stock voice inside a real speaker's line will sound obviously spliced.** Expected, and why Task 7 labels it. 4a proves the plumbing, not the illusion.
- **Short edits make tempo-fitting fragile.** A 0.5 s span with a 4-syllable replacement will fall outside [0.8, 1.25] and be refused. That is the correct outcome, but it will be hit on the sample ad; the message must tell the user to widen the selection.
- **ElevenLabs output length varies per call** for the same text, so the same prompt can land inside the bound once and outside it the next. Retrying would not be deterministic either, so it stays a clear failure, not a hidden retry.

## Deviations from the plan

- **Task 5:** `synthesize` takes `transcript` as an *optional* argument, so the mock and existing callers needed no churn. Voice adapters also gained `cost_of(plan)`, which the preview endpoint uses for the 402 check before creating a job.
- **Task 7:** the stock-voice label is a warning only; the mocked `voice_match` number is left as is. Replacing it with a fake low number would be just as made up — Phase 6 measures it for real.
- **Task 8:** dry-run covers transcription as well as voice. "Dry run" should mean nothing is billed, and Whisper is billed too. Adapter choice moved to `app/adapters/selection.py` so it is testable without re-importing the app.
- **Task 11:** the in-browser listen was not possible (Chrome extension not connected). Replaced by: the exact `<audio>` URL fetched through the Vite proxy as a range request (`206 audio/wav`), plus Whisper transcribing the generated WAV.
