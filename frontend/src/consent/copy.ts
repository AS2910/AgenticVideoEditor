/** Voice consent V1 step 6: the owner's copy, word for word (BRIEF.md "UI and copy").
 *  The server holds the same words (`app/safety/voice_guard.py` STATEMENT,
 *  EXPORT_STATEMENT, BLOCKED, HELD, SUSPENDED, OUT_OF_SCOPE); the tests check both. */
import type { AttestationFacts, ExportVoice } from './types'

export const ATTEST = {
  body: "Voltage will make new lines in this person's voice. Tell us whose voice it is.",
  choices: [
    { choice: 'my_voice', label: 'This is my voice' },
    { choice: 'have_permission', label: 'I have permission from this person to change what they say' },
  ],
  confirm: "I confirm I have the rights and consent to use this voice. I won't use it to deceive, impersonate or harm anyone, and I'm responsible for how it's used.",
  warning: "Using someone's voice without their consent can be illegal.",
  cancel: 'Cancel',
  accept: 'Use this voice',
} as const
export type AttestChoice = (typeof ATTEST.choices)[number]['choice']

export const EXPORT = {
  label: 'Add an "AI voice" label to the video (recommended)',
  confirm: 'I have permission from everyone whose voice was changed',
  back: 'Back',
  accept: 'Export',
} as const

export const LINE = {
  held: "This line is held for a quick check. You'll get a notification when it's cleared.",
  suspended: 'Voicing with cloned voices is paused on your account while we review recent lines. Contact support if this is a mistake.',
  outOfScope: 'This voice can only be used in the video it came from.',
  edit: 'Edit the line',
} as const

export const VOICES = {
  videoOnly: 'This video only',
  save: 'Save to My voices',
  prove: "Prove it's your voice",
} as const

/** The speaker as the copy names them: their name, else "Speaker 2" from the label, else "this speaker". */
export function speakerName(facts: Pick<AttestationFacts, 'speaker_name' | 'speaker_label'>): string {
  if (facts.speaker_name?.trim()) return facts.speaker_name.trim()
  const label = facts.speaker_label?.trim()
  if (label && label !== '_') return /^\d+$/.test(label) ? `Speaker ${label}` : label
  return 'this speaker'
}

/** "Use Speaker 2's voice?" */
export const attestTitle = (facts: Pick<AttestationFacts, 'speaker_name' | 'speaker_label'>) => `Use ${speakerName(facts)}'s voice?`

/** "This video has AI changes to Speaker 2's voice"; one confirmation names every voice in the export. */
export function exportTitle(voices: ExportVoice[]): string {
  const names = [...new Set(voices.map((v) => speakerName(v)))]
  if (names.length <= 1) return `This video has AI changes to ${names[0] ?? 'this speaker'}'s voice`
  const owned = names.map((n) => `${n}'s`)
  return `This video has AI changes to ${owned.slice(0, -1).join(', ')} and ${owned[owned.length - 1]} voices`
}

export type RefusalKind = 'blocked' | 'held' | 'suspended'

/** Which of the guard's line refusals a sentence is (the row's reason and the step carry the guard's words). */
export function refusalKind(text: string | null | undefined, code?: string | null): RefusalKind | null {
  if (code === 'line_blocked') return 'blocked'
  if (code === 'line_in_review') return 'held'
  const t = (text ?? '').trim()
  if (code === 'voice_unavailable' && t.startsWith('Voicing with cloned voices is paused')) return 'suspended'
  if (!t) return null
  if (t.startsWith("I can't voice this line.")) return 'blocked'
  if (t === LINE.held) return 'held'
  if (t === LINE.suspended) return 'suspended'
  return null
}

/** Ask the transcript to open a line's editor on its current words (LineDoc listens). */
export function editLine(start: number, end?: number): void {
  window.dispatchEvent(new CustomEvent('voltage:edit-line', { detail: { start, end } }))
}

/** What became of a Save to My voices: saved, or kept for its video with the reason. */
export type ProveOutcome = { saved: true } | { saved: false; status: 'review' | 'failed' | 'error'; reason: string }

/** The words a voice kept for its video carries after a check that did not pass. */
export function keptWhy(outcome: Extract<ProveOutcome, { saved: false }>): string {
  const why = outcome.reason.trim()
  if (outcome.status === 'review') return `Kept for this video only while a person checks your recording.${why ? ` ${why}` : ''}`
  return `Kept for this video only. ${why || 'The check did not pass.'}`
}
