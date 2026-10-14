# Phase 15 — The speaker's own voice and room

**Written 2026-10-14.** Unblocks roadmap 4b (speaker's own voice) and 6b (voice identity measured). From `2026-10-03-natural-fit-roadmap.md`: *instant clone from the reference extraction; Voice Changer route from the original line; Demucs stems and remix; reverb and spectral matching; SIM-o and UTMOS measured.* **Exit:** SIM-o ≥ 0.75 against the speaker on every take; the stock-voice warning disappears; music beds unchanged bit-for-bit outside the edit.

Vendor: ElevenLabs **Creator** plan (instant voice cloning; the key must carry `voices_read`, `voices_write`, `models_read`, `user_read`, text-to-speech and speech-to-speech — see 15a's `check_elevenlabs`). Tests never call a vendor (cassette fakes); every real piece keeps a mock sibling; the heavy local models are **optional extras** (`pip install -e '.[room,measure]'`) and the app runs without them exactly as before.

## Sub-phases (each closed fully clean — pytest, ruff, lint, build, docs — before the next merges)

### 15a · The clone (`elevenlabs.py`, `store`, `api`)
- A speaker's clone is made **once per speaker**, lazily at their first synthesis, from *all* of that speaker's speech (`reference.extract_reference_audio(..., speaker=)`); the earlier "exclude the selection" rule cannot hold for a clone that outlives one edit. Needs ≥ `AVE_CLONE_MIN_SECONDS` (default 10 s) of that speaker's speech; less → the line is spoken in the stock voice and says why ("4.2 s of this speaker's voice, 10 s needed to clone it").
- `POST /v1/voices/add` (instant clone, multipart). The id is stored on the speaker (`clone_voice_id`, `clone_made_at`, the reference's sha), reused by every later edit, and **deleted with the project** (`DELETE /v1/voices/{id}`), which is how consent is withdrawn.
- Consent is checked server-side before the clone is made (already the rule for any synthesis).
- Voice precedence for a speaker's line: a voice the user picked on purpose > the clone > the requested voice. `identity` is `"clone"` for a clone-voiced take, `"stock"` otherwise, **per take**, so the stock-voice warning appears only on stock takes.
- The clone is metered (one call, no characters) and its slot count respected: a refusal ("voice limit reached") is a plain sentence, not a crash.
- `python -m app.tools.check_elevenlabs` prints which permissions the key has, the plan, the clone slots and characters left — never the key. `/health` reports `voice: …:clone` when cloning is live.

### 15b · The Voice Changer route (`elevenlabs.py`, `pipeline.py`, `config.py`)
- `POST /v1/speech-to-speech/{voice_id}`: a take is made in any voice and converted into the clone, keeping the take's own timing and delivery. Used when a clone-voiced TTS take scores **SIM-o < 0.75** (15d) — the rung after "another take" — or always with `AVE_VOICE_ROUTE=changer`. `AVE_VOICE_ROUTE=tts|changer|auto` (default `auto`).
- Billed by audio seconds, metered in the ledger; the budget check runs before the call.

### 15c · The room (`media/stems.py`, `media/room.py`, `render/compose.py`) — optional extra `room`
- **Stems:** `htdemucs` two-stem (vocals / accompaniment) of the original through `stems.separate`; cached per source sha. An edit replaces the *vocals* of its span and keeps the original *accompaniment* of that span, so music beds and room are untouched; outside the edit the output is **bit-for-bit the original**.
- **Room matching:** `room.estimate_reverb` (RT60 and early/late ratio from the speaker's own decays) and `room.match_room` (a synthetic impulse response convolved onto the dry voice); `room.spectral_match` (smoothed long-term spectrum ratio against the speaker's context, clamped ±6 dB). Applied to every generated take before it is placed.
- Without Demucs the compose path is today's. A clip with no separable accompaniment is detected and skipped.

### 15d · Measured identity and naturalness (`continuity/similarity.py`, `measured.py`) — optional extra `measure`
- **SIM-o:** cosine similarity of speaker embeddings (WavLM speaker-verification model) between the take and the speaker's own speech → `ContinuityReport.voice_match`. Passing needs ≥ 0.75. **UTMOS:** a naturalness MOS of the take → `ContinuityReport.naturalness` (new field, default `None`), 1–5, recorded and shown, gated at ≥ 3.0.
- Models load lazily on first use and are cached; absent → both stay `None` and the take is not blocked (as today).

## Interfaces (so the sub-phases can be built side by side)
- `reference.extract_reference_audio(source, transcript, store, *, exclude=None, speaker=None, min_seconds=…)`.
- `similarity.speaker_similarity(reference: Path, candidate: Path, *, embed=None) -> float | None` and `similarity.naturalness(candidate: Path, *, predict=None) -> float | None` (`embed` / `predict` are injectable for offline tests).
- `stems.separate(wav: Path, out_dir: Path, *, run=None) -> Stems(vocals: Path, accompaniment: Path) | None` and `stems.available() -> bool`.
- `room.RoomProfile`, `room.estimate_reverb(x, sr) -> RoomProfile | None`, `room.match_room(voice, profile, sr) -> np.ndarray`, `room.spectral_match(voice, context, sr) -> np.ndarray`.

## Not in this phase
Lip-sync (17) and inpainting-grade editing (18) stay in the Backlog: they need a sync.so key and a self-hosted GPU.

## As built
*(filled in as each sub-phase closes)*
