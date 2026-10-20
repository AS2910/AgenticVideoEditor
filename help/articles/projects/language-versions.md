---
title: Language versions
section: Projects
order: 1106
---
A video in a project can have **language versions**: the same clip, every line spoken in another language. Hindi, Hinglish, Tamil and Marathi to start, and English for a video that is not in English.

On the project page, select **+ Language versions** under a video (or, in the editor, open the project menu and choose **Make language versions…**). Pick the languages, then how they are voiced:

- **Same voice in the new language**: the speaker's own or cloned voice, speaking the new language with the multilingual voice model.
- **A designed voice per language**: Voltage designs one voice for each language that suits the speaker.

Before anything is made, the dialog shows the numbers: how many versions, how many lines, about what it costs (from your earlier turns and the voice prices; left out when nothing is measured yet) and the most it can spend, each version's own turn cap added up. **Make versions** then makes one video per language, linked to this one, and runs one batch turn over them: each version gets its own turn that translates every line and voices it in place, fitting the time of the line it replaces. A line that runs long is fitted first, and written shorter in that language when fitting is not enough. The batch board on the project page shows each version; nothing is added until you choose **Add all that passed**.

**Brand names never translate.** In **Words**, tick **Brand name, never translate** on a term. Each version's turn is told "Never translate" with those names, and every take is checked: when the master's line says a brand name and the version's line does not carry it exactly as written, the take is marked **Brand name translated** and is never Voltage's pick or added by Add all that passed. A word can also say how it goes in one language: pick the language and type the translation, and that version's turn uses it.

On the project page, a video and its versions are one stacked card with a chip per language. Home shows the same chips.

**Keeping in step.** When the master gets a new change (a line added or taken back), each version shows **Out of sync with master**, on its chip, on Home and in its editor header. **Sync this change** runs one turn on that version for only the lines the master changed since it last synced, in its language, and leaves every other line as it is. Once that turn finishes, the version is in step again.
