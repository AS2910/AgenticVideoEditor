# Good morning: review fixes (overnight run 5)

Branch `overnight/review-fixes`, cut from main `b912fbc`. Worktree `../AgenticVideoEditor-review`.
Not pushed; main untouched. Your running app (main checkout, :8000 and :5173) does not have any of this yet.
Run 4's summary: `git show b912fbc:MORNING.md`.

In one breath:
- **Part 1 is all done and gated together** on this branch: honest errors, fewer confirmations, tips, no invented lines, less to read. None of it is live until you merge (section 9).
- **Fast path:** a 4-word change is ready to hear in 4.8 s p50 / 6.1 s p95 with simulated vendor latency, against 25.7 s / 40.7 s for a full turn.
- **Voice tone:** built and measured, but no clear win yet; the A/B page is ready for your ears.
- **Messy audio:** 20 variants; the top 3 breaks fixed (lines lost under loud music, music dropping out under a new line, phone takes rejected).
- **Batch is public:** `launch.batch_public` is ON.
- **Lip-sync:** foundations only, no provider on. Recommendation: sync.so lipsync-2 first.
- **Real spend: $1.17** of the $4 stop ($1.12 ElevenLabs in item 7, $0.05 Whisper in item 8).
- **Yesterday's "refused on my side"** was an invalid Anthropic key; you replaced it. Item 1 means the next one reads "Something went wrong on our end" and alerts admins.

## 1. What shipped

Each item was built on its own branch (`review/item<N>`, worktrees `../AgenticVideoEditor-v<N>`), one commit, gated there with `make launch-check SKIP_ENV=1`, then cherry-picked here and gated again on this branch.

| # | Item | Commit | Status |
|---|---|---|---|
| - | Gate fix: migration check skips the content cache | 2e53505 | done |
| 1 | Honest error messages | e6353d6 | done |
| 2 | Fewer confirmations | 8b34340 | done |
| 3 | Tips | ffb9da0 | done |
| 4 | Transcription that makes things up | 4c54e46 | done |
| 5 | Less to read | 9f8f39c | done |
| 9 | Lead with many videos at once | b3db466 | done |
| 10 | Lip-sync foundations | 2cc21fc | done |
| 8 | Messy real-world audio | b86529d | done |
| 7 | Voice tone and feel | 4208b80 | partial (see 4) |
| 6 | Fast path for small edits | 4df7778 | done |

Gates on this branch (`make launch-check SKIP_ENV=1`, against a copy of your live database):
- after item 1: backend 2166 passed; one front-end test (SettingsPage) timed out under load and passed alone, then the rerun of every later step passed (550/550, Playwright 145/145, migrations ok).
- items 2, 3 and 5 sat directly on the branch head, so their own passing gate ran on exactly this tree.
- after items 3 and 4: all steps passed (backend 2238, vitest 565, Playwright 148).
- after items 9, 10, 8 and 7 (picked together, then gated once; each had passed its own gate first): all steps passed (backend 2400, vitest 589, Playwright 152).
- after item 6, the final tree: **all steps passed** (backend 2420 passed, 16 skipped; vitest 597/597; build; lint; Playwright 152/152; migrations ok; em dash check).

Flaky under the night's load (load averages up to about 400 while five gates ran at once): single timeouts in Thumbs, SettingsPage, NotificationBell and go-run.spec; each passed on rerun, none is in code changed tonight.

Conflicts resolved while merging: appended blocks in DECISIONS.md, PROGRESS.md and `.env.example`; the batch panel's tip line (items 3 and 9); test blocks in conftest, LineDoc and the room tests; App.tsx's import list (items 5 and 6). One real interaction: items 7 and 8 together let a noisy take pass the clarity check; fixed inside item 7's commit with a regression test.

## 2. Part 1: ready for beta?

All five are on this branch and pass the gate together. Live = after you merge to main and restart (section 9).

1. **Honest error messages: ready.** One classifier (`backend/app/failures.py`) for every failure a person can read: agent turns, transcription, voicing, cloning, renders, exports, batches, the job runner.
   - Our side (bad or missing key, vendor auth, quota, outage, timeout): "Something went wrong on our end. Nothing was charged. Try again in a minute." The real cause goes to Admin > Feedback > Errors reported (and Sentry when set), plus a new admin bell and email notice "Failures on our side", at most once per vendor and cause every 30 minutes.
   - A vendor's safety filter: names the line ("the line at 0:06 (...)") and says to reword it.
   - Your input: what and how to fix it.
   - "Nothing was charged" is kept true: every voice call refunds on failure; a turn that paid for earlier steps says what it spent instead.
   - 25 tests force each failure through a mocked vendor (Anthropic 401/403/429/500/timeout/reset, ElevenLabs 401/429/reset/refusal, OpenAI 401/500/timeout/reset).
2. **Fewer confirmations: ready.** Settings: "Ask me before spending more than $X" (default $0.25 a turn, per user). Under it Voltage voices without asking. Over it: one card whose button names the step and price ("Voice it here · $0.04"); picking an option is the approval; no separate Move it. Meaning questions (which line, which voice) are still asked. Test: a $0.04 voice-over is one click from request to a proposal you can hear.
3. **Tips: ready.** All 29 first-time tips go through one queue: one on screen, two a session (30 idle minutes ends a session; the count survives reloads), in Voltage's pane or under the top bar, never over the transcript or player (Playwright checks at three sizes). Fixed a real bug: Got it was only saved for 10 of the 29 tips; the other 19 came back after every reload.
4. **No invented lines: ready.** Voice activity detection before transcription (only speech is sent; a silent clip makes no call), sound captions ("[Music]", "♪") always dropped, subtitle credits in 8 more languages, off-language segments kept only if confident and at least 1 s, high no-speech segments dropped. Zero invented lines on a silent clip, a WhatsApp-style clip, a music-only clip and a clip with no audio track. Speech under loud music is still transcribed (item 8's fix, built in). **A video with no audio track is now accepted** (it gets a silent track, is never transcribed or charged, and opens the Voice-over panel).
5. **Less to read: ready.** New and existing users start in a simple view (player, transcript, Voltage pane); "More controls" in the header brings back the three-way switch, tracks, counts, timing bar, Voice / Bed / Effect and Fine-tune, remembered per user. "Hear changes" on/off replaces the three-way switch. Monospace capitals only on timecodes and costs (a Playwright test fails on any other). Plain words ("Spent $0.34 of $10", "Asks you before spending over $0.25"). Voltage replies are two sentences; the rest goes behind "Why?" (nothing is deleted). The "Get started" pill no longer covers the transcript.

## 3. Fast path timings (item 6)

Click a line, change the words, press Enter. Up to 8 changed words in one existing line, same voice, under the spending limit: no planning, one take with the line's voice and delivery, the fit check, a proposal ready to hear. A fit failure hands over to a full turn with a note. Story checks (a different price or percentage on another line, a negated repeat, a repeated 3+ word run) run after and show one gentle "Worth a look" message; they are local and free.

**Simulated vendor latency** (the rehearsal's timed mocks, LOAD.md values: Claude 1 to 3 s a call, a voiced line 2 to 6 s, a render 5 to 20 s), 4-word change, 24 runs each:

| Path | p50 | p95 |
|---|---|---|
| Fast path, Enter to proposal ready | 4.8 s | 6.1 s |
| Full turn, its take ready mid-turn | 6.8 s | 8.2 s |
| Full turn, turn finished | 25.7 s | 40.7 s |

From your real history (read-only copy of the database): full turns p50 25.1 s, p95 95.3 s (30 turns); single line voicings, which is what the fast path runs, p50 6.4 s, p95 34.4 s (55 jobs). So under 15 s holds at p50; the real p95 is the voice vendor's tail. Not measured with real vendors (no spend allowed in item 6).

## 4. Voice tone, before and after (item 7)

- When only the voice changes, the take is the original line converted into the new voice (speech to speech), so pace and emotion follow the original. When the words change, ElevenLabs has no audio style reference; steering the first take from the original's measured settings is built but off (`AVE_VOICE_TONE_REFERENCE`): it cost naturalness for no gain.
- Each take is measured against the speaker's neighbouring lines (pitch register, range, rate, contour) and retaken if outside; lines asked for in a particular delivery are never refused.
- The take gets the room's EQ and reverb when the room is clean enough, and room tone loops smoothly under it.
- A prosody distance ranks takes and shows on the card as "Delivery".

Real vendors, your owl story (p66, its existing clone; no new clone made), 5 lines, old method vs as shipped:

| Voice similarity | Naturalness (UTMOS) | Delivery gap | Loudness delta | Duration error |
|---|---|---|---|---|
| 0.964 to 0.957 | 4.13 to 4.06 | 1.30 to 1.26 | 0.65 to 0.80 dB | 0.146 to 0.092 s |

No clear win: the old method run twice moved the delivery gap by up to 0.5. No take was refused on this clip. Spend $1.12.

**A/B page:** `#admin/voice-ab` (admins), original line then the old and new takes in blind order, a vote, then which was which and the scores. The eval's clips are of your own video, so they are kept on this machine only (git-ignored, `backend/evals/results/voice-ab/`). They are in `../AgenticVideoEditor-v7/backend/evals/results/voice-ab/`; copy that folder into the main checkout after you merge (section 9) so the page has trials. Your votes should decide whether room EQ and reverb stay on takes.

## 5. Messy audio (item 8)

Upload now listens for music or noise under the speech (0.4 s for a 49 s clip) and separates it with Demucs in the background (12 to 24 s a clip under heavy load), so a replaced line keeps the bed. `backend/evals/messy/` makes 20 variants (music, cafe noise, echo, crosstalk, phone, clipped) and reports per stage; `evals/messy/real/` waits for your 20 real clips.

Top 3 fixed: lines lost under a loud music bed (recall 0.17 to 1.00), music dropping out under a new line (1% to 96 to 100% kept; heavy cafe noise 76%), a good take refused on a phone clip with dropouts (0.10 to 1.00).

Still broken: clipped audio (a new take needs more level correction than allowed), crowd babble mostly stays in the voice track (5 to 15% of it kept), Whisper puts the first word about 0.4 s early on every clip, one line end off by 0.46 s on the hardest variant.

Combining items 7 and 8 briefly let a noisy take pass the clarity check; fixed in item 7's commit (clarity is judged before the room's EQ), with a test.

## 6. Batch public: ON (item 9)

`launch.batch_public`, default on, turns on `projects.batch` for the public profile: B1 (one goal across many videos), B2 (language versions), B3 (export everything). The paid project check and review stages stay off for the public. B1 has example prompts ("Make every offer line say 25% off"), a gate that says "You pay at most $X for all of it" and a results board that opens with one plain sentence. The batch journeys run in the rehearsal suite with mocks (2 of 2 passes). The landing page now leads with "For ad teams and agencies. Change every ad at once. Offers, prices, languages." and single-video editing is the second section.

## 7. Lip-sync foundations (item 10)

- On upload, each line is marked on camera, off camera or unsure (face found, mouth moving with the sound), 0.2 to 0.4 s per second of video, in the background.
- Voltage prefers off-camera lines; a changed on-camera line says "... is on screen saying this line, so the lips won't match yet."
- `LipSyncProvider`: only the changed span plus 0.5 s handles goes out, never across a cut, and is stitched back frame for frame. A fake provider, a sync.so stub and a self-hosted LatentSync stub; a provider needs both `AVE_LIPSYNC_PROVIDER` and its key, so your sync.so key alone does nothing. `/health` says lip-sync is off.
- Quality: a 0 to 1 confidence (SyncNet when installed), and a side-by-side review on the admin page.

**LIPSYNC.md recommends** sync.so lipsync-2 first (about $0.18 a 3 s line), then try fal.ai LatentSync ($0.20 a span; needs a new account), self-host only at volume; Wav2Lip is out (non-commercial licence). Not yet checked on real talking-head clips (none here); before turning a provider on: real clips, wire it into export, make export a job.

## 8. Decisions to confirm

All logged in DECISIONS.md (section "Run 5").

1. Item 1: ElevenLabs safety refusals are recognised by pattern (no real moderation payload was available); a missing ffmpeg now gets the "our end" sentence; missing-key and vendor-failure alerts email admins by default.
2. Item 2: Voltage's own thinking cost is not counted against the limit; the limit applies only under Check with me; consent is asked before the first turn when the limit is above $0; $0.00 means always ask.
3. Item 3: a session is 30 idle minutes, counted per browser; tips take room in the page (content moves down) instead of floating.
4. Item 4: a clip whose only line is "Thank you." gets no lines; music-only clips are still sent (and paid) because loud sound is always sent to protect speech under music; **transcription is still billed for the clip's full length even when only speech or nothing was sent** (an overcharge; cost work was out of scope).
5. Item 5: existing users also start in the simple view; Hear changes plays proposals when there are any; the facts line goes behind Why?.
6. Item 6: story checks are local heuristics (a Claude check would be about $0.002 a line); a delivery-only change still takes the full turn; the fast path skips the preview render.
7. Item 7: reference settings off; room EQ and reverb on takes until the A/B votes say otherwise.
8. Item 8: bed threshold 28 dB; separation on by default; clips heard clean at upload are never separated.
9. Item 9: the public gets batch only, not the project check or review stages; B3 exports every video when stages are off.
10. Item 10: the lips note shows only on changed lines; the provider recommendation above.

## 9. How to go live for beta

1. Back up the database: `cp backend/var/ave.db backend/var/ave.db.bak-20261028-pre-review-fixes`.
2. Merge in a worktree, then fast-forward main (never merge in the main checkout while uvicorn reloads there).
3. Migrations: item 7 adds 0047 (`voice_ab_votes`). Nothing else adds one. Apply with the usual migrate step; `make migrations-check` passes on a copy of your live database.
4. Restart the backend (the new settings are read at start).
5. New settings, all optional, in `.env.example`: `AVE_STEMS_ON_UPLOAD`, `AVE_ON_CAMERA`, `AVE_LIPSYNC_PROVIDER`, `AVE_LIPSYNC_MODEL`, `LIPSYNC_SELFHOSTED_URL` and `_TOKEN` and `_USD_PER_SECOND`, `AVE_MODEL_CACHE`, `AVE_MOUTH_MEASURE`, `AVE_VOICE_TONE`, `AVE_VOICE_TONE_REFERENCE`, `AVE_VOICE_AB_DIR`. Your existing `SYNC_API_KEY` does nothing unless `AVE_LIPSYNC_PROVIDER=sync_so`.
6. Copy the A/B trials: `cp -R ../AgenticVideoEditor-v7/backend/evals/results/voice-ab backend/evals/results/`.
7. Run the rehearsal suite once against the stack (item 2 changed button wording the helper now expects; item 9 ran it).

## 10. LAUNCH BLOCKERS (refreshed)

Fixed tonight and off the list: errors that blamed the user or showed SDK text; invented lines on silent or music clips; uploads with no audio refused.

Still unsafe for public users, most serious first (unchanged from run 4 unless noted):

1. **No production deployment exists.** provision.sh and deploy.sh have never run on a real VM.
2. **Legal pages are drafts.** Don't open sign-ups until a lawyer replaces them.
3. **No email provider.** No address confirmation, password reset, receipts, or (new) admin failure emails without Resend.
4. **Prices sell at about cost.**
5. **Payments untested against the real providers.**
6. **Off-machine backups aren't configured.**
7. **No real end-to-end run on the VM.**
8. **The sample video is a placeholder.**
9. **Abuse reports, consent reviews, beta feedback and (new) "Failures on our side" need a person watching.**
10. **New: transcription is billed for the full clip length** even when VAD sends less. Fine for a free beta, wrong once people pay.

Not blockers, worth knowing: fast-path p95 depends on the voice vendor's tail; voice tone shows no measured win yet; lip-sync is off; clipped audio and crowd babble still break voice matching.
