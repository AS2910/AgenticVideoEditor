# Lip-sync: options and a recommendation

Written 2026-10-27 (overnight run 5, item 10). No provider is switched on. This page is for the owner to pick one.

## What is built (no provider yet)

- **Who is seen saying each line.** On upload, each spoken line is looked at in the background (`backend/app/lipsync/on_camera.py`): a face finder (YuNet, the 230 KB model from Phase 17) on the picture at 12.5 frames a second, and the mouth's movement compared with the head's and with the line's changes in loudness. Each line is stored as `on_camera`, `off_camera` or `unsure` in the video's settings (`on_camera`), and comes back on every statement.
- **Voltage and the editor use it.** Voltage's transcript marks `[on camera]` and `[maybe on camera]` lines, and is told to prefer an off-camera line when either would do, and to say once that the lips won't match yet when it changes an on-camera one. In the editor, a changed line whose speaker is on camera says "The Customer is on screen saying this line, so the lips won't match yet." (softer for unsure; nothing for off camera). The moved-line warning now ends "won't match yet." too.
- **The seam.** `LipSyncProvider` (`backend/app/lipsync/provider.py`): source clip span plus new audio in, replaced span out. Only the changed span plus 0.5 s handles each side is cut and sent (never across a cut, never past the clip's ends), and the result is laid back frame for frame (Phase 17's patch graph).
- **Providers.** `fake` (tests and the review page, free), `sync_so` (hosted, wraps Phase 17's tested client), `selfhosted` (an HTTP endpoint we would run LatentSync behind). Both real ones need `AVE_LIPSYNC_PROVIDER` set to their name AND their key or URL; a key alone sends nothing. `/health` says `lipsync: off`.
- **Quality harness.** `backend/app/lipsync/quality.py`: a 0 to 1 confidence per clip, by SyncNet's LSE-C when torch is there (Phase 17's measure, reviewed tonight: https download, pinned SHA-256, weights-only load), else by the cheap mouth-motion read. A result passes when it scores at least 80% of the original window's own score.
- **Review page.** Admin, "Lip-sync review": load a video, see each line's verdict, run one line through a provider, watch the original window and the result side by side, each with its score.

## Measured tonight

| What | Number |
|---|---|
| On-camera look, CPU, while the machine ran four other builds | 0.18 to 0.40 s per second of video (75 s clip: 15 s; 13 s clip: 4.8 s) |
| On VGG's SyncNet sample (a real talking face, 12.7 s) | all 3 lines on camera; a still frame of the same face under the same speech: all off camera |
| On the eval fixtures and rehearsal clips (title cards, screen recordings) | every line off camera |
| SyncNet on the same sample | LSE-D 5.34, LSE-C 9.95, offset +3 (published: 5.35, 10.02), 15 s including the model load |
| Known limit of the cheap read | a moving mouth under other speech (a dub) can still read on camera; that errs on the side of showing the note |

## The options

Prices are list prices found on 2026-10-27 unless marked measured. "Per span" assumes our shape: a 1 to 5 s line plus 1 s of handles.

| Option | Quality and weak spots | Speed | Cost | Licence |
|---|---|---|---|---|
| **sync.so lipsync-2** (hosted) | Good on frontal talking heads. Measured: 1280x720 at 30 fps kept, same frame count, face and background untouched, mouth movement subtle. | Measured ~58 s for a 1.3 s clip | Measured $0.06/s = **$3.60/min**; a 3 s span is about $0.18 | Commercial API |
| sync.so lipsync-2-pro | Better teeth and detail (vendor claim, unverified) | Similar (unverified) | Measured $0.10/s = $6.00/min | Commercial API |
| sync.so sync-3 | Measured: mouth opens wider, more expressive; built for angles and obstructions | Measured ~57 s for 1.3 s | Measured $0.16/s = $9.60/min | Commercial API |
| fal.ai LatentSync (hosted open model) | Diffusion; sharper than Wav2Lip; some flicker; weak on profiles and occlusion | Queue plus GPU (unverified) | $0.20 flat per request up to 40 s, so about **$0.20 per span** ([fal](https://fal.ai/models/fal-ai/latentsync)) | Apache-2.0 weights; fal's terms |
| fal.ai Kling LipSync | Built for generated video; unverified on real footage | Unverified | $0.014 per second, rounded up to 5 s: at least $0.07 per span (medium confidence) | fal's terms (unverified) |
| HeyGen, Tavus | Avatar and translation products, not a span-replace API | Minutes | No clear per-minute API price found (low confidence) | Commercial |
| **LatentSync 1.6** (self-hosted) | Best open quality; flicker, profiles and occlusion are weak | Needs 18 GB VRAM (8 GB for 1.5); roughly 5 to 20 s of GPU per second of video (unverified) | About $0.10 to $0.50/min on an L4 or A10G at ~$0.8 to $1/hr, plus cold starts that dominate 1 to 5 s jobs (estimate) | Apache-2.0 ([repo](https://github.com/bytedance/LatentSync)), commercial use allowed |
| MuseTalk 1.5 (self-hosted) | Real time, but a 256x256 face region: soft at 720p and up | ~1x real time on a V100 | Under $0.05/min (estimate) | Reported MIT; not verified on the official repo |
| Wav2Lip, Video-Retalking | 96x96 mouth, blurry at HD | Fast | Cheap | **Non-commercial** ([Wav2Lip](https://github.com/Rudrabha/Wav2Lip)); not usable for ads |

## Recommendation

1. **Ship the foundations as built, with no provider, for beta.** The note is honest and the agent steers to off-camera lines first. Nothing costs money.
2. **First provider: sync.so lipsync-2.** It is the only option we have measured on our own footage, the client is written and tested, it keeps the picture's size and frame rate, and it is commercial. With span-only sending, a typical changed line costs about $0.18 and about a minute of waiting. Charge it per changed on-camera line, only after the user asks for it ("Match the lips · $0.18"), and gate the result on the quality harness (at least 80% of the original's own score, else keep the original picture and say so).
3. **Trial fal.ai LatentSync next.** At a flat $0.20 per span it is about the same as lipsync-2 for a 3 s span and cheaper for long ones, with Apache-2.0 weights; it needs a fal account and key (the owner's call; none was created tonight). It plugs into the same seam.
4. **Self-host LatentSync only at volume.** A warm 24 GB GPU costs about $600 a month before any use; it pays once hosted spend passes that, and the `selfhosted` stub is ready for it.
5. **Never Wav2Lip or its family** for customer ads (non-commercial licence).

Before switching any provider on: run the review page on 5 to 10 real talking-head clips with real takes (there was no talking-head footage of our own to test on tonight), wire the export to call `replace_span` for approved on-camera lines, and make the export a job (Phase 17's open problem: an export with the mouth step can take minutes).
