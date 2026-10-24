# Consent-verified cloning (run 4, item 2)

Before Voltage clones the voice of a speaker in a video, that speaker reads a
random phrase aloud. This replaces the stand-in liveness check of G6 for any
owner with the flag `voices.cloning_verified` on. The code is
`backend/app/safety/consent.py`; the routes are in `backend/app/safety_api.py`
and the review queue in `backend/app/admin_api.py`.

## The gate

1. **The phrase.** The server makes 8 to 12 different words from a fixed list
   of plain, common words (`consent.WORDS`: no numbers, no names, no common
   homophones such as "two" or "right", no words with British and American
   spellings). It belongs to one attempt, can be read once, and is spent after
   10 minutes. English only: a Hindi list would need Whisper to write Hindi in
   one script every time, which it does not (it mixes Devanagari and
   romanised Hindi), so the words rule would fail people who read correctly.
2. **Length.** The recording is at least 4 s. Under that it does not pass.
3. **Words.** Whisper hears the recording. After normalising (NFKC, lower
   case, punctuation and hyphens to spaces, apostrophes dropped), the word
   error rate against the phrase is under 20%. At 20% or more it does not pass.
   Without a real transcriber (mock or dry run), the words cannot be checked
   and the attempt goes to review.
4. **Voice.** SIM-o (`app.continuity.similarity.speaker_similarity`, WavLM
   `microsoft/wavlm-base-plus-sv`, local and free) between the recording and
   the clone's source audio: the named speaker's speech in the video, else the
   speaker with the most speech, cut by the same `extract_reference_audio`
   the clone uses.

| SIM-o | Result |
|---|---|
| 0.92 or more | passed |
| 0.84 to 0.92 | sent for review (a person listens) |
| under 0.84 | did not pass |
| not measured (model unavailable, under 3 s of the speaker in the video) | sent for review |

Every attempt stores the phrase, what was heard, the WER, the SIM-o, the
length, the rule that decided, the bands used, the transcriber and speaker
model names, and the times (created, checked, expires, reviewed). Migration
0039 adds those columns to `liveness_attempts`.

## The review queue

A borderline attempt (status `review`) shows on the admin page (Consent
reviews), with the phrase, what Whisper heard, the scores, the recording and
the speaker's speech from the video to compare. The admins get a bell
notification (`consent_review`). An admin approves or rejects with a reason
(at least a few words). The decision is written to `admin_audit`
(`consent_approve` or `consent_reject`, with the attempt, the video and the
scores) and to the attempt itself (`reviewed_by`, `review_reason`,
`reviewed_at`). The owner gets a `consent_decided` notification. An approved
attempt counts as passed; a rejected one as did not pass, and the owner can
read a new phrase.

## The threshold study

`python -m app.tools.consent_study --out <scratch> --media <artifacts dir of a
database copy> --public frontend/public --manifest docs/cloning-consent-testset.json`

Run on 2026-10-24 on this machine, with no vendor calls: Whisper was not used
(the words rule is not what the study measures; for a test pair the transcript
is the known text, and the gate's tests mock it the same way). The manifest
`docs/cloning-consent-testset.json` lists every clip (its speaker, where it came
from, its role and length), the score distributions, the bands' outcomes and
the median and highest score for every pair of speakers.

**The clips (82).**

- 12 macOS `say` voices (Samantha, Daniel, Karen, Moira, Rishi, Tara, Aman,
  Lekha, Flo, Eddy, Reed, Shelley), each reading one longer "source" passage
  (about 8 s) and two consent phrases made by `consent.phrase`. Each consent
  clip also goes through a phone-like channel (300 to 3400 Hz, pink noise, a
  16 kbit/s Opus round trip), to stand for the same person on a worse
  microphone than the video's.
- Read-only media of the dev database copy: ElevenLabs takes grouped by voice
  id (4 voices, 16 takes, English and Hindi, some shouted), a recorded voice
  sample (a 15 s song clip, cut into three) and a real speaker's video (p60,
  cut into two).
- `frontend/public/sample-ad.mp4`. It was made with `say`'s default voice and
  which voice that is is not known, so its pairs with the `say` voices are left
  out.

A clip is never paired with its own phone copy. That leaves 125 same-speaker
pairs and 3112 different-speaker pairs.

**Results (SIM-o).**

| Pairs | n | min | 5th pct | median | 95th pct | max |
|---|---|---|---|---|---|---|
| same speaker, clean | 37 | 0.889 | 0.925 | 0.968 | 0.987 | 0.989 |
| same speaker, phone vs clean | 60 | 0.835 | 0.900 | 0.954 | 0.982 | 0.993 |
| same voice, ElevenLabs takes or the song sample | 28 | 0.547 | 0.551 | 0.803 | 0.929 | 0.936 |
| different speakers | 3112 | 0.188 | 0.356 | 0.623 | 0.873 | 0.972 |

At the chosen bands (pass 0.92, review from 0.84):

| Pairs | passed | review | did not pass |
|---|---|---|---|
| same speaker, consent-like (clean, phone vs clean), 97 | 90 (93%) | 6 (6%) | 1 (1%) |
| same voice, ElevenLabs takes or the song sample, 28 | 3 | 9 | 16 |
| different speakers, 3112 | 50 (1.6%) | 232 (7.5%) | 2830 (90.9%) |

Error rates at other single thresholds (false accept: different speakers at or
above; false reject: consent-like same pairs below):

| Threshold | 0.84 | 0.86 | 0.88 | 0.90 | 0.92 | 0.94 | 0.96 |
|---|---|---|---|---|---|---|---|
| false accept | 9.1% | 6.6% | 4.5% | 3.0% | 1.6% | 0.6% | 0.1% |
| false reject | 1.0% | 1.0% | 1.0% | 4.1% | 7.2% | 19.6% | 54.6% |

**Why these bands.** The WavLM model card's 0.86 lets 6.6% of different
speakers through here, so it is too low for an automatic pass. At 0.92 about 1
in 60 different-speaker pairs passes, and those are all synthetic voices of one
family (Rishi and Aman, Eddy and Reed, Moira and Tara: the same engine's
voices share its sound); 93% of the same-speaker pairs pass with no person
involved. 0.94 would cut false passes to 0.6% but send one honest reader in five
to a person. 0.84 as the floor keeps all but one of the 97 same-speaker pairs
out of "did not pass" (the one is a phone-channel copy at 0.835), and still
turns away 91% of different speakers without anyone's time. If the review
queue turns out cheap, raise `PASS_AT` to 0.94.

**What the study says about the model.** WavLM base plus SV separates voices of
the same sex and accent poorly: different speakers reach 0.97. The voice rule
is one layer, not the whole gate: the phrase is fresh, single use and short
lived, so a replayed clip of the speaker does not pass the words rule, and the
borderline band puts a person in the loop. The ElevenLabs takes and the song
sample score low against each other (median 0.80): a clone's source that is
singing, shouting or another language does not compare well with read speech,
so those go to review or do not pass, which is the safe side. A stronger
speaker model (an ECAPA-TDNN, or score normalisation against a cohort) is the
next step if false passes matter more than they do in the beta.

**Limits.** The set is small and mostly synthetic: only one real person has two
clips (p60, 0.948). The phone channel is simulated. Re-run the study with real
consent recordings once some exist (only from people who agreed), and move the
bands with the numbers.

## Flags

`voices.cloning_verified` is off for everyone by default, the default owners
too, and it is not in the public profile. Turn it on for everyone with
`python -m app.flags set voices.cloning_verified on --db <db> --owner '*'`, or
per person on the admin page (Features). It needs `golive.g6` (the read-aloud
step). With it on, a video's speaker is cloned once a check of that video has
passed (or a reviewer approved it); withdrawing consent spends the passed check.
It does not open cloning your own voice from an upload: `voices.cloning` still
does that.
