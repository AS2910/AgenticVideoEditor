# Three bugs: renders, dates, an invented line (2026-10-19)

Evidence was gathered before any code changed. Video `p59` in project `f1` "Ashish Testing": `WhatsApp Video 2026-10-19 at 9.43.19 PM.mp4`, 6.93 s.

## 1. Added audio sometimes plays and sometimes doesn't

**What the record says (live DB, UTC):**

| Time | Event |
|---|---|
| 16:16:32 | e1 (English layer, c1) approved by Voltage's ship |
| 16:17:21 | the render of e1 lands: `fe7a1902…` (144 MB) — 49 s for a 6.9 s clip |
| 16:19:47 | turn 2 keeps the Hindi take c2 on plan2's i1 (proposal, ready) |
| 16:20:01 | a render starts (front end: *With proposals*, `ensurePreview`) |
| 16:20:08 | the user's Add it approves c2 → e2 (`overridden`), e1 reverted; `_ship` starts its own render |
| 16:20:11 | that render's ffmpeg starts |
| 16:21:14 | turn 3: Voltage says the swap is done and the video is ready — **no tool ran, no render had finished** |
| 16:21:26 | a third render starts (front end: `syncEdits` after turn 3 → `runExport`) |
| 16:40 (now) | all three ffmpeg processes still running, 18–21 min each; the only finished render on disk is still the English one |

**Causes, each confirmed:**
- **The source is 8K HEVC** (7680×4320, 79 Mbit/s). `compose()` stream-copies only H.264 (`_COPYABLE_VIDEO = {"h264"}`), so a layer-only edit — whose picture is one plain `copy` piece — still re-encodes 8K with libx264. Alone that took 49 s; three at once took 20+ minutes each.
- **No render key, no reuse, no single flight.** `_export` renders synchronously in every request. `/approve` renders, then the front end renders the same edit set again after the turn, and *With proposals* renders a third. Nothing dedupes identical work or orders the results.
- **The front end takes whichever render returns last.** `runExport` sets `rendered` from any response and clears `exporting` on the first to finish, so an older render can overwrite a newer one and "Rendering…" can drop while another runs.
- **"Rendering with the proposals…" can never clear.** `ensurePreview` ignores a request while one is running (`if (previewing) return`); when the running one returns with an old key, nothing asks again, so the status reads "The proposals changed; rendering again…" forever.
- **Hear it plays over a stale final.** `playTake` plays the take over `rendered` whenever the pieces are copies — here the English render — so the Hindi take was heard over the English line it replaced, or alone, depending on the mode.
- **Voltage's "ready" came from memory.** `project_state` has no render status; the ship tool's text says "rendered" and the model repeats it on later turns.
- **Ruled out:** the layer running past the clip's end (it ends at 6.7 s on a 6.93 s clip); a cached stale URL (artifact URLs carry the sha256).

## 2. "1 Jan 1970" on Shared voices

**Cause:** `GET /projects/{id}` sends `"consent": true` (a boolean) on shared voices. The project page formats it with `whenLabel(v.consent)` → `new Date(true)` → epoch + 1 ms → "1 Jan 1970". **The name is not missing from the API**: the row measured in Chrome is `Recorded 79px | "Deewar song" 0px | "consent 1 Jan 1970" 126px | Remove 67px` — the name is squeezed to zero by the tag and the button. One field-name mismatch is real: the page reads `used_in_project`, the API sends `used_in`.

**Every date-like field (before):**

| Field | Stored as | On the wire |
|---|---|---|
| `videos.created_at`, `projects.created_at` | ISO with µs and `+00:00` | same |
| `videos.consent_at` (video consent) | ISO `+00:00` or NULL | `consent: {granted_at}` or null |
| speaker clone consent | not stored separately (the video's) | — |
| `my_voices[].at` (voice made/kept) | ISO `+00:00` | `at` |
| recorded voice consent | **not stored** (the box is required, the moment is lost) | — |
| project voice `consent` | **boolean** | **boolean** |
| `made_voices[].at`, `designs.at`, files `at`, suggestions `at` | ISO `+00:00` | same |
| `messages.at`, `turns.at`, plan `created_at`, plan log `at` | ISO `+00:00` | same |
| `usage.at` (ledger) | ISO `+00:00` | not sent |
| `settings.render.at`, `settings.reading.at` | ISO `+00:00` | `render.at` on the receipt |
| edits (approved) | **no time stored** | — |
| frames `at`, inserts `at` | seconds into the clip (not dates) | — |

Front-end display: `pages/fmt.ts` (`whenLabel`, `monthShort`, `monthLong`) and the call sites on Home, Voices and the project page.

## 3. "謝您的觀看" at 0:06 on a silent stretch

Whisper's answer for this clip's audio (re-run once): language `chinese`, one segment `5.5–6.9 "多謝您的觀看"` with no_speech_prob 0.608, avg_logprob −0.956. The filter drops the segment (0.608 > 0.6). Its words are `多 5.5–6.9`, then `謝 您 的 觀 看` each **zero-length at 6.9–6.9**. The word filter's overlap test is strict (`start < b and a < end`), so a zero-length word exactly on the dropped segment's end is never matched: `多` goes, the five others stay. Statements are filtered, words are not, and the transcript shows the words.

## As built

### 1. Renders — what the cause actually was

Not one cause but four that compounded on an 8K HEVC phone clip: the renderer re-encoded an HEVC picture even when nothing was retimed (49 s alone, 20+ min with three at once); renders had no key, so the approval, the post-turn sync and *With proposals* each rendered the same edit set again, concurrently; the client took whichever answer came back last and ignored a newer preview request while one ran, so the status could stick; and Voltage said "ready" from memory. The layer running past the clip's end and a cached stale URL were ruled out.

**Fix.** `edit_set_hash` (source, mode, each edit's take, span, mix, level, flex, fit, words) keys every render; a finished render for a key is reused (`settings.renders`, last 12); requests for the same key share one render, and one video renders one thing at a time; every request, reuse and completion is logged on `voltage.render` with video, mode, hash, sha, request id and seconds. `GET /videos/{id}/renders` reports each mode against the edits now. HEVC is stream-copied (tag `hvc1`). `project_state` and `ship` say "rendered" only from that record, and the prompt forbids saying it otherwise. The client numbers each request per mode, takes only the latest, clears "Rendering…" with it, counts an approval as a final request, plays Hear it over the final only when it is current, and the player resumes at the same moment when its file changes.

**Tests.** `tests/api/test_render_keys.py`: reuse and a changed set; two overlapping renders out of order; identical requests in flight share one render; a mode switch mid-render; undo then re-add; an agent ship then an immediate preview; HEVC copied. Each checks the audio by correlation with the take (> 0.9 with the line, < 0.3 without). `App.test.tsx`: a late, older final render is dropped; a newer preview request is made while an older runs and only the latest shows. `test_tools.py`: Voltage never calls the video ready without a finished render.

### 2. Dates — what the cause actually was

A boolean (`consent: true`) on shared voices, formatted as a date. The missing name was layout, not data: squeezed to 0 px by the date tag and the button. One real field mismatch (`used_in_project` vs `used_in`). Beyond the bug: times were stored as `+00:00` ISO with microseconds, the ledger compares them as strings, and a recorded voice never stored when its consent box was ticked.

**Fix.** `app/timefmt.py`: every moment is `YYYY-MM-DDTHH:MM:SS.mmmZ` or null, written by every writer; `to_iso` reads any old form (and numbers as seconds or ms); a one-time backfill (`times_v2`) rewrites every stored moment and turns a boolean consent into the entry's own time (a shared voice: its owner's), marked `consent_approximate`, or null — never 0. Consent on the wire is `consent_granted_at`. `src/lib/dates.ts` is the one formatter, in the viewer's zone; anything that is not a moment reads "Not recorded". The voice row is name, then kind · Consent 19 Oct 2026.

**Tests.** `tests/api/test_dates.py` (schema over every answer, `to_iso`, the backfill), `src/lib/dates.test.ts` (null, seconds by mistake, a day-boundary zone, month names), `ProjectPage.test.tsx` (the row), `no-1970.test.tsx` (Home, Voices, a project, Export).

### 3. The invented line — what the cause actually was

The sign-off filter worked: the segment was dropped (no_speech_prob 0.61). Its **words** leaked: five were zero-length at 6.90–6.90 on the dropped segment's end, and the strict overlap test (`start < b and a < end`) never matches a zero-length word on an edge. The energy check would not have caught it either: the tail is 14 dB over the clip's floor (ambient sound), above the 8 dB bar. A second, latent bug: the normaliser stripped Devanagari vowel signs, so Hindi sign-offs could never match.

**Fix.** A word inside or on the edge (±20 ms) of a dropped segment goes with it, in both filters. Sign-offs in Chinese, Japanese, Korean and Hindi, plus "thanks for watching" / "subscribe" stems in any language for segments of eight words or fewer. A segment in another script than the clip's own (read from its confident segments, else Whisper's guess) is dropped at a stricter bar (no_speech_prob > 0.3 or avg_logprob < −0.7); confident code-switching (Hinglish) stays. The normaliser drops only punctuation and symbols.

**Tests.** `tests/adapters/test_invented_speech.py`: this clip's own Whisper answer and audio (`tests/fixtures/whisper-silent-tail-zh.json`, `silent-tail-zh.wav`), a silent tail with a sign-off in ten languages, the script rule both ways, real speech mentioning "watching" kept.

**Not done.** Transcripts already stored keep their words (Whisper's raw answer was not kept); the video `p59` still shows "謝您的觀看" until it is uploaded again.
