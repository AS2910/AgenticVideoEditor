# Phase 11 — Multiple voices

**Date:** 2026-09-26 · **Roadmap:** Phase 11, proposed after Phase 10's live test.

## Why

On a two-speaker clip (customer + shopkeeper), continuity compared a new line with *everyone* speaking nearby, so its pitch reference was a blend: Sarah measured +5.2 semitones, Brian −4.8 — no single voice could pass. And a new line should be spoken in the voice of whoever says it.

## Spike (2026-09-26, the 49 s Bhaji Cam clip)

| | Result | Cost |
|---|---|---|
| OpenAI `gpt-4o-transcribe-diarize` (`diarized_json`) | 20 segments, speakers A/B, all correct; no word timings | ~$0.005 (1.7k tokens) |
| ElevenLabs Scribe v1 (`diarize=true`) | words + punctuation + speaker per word, all correct; spelt "Bhaji cam" right | draws on the free tier's 10k credits — the same pool the voice needs |

**Chosen: OpenAI diarization alongside Whisper.** It keeps Whisper's word timings (continuity is calibrated on them) and leaves the scarce ElevenLabs quota for speech. Scribe is the better single call if the ElevenLabs plan is upgraded — revisit then.

## Design

- **Speakers on the transcript.** Whisper's words and statements each get the speaker of the diarized segment they overlap most. `Word.speaker`, `Statement.speaker` (None when unknown). Diarization failing never fails an upload — the project just has no speakers.
- **Existing projects:** `POST /projects/{id}/speakers/detect` diarizes after the fact.
- **A voice per speaker.** `GET/PUT /projects/{id}/speakers` — each speaker's display name and voice. An edit over one speaker's words is spoken in that speaker's voice; over no speech (or mixed speakers), in the voice picked in the chat.
- **Continuity against the same speaker.** The prosody/level context is only the edited speaker's words. Unknown speakers → everyone, as before.
- **Spend:** diarization is recorded in the ledger (estimated per minute).
- **Front end:** speaker chips on transcript statements; a Speakers row to rename speakers and choose each one's voice; "Detect speakers" for older projects.

## Exit

Suites green; ruff, tsc, oxlint, build clean; docs current. Live on the Bhaji Cam clip: two speakers detected; the shopkeeper's line is measured against the shopkeeper only, and a voice chosen for him passes the pitch check where the blend could not.
