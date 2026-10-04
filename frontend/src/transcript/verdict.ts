import type { Candidate } from '../types'

/** The verdict on a take, in words first; the score is behind it. */
export function verdict(candidate: Candidate, speaker?: string | null): { text: string; score: number | null; passed: boolean } {
  const c = candidate.continuity
  const who = speaker ? `like ${speaker}` : 'like the speaker'
  const measured = ['prosody', 'audio_integration', 'voice_match', 'lip_sync'] as const
  const scores = measured.filter((k) => c.measured.includes(k) && c[k] !== null).map((k) => c[k] as number)
  const score = scores.length ? Math.min(...scores) : null
  const notes = (candidate.fit_notes ?? []).filter((n) => !n.startsWith('nearest'))
  const tail = notes.length ? ` ${notes.join(', ').replace(/^./, (ch) => ch.toUpperCase())}.` : ''
  if (score === null) return { text: `Sounds right (not measured yet).${tail}`, score: null, passed: c.passed }
  const pitch = c.warnings.map((w) => /Pitch is (-?[\d.]+) semitones/.exec(w)).find(Boolean)
  if (!c.passed) {
    if (pitch) {
      const n = Math.abs(Math.round(parseFloat(pitch[1])))
      return { text: `Sounds ${n} semitone${n === 1 ? '' : 's'} ${parseFloat(pitch[1]) < 0 ? 'low' : 'high'} for ${speaker ?? 'the speaker'}.${tail}`, score, passed: false }
    }
    const why = c.warnings.find((w) => !w.startsWith('Stock voice') && !w.startsWith('Regenerated'))
    return { text: (why ? why.replace(/\.$/, '') : "Doesn't quite sit in the scene") + `.${tail}`, score, passed: false }
  }
  if (score >= 0.9) return { text: `Sounds ${who}, and sits in the room.${tail}`, score, passed: true }
  return { text: `Sounds ${who}; close enough to keep.${tail}`, score, passed: true }
}
