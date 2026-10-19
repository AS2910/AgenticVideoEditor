---
title: Several lines at once, and how they are mixed
section: Editing lines
order: 304
---
Added lines can play at the same moment. Each one has a role, Voice, Bed or Effect, and its level follows from that role, measured against how loud the clip's own speech is.

Lines at the same moment are separate rows and play together; the transcript says "with N other lines at this moment". On an added line or a proposal, choose what it is:

- **Voice** is words meant to be understood. It plays at the clip's own speech level. On a clip with no speech it uses the project's default level.
- **Bed** is music, a crowd, cheers or ambience. It sits 15 dB under the loudest voice playing with it, and dips a little further while words are spoken. With no speech in its span it plays nearly full, and the row says so.
- **Effect** is a sound effect, at the speech level.

The line under the role says how it sits, for example "Bed · sits 15 dB under the voices · ducks while they speak". **Fine-tune** nudges any line from 24 dB down to 6 dB up, and **Hear it in place** plays it there. Changing the role or the fine-tune never voices the line again.

Lines of the original speech are always a Voice. An added voice over the original's music makes the music dip under it. If the only speech in a stretch would become a Bed, Voltage asks first: as a Bed it would just be quieter, so you can keep it as a Voice or play it quietly under.

After each render Voltage checks that every voice can be heard over everything else. When something covers a line, the row says what, for example "The cheers cover this line at 0:02; lower it or make it a Bed." Every render, and the file you export, is brought to the same loudness (-14 LUFS for social, -16 for general, set in the video's settings) with no clipping, so what you hear is what you get.
