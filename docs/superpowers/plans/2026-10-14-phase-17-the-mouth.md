# Phase 17 — The mouth

**Written 2026-10-14.** Roadmap 5 / natural-fit Phase 17. Vendor: **sync.so** (key `SYNC_API_KEY` in `backend/.env`, checked 2026-10-14: `GET /v2/generations` → 200, a wrong key → 401). **Exit (from the roadmap):** LSE-D on edited spans within 1.0 of the original footage's own score. Tests never call the vendor (recorded fakes); the mock lip-sync stays and is selected without a key or under dry-run; the heavy/optional pieces are optional extras.

## What the vendor does (read from sync.so's docs, 2026-10-14)
`POST /v2/assets/upload` `{fileName, contentType, size}` → `{uploadUrl, url}`; `PUT` the bytes to `uploadUrl` (no key); `POST /v2/assets` `{url, type: VIDEO|AUDIO, name}` → asset id. `POST /v2/generate` `{model, input:[{type:"video",assetId},{type:"audio",assetId}], options:{sync_mode, temperature, active_speaker_detection:{auto_detect}, occlusion_detection_enabled}}` → `{id, status}`. Poll `GET /v2/generate/{id}` until `COMPLETED` (→ `outputUrl`, `outputDuration`) or `FAILED` / `REJECTED` (→ `error`, `errorCode`). `POST /v2/generations/estimate` prices a job. Models: `lipsync-2` (talking heads), `sync-3` (angles and obstructions), `lipsync-2-pro`. It is billed by the second of video, so only the seconds that need a new mouth are sent.

## The shape of the problem (found on the live-check clip, p3)
An ad is cut: in one 2-second edit the picture goes phone close-up → shopkeeper → courier. A mouth can only be moved where a face is on screen, and a render that sends the whole span wastes money and invites the model to invent a face. So:

### 17a · The adapter (`adapters/sync_so.py`)
`SyncSoLipSyncAdapter.sync(source, plan, audio)`: cut the video of the span (and the take's audio) → upload → generate → poll → download → the frames artifact. Retries and the job runner's backoff as for every vendor (`VendorError` transient, `NonRetryableError` for key/quota/rejection). The estimate is charged to the ledger **before** the call and reconciled after; the project's spend ceiling applies. A `REJECTED` / `FAILED` job (no face found, too short) is not a crash: the candidate keeps its original picture and says why in a sentence. Model by `AVE_LIPSYNC_MODEL` (default `lipsync-2`), chosen per shot by the spike's result.

### 17b · Where there is a mouth to move (`media/faces.py`, `media/shots.py`)
Split the edit's span at the picture's cuts (`shots.cuts`); in each shot sample frames and detect a face (OpenCV frontal + profile Haar cascades, optional extra `mouth`); a shot is sent only if a face is in ≥ 60% of sampled frames and the stretch is ≥ 0.4 s (below that the vendor refuses). More than one face → `active_speaker_detection.auto_detect`. The rest of the span keeps the original frames.

### 17c · Composite (`render/compose.py`)
`compose(..., use_generated_frames=True)`: over each sent stretch the output picture is the vendor's frames, frame-exact (the same filter graph as Phase 16's pieces), with the original picture before and after; audio is untouched. Only plain "replace" spans (flexed, living and held pieces are retimed and keep their picture, and the export says so). The export manifest says which seconds got a new mouth.

### 17d · Measured lip-sync (`continuity/lipsync_measure.py`, optional extra `mouth`)
LSE-D / LSE-C (SyncNet: audio-visual offset distance and confidence) of the edited stretch against the take's audio, and of the original footage's own speech for the baseline → `ContinuityReport.lip_sync` (0–1: 1 at the original's own LSE-D, falling linearly to 0 at +4.0). Pass needs the take within 1.0 LSE-D of the original. None when the model is unavailable or no face is found; a None blocks nothing.

## Spike (before 17a is trusted)
The same ~2 s face stretch of p3 through `lipsync-2` and `sync-3` with a real take's audio; record cost per second, latency, output size/fps/resolution match, and a look at the result. The cheaper model that keeps the picture's resolution wins; the numbers go in "As built".

## Not in this phase
Inpainting-grade editing (18, needs a self-hosted GPU). A face crop composite (only the mouth region over the original frame) is a refinement if the vendor's frames show a resolution or colour mismatch in the spike.

## As built
**Status 2026-10-14 (paused by the user, branch `phase-17-the-mouth`, committed as work in progress, not merged).**

**Built and tested offline** (backend suite not yet re-run in full after this phase; the new tests pass, and `tests/conftest.py` now blanks `SYNC_API_KEY` so no test can spend):
- **17a** `adapters/sync_so.py`, the vendor client: presigned asset upload → register → `POST /v2/generate` → poll → download (the result URL redirects, so redirects are followed and the key is never sent to storage or the download). Errors are plain sentences of the right kind (`MouthError` retryable, `MouthConfigError` and `MouthRefused` not). 20 tests on httpx's mock transport.
- **17b** `media/faces.py`: YuNet face detection (230 KB model vendored in `media/models/`, optional extra `mouth`), a face must be whole in the frame and ≥ 10% of its height, shots split at cuts, a shot is sent only with a face in ≥ 60% of samples and ≥ 0.4 s. 9 tests.
- **17c** `render/mouth.py`: per approved *replace* edit, only the face stretches are cut and sent with the take's slice of audio; cached by (source, take, offset, stretch, model) so a repeat export is free; the spend ceiling is checked cumulatively before anything is sent; up to 4 stretches in flight; a vendor failure never fails the export (the stretch keeps its picture and the result says why); `patch_video` lays the clips into the source picture frame-exact (a clip a frame short is padded) and copies the soundtrack through. `_export` uses it when `SYNC_API_KEY` is set (`AVE_LIPSYNC=0` switches it off, `AVE_LIPSYNC_MODEL` picks the model); the export response has a `mouth` report, shown by the export bar; spend appears as "Mouth" in the meter. 16 + 2 API tests.
- **17d** `continuity/lipsync_measure.py` (SyncNet v2 LSE-C/D, subagent-built, **report received, code not yet reviewed by me**): `lse()`, `lip_sync_score()`, `PASS_WITHIN = 1.0`; weights `syncnet_v2.model` (54.6 MB, Oxford, cached in `~/.cache/voltage/syncnet/`); 84 continuity tests pass offline. On VGG's own sync example it reproduces the published numbers (offset 3, LSE-D 5.34 vs 5.35, LSE-C 9.95 vs 10.02) and reacts correctly to shifted and unrelated audio. **On p3 it finds no sync signal even in the untouched original** (pooled LSE-D 11.8, LSE-C 0.9; shifting the audio makes no difference), so p3's footage (probably generated or dubbed audio) cannot be the "original footage's own score" baseline the roadmap exit assumes. Rule it recommends: trust a baseline only when the original's LSE-C ≥ ~4 and best offset within ±5 frames (synced footage reads 7–10, +2/+3, LSE-D ~5.5–6); otherwise `lip_sync` is None. The exit criterion therefore needs a clip with real synced speech to test on, or a different baseline. Not wired into the export / `ContinuityReport.lip_sync`; 224×224 colour face crops, not Wav2Lip's grayscale lip crop.

**Spike results (live, real money: about $0.36 in total, outside any project's meter):**
| | lipsync-2 | sync-3 |
|---|---|---|
| price | $0.06 / s | $0.16 / s (lipsync-2-pro: $0.10 / s) |
| latency for a 1.3 s clip | ~58 s | ~57 s |
| output | 1280×720, 30 fps, same frame count, soundtrack = the take | same |
| look | mouth opens a little, subtle | mouth opens wide, expressive |
Face, glasses, hand and background identical to the original in both. **Default `lipsync-2`.** Lessons the spike forced: a face half out of the frame was "detected" and useless (fixed: must be whole and big enough); a fast montage has soft cuts a 0.35 scene threshold misses (the mouth step uses 0.15); the estimate endpoint wants `{model, duration}` and answers `estimatedGenerationCost`.

**Open problem to look at first when resuming:** a real export of p3 (`main._export(repo.get("p3"))`, five replace edits, 3.9 s of face stretches ≈ $0.23) ran for over ten minutes **without sending anything to sync.so** (its generations list showed only the three spike jobs), so it was stopped; nothing was charged. It stalls before the vendor call. Suspects, in order: `_pieces` (motion analysis for flexed and living pieces), the Demucs separation of the whole 49 s clip on CPU (`AVE_STEMS=1`, first run also downloads weights — run with `AVE_STEMS=0` to rule it out), then `shots.cuts(…, 0.15)` and `faces.stretches` (a 49 s scan took seconds in the preview, so unlikely). Time each step of `_export` separately. This also argues for making the export a background job (the chaos pass's backlog item): with the mouth step it can now take minutes.

**Still to do:** find and fix the stall; the live end-to-end export and a look at the result; wire the LSE measure (`ContinuityReport.lip_sync`, edited vs the original footage's own score, exit: within 1.0) into the export report; make the export a job; full backend + frontend suites and build, docs, merge.
