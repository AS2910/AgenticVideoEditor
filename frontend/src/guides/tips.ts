/** The first-time tips: each shows once, the first time its moment comes,
 *  under the control it is about. `slug` is the Help article behind it. */
export interface TipDef { id: string; title: string; text: string; link: string; slug: string }

export const TIPS: TipDef[] = [
  { id: 'first-upload', title: 'First video', text: 'Voltage reads the clip first: who speaks, what they say, and what the picture shows. Nothing is changed until you ask.', link: 'Your first edit', slug: 'your-first-edit' },
  { id: 'first-silent', title: 'No speech', text: 'No one speaks in this clip, so Voltage looked at the picture instead. Ask for a voice-over and it writes and voices one.', link: 'What videos work best', slug: 'what-videos-work-best' },
  { id: 'first-question', title: 'First question', text: 'Voltage asks only when it cannot decide, with its own guess first. Saying go takes the guess.', link: 'When Voltage asks you', slug: 'when-voltage-asks-you' },
  { id: 'first-just-do-it', title: 'Just do it', text: 'Voltage now voices and fixes on its own, inside your turn cap. Exporting, cloning and designing a voice still ask first.', link: 'Check with me or Just do it', slug: 'check-with-me-or-just-do-it' },
  { id: 'first-voice-design', title: 'Designed voice', text: 'Voltage made three previews from your words. It cannot hear them, so you choose the one that fits.', link: 'Designing a voice from words', slug: 'designing-a-voice-from-words' },
  { id: 'first-project-voice', title: 'Keep this voice', text: 'A voice made here lives with this project. Keep it in your voices and it works in every project, by name.', link: 'Saving and reusing your voices', slug: 'saving-and-reusing-your-voices' },
  { id: 'first-background', title: 'Background', text: 'This line plays under the words at 12 dB below them. Drag its level, or ask Voltage to bring it up or down.', link: 'Several lines at once and background levels', slug: 'several-lines-at-once-and-background-levels' },
  { id: 'first-undo-after-export', title: 'Still undoable', text: 'The file is rendered, and every change can still be taken out. Export again to update it.', link: 'Undo anything', slug: 'undo-anything' },
  { id: 'first-ceiling', title: 'Ceiling reached', text: 'This project has spent up to its ceiling, so paid steps wait. Raise it in the header, or in Settings for new projects.', link: 'Turn, project and monthly ceilings', slug: 'turn-project-and-monthly-ceilings' },
  { id: 'first-failed-take', title: 'A take failed', text: 'Nothing was charged. Try it again, or ask Voltage what happened.', link: 'A take failed', slug: 'a-take-failed' },
]

export const tipById = (id: string): TipDef | undefined => TIPS.find((t) => t.id === id)
