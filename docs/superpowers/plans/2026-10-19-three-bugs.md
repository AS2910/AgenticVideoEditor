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
