---
title: Export many videos at once
section: Projects
order: 1105
---
On a project page, **Export videos** makes a file of each video you pick, once for each preset you pick, in one go.

**Presets** (beside the brief) say how each file is made: the frame (YouTube 16:9, Reels 9:16 or Feed 1:1), the codec (H.264, or HEVC where the server can write it), the loudness (-14 LUFS for the web, -16 general, -24 for broadcast), whether captions are burned into the picture, and the file name. A project starts with three: YouTube 16:9, Reels 9:16 and Feed 1:1, all at -14 LUFS. Add, change or remove them; one you remove stays removed.

A file name is a pattern with these parts: `{project}`, `{video}`, `{lang}`, `{preset}` and `{version}`. The default `{project}_{video}_{lang}_{preset}_v{version}` makes names like `Diwali-Sale_bhaji-cam_en_Reels-9-16_v3.mp4`. The version is the video's render version; the language is `en` until videos have their own.

A video shot in another shape is never cropped to fit a frame: it is scaled to fit and the rest is black bars (above and below, or at the sides). Each file says which. Captions are the words the video says now: the lines as shot that no change replaced, and every line you added, at the times they play.

Approved videos are picked for you. You can pick others too; they are marked **Not approved**. Without stages on your account, every video is picked and none is marked. Before you export, the project check's free checks run and anything they find shows as a warning. Warnings never stop an export.

**Export** makes one file per video and preset, two at a time, with a bar for the whole export. A file that fails is tried once more; if it fails again it shows **Failed** with the reason, and the others still finish. A video whose files are all made moves to **Exported**.

When the export finishes, download each file, or **Download all (.zip)**. **Share link** makes a link anyone can open without an account: it lists every file with a player and a Download button, and works for 30 days. **Turn off the link** stops it at once; whoever opens it then is told it was turned off.
