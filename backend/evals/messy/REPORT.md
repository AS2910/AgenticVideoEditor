# Messy real-world audio: what breaks (run 5, item 8, 2026-10-27)

20 variants of `evals/clips/chai.mp4` (five lines, two speakers) plus the clean
control, made by `python -m evals.messy build` (music beds, cafe noise, babble,
hum, three rooms, crosstalk, phone, dropouts, clipping, two combinations; see
`variants.py`). Scored by `python -m evals.messy run`, tabled by
`python -m evals.messy report <after> --before <before>`. Results:
`results/*-before.json` (main as it was) and `results/*-after.json` (with the
three fixes below).

## What ran for real, and what did not

- **Transcription: real**, all 21 clips: OpenAI `whisper-1` plus
  `gpt-4o-transcribe-diarize`, through the app's own adapter. 42 paid calls,
  about $0.05. Every response is cached by the audio's sha (`out/cache/`), so
  the before and after runs re-score the same answers at no cost.
- **Voice matching: local, no vendor.** The app's measured continuity check
  (WavLM SIM-o and UTMOS, the `measure` extra) on replacing line 4, with the
  speaker's own clean line as the take: a perfect take, so any failure is the
  messy context's fault. A real ElevenLabs take was planned (one call, cached):
  the first try named a voice the account does not have (404, not billed), and
  from then on this sandbox could not reach api.elevenlabs.io at all. No
  ElevenLabs spend.
- **Timing: real Whisper word times** against where the clean clip's own
  transcript puts each line.
- **Bed under the new line: local**, through `render.compose.splice` with real
  Demucs stems.

## Breakage table (before -> after)

| Variant | Transcription | Voice matching | Timing | Bed under the new line (no stems / stems) |
| --- | --- | --- | --- | --- |
| clean | ok (recall 1.00) | ok (match 0.972, mix 1.0) | ok (worst edge 0.00 s) |  |
| music_soft | ok (recall 1.00) | ok (match 0.969, mix 1.0) | ok (worst edge 0.12 s) | 0.019 / 0.445 |
| music_mid | ok (recall 1.00) | ok (match 0.963, mix 1.0) | ok (worst edge 0.12 s) | 0.013 / 0.961 |
| music_loud | BREAK -> **ok** (recall 1.00) | ok (match 0.959, mix 1.0) | BREAK -> **ok** (worst edge 0.12 s) | 0.007 / 0.967 |
| music_beat_loud | ok (recall 1.00) | ok (match 0.97, mix 1.0) | ok (worst edge 0.12 s) | 0.009 / 1.023 |
| cafe_light | ok (recall 1.00) | ok (match 0.972, mix 1.0) | ok (worst edge 0.12 s) | -0.081 / 0.145 |
| cafe_heavy | ok (recall 1.00) | ok (match 0.933, mix 1.0) | ok (worst edge 0.12 s) | -0.013 / 0.762 |
| babble | ok (recall 1.00) | ok (match 0.953, mix 0.993) | ok (worst edge 0.16 s) | 0.051 / 0.056 |
| hum_hiss | ok (recall 1.00) | ok (match 0.963, mix 1.0) | ok (worst edge 0.12 s) | 0.059 / 0.966 |
| echo_small | ok (recall 1.00) | ok (match 0.95, mix 1.0) | ok (worst edge 0.04 s) |  |
| echo_large | ok (recall 1.00) | ok (match 0.948, mix 0.997) | ok (worst edge 0.12 s) |  |
| echo_far | ok (recall 1.00) | ok (match 0.858, mix 1.0) | ok (worst edge 0.18 s) |  |
| crosstalk_brief | ok (recall 1.00, 7 extra words) | ok (match 0.965, mix 1.0) | ok (worst edge 0.14 s) |  |
| crosstalk_heavy | ok (recall 1.00, 7 extra words) | ok (match 0.96, mix 1.0) | ok (worst edge 0.14 s) |  |
| phone | ok (recall 1.00) | ok (match 0.97, mix 1.0) | ok (worst edge 0.20 s) |  |
| phone_dropouts | ok (recall 1.00) | BREAK -> **ok** (match 0.955, mix 1.0) | ok (worst edge 0.04 s) |  |
| phone_noisy | ok (recall 1.00) | ok (match 0.928, mix 1.0) | ok (worst edge 0.04 s) |  |
| clipped_mild | ok (recall 1.00) | BREAK (match 0.958, mix 0.774) | ok (worst edge 0.14 s) |  |
| clipped_hard | ok (recall 1.00) | BREAK (Level is +12.4 dB off the surrounding speech, too far to correct.) | ok (worst edge 0.12 s) |  |
| music_echo | ok (recall 1.00) | ok (match 0.947, mix 1.0) | ok (worst edge 0.12 s) |  |
| everything | ok (recall 1.00) | ok (match 0.824, mix 1.0) | BREAK (an edge moves 0.46 s) |  |

Breaks: transcription 0, voice matching 2, timing 1 (of 21 rows, the clean control included). Spend this run: $0.0000.

"Bed under the new line" is how much of the true bed (the variant minus the
clean clip) still plays inside a replaced line: 0 is gone, 1 is all of it.
Without stems the bed always dropped out. Before the fix it dropped out even
with stems, because the chai voices are dry (see fix 2); the "stems" column is
after.

## The top 3 fixes

1. **Lines lost under a loud music bed (transcription).** `music_loud`: Whisper
   heard all six segments, confidently (no-speech 0.03), and the app's own
   silence screen (`without_silent_speech`) dropped four of them: under a bed,
   the quietest tenth of the clip *is* the music, so speech 6 dB over the music
   read as 7 to 8 dB "over the floor", under the 8 dB bar. Fix: a statement
   that misses the floor bar gets a second chance against the level between
   the words (4 dB over it). An invented line over music alone is still
   dropped (test). Before: recall 0.17, 4 of 5 lines lost, 4 lines without a
   span. After: recall 1.00, nothing lost.
2. **The bed dropped out under a replaced line (render).** `compose.Room.prepare`
   returned None whenever the voice had no reverb tail to read (a dry voice: a
   lavalier, a voice-over, these `say` voices), and the compositor then
   replaced the whole mix, music and all. Fix: the bed stays; only the reverb
   match is skipped. Before: 0.7 to 1.9% of a music bed under the new line.
   After: 96 to 100% (music_mid, music_loud, music_beat_loud, hum_hiss), 76%
   cafe_heavy. Plus separation on upload, below.
3. **A perfect take failed on a phone clip with dropouts (voice matching).**
   Dropped packets read 50 dB and more under the speech; the clarity check took
   them as the room's floor, so the context looked far clearer than it sounds
   and the speaker's own line failed as "noisier than the surrounding audio".
   Fix: clarity reads its floor only from frames within 40 dB of the speech.
   Before: integration 0.10, failed. After: 1.00, passed.

## Separation on upload

`media/bed.py` measures the gap between the speech and the quietest tenth of
the clip (0.4 s for 49 s). Every bed variant measured 10 to 24 dB, every other
32 dB and up; the threshold is 28 dB. With a bed, the upload starts a
`separate` job on the work pool (Demucs htdemucs, cached per source); a clean
clip is never separated, at upload or at export. Timings on this laptop under a
load average of 150 to 250: 12 to 17 s for each 13 s variant, 24 s for a 49 s
clip. The Phase 17 "export of the 49 s clip stalled over 10 minutes" was not
Demucs.

## Still broken (not fixed tonight)

- `clipped_mild`, `clipped_hard`: a take at a normal level is 12 dB and more
  under a clip recorded too hot; the level correction is capped at 12 dB and
  the take fails. That is the new take's loudness match (item 7's area), left
  for it.
- `everything`: line 2's end moves 0.46 s (Whisper runs the line into the
  next under music, cafe, room and phone at once).
- Babble and light cafe noise mostly stay with the voice in Demucs' vocals stem
  (5 to 15% of the bed kept): crowd noise is voice-like.
- On every clip, clean included, Whisper pins the first word to 0.0 s (0.4 s
  early) and the continuity check cannot judge line 2 (too little of the same
  speaker's speech within 3 s). Not caused by the mess, so not counted.
- Crosstalk is transcribed (the second voice really speaks), as a line of its
  own; diarization labels 93% of words right.
