import type { MixLine, Role } from '../types'

/** "−3 dB", "+2 dB": a fine-tune as the row says it. */
export const db = (x: number) => `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(Math.round(x))} dB`

/** The one line of facts under the role: how the line sits in the mix. */
export function roleFacts(role: Role, offset: number, mix: MixLine | null | undefined, bedUnderDb = 15): string {
  const tune = offset ? ` · fine-tuned ${db(offset)}` : ''
  if (role === 'bed') {
    if (mix?.alone) return `Bed · no speech here, so it plays nearly full${tune}`
    const under = mix?.under_db != null ? Math.round(mix.under_db) : Math.round(bedUnderDb - offset)
    return `Bed · sits ${under} dB under the voices${mix && !mix.ducks ? '' : ' · ducks while they speak'}${tune}`
  }
  if (role === 'effect') return `Effect · at the speech level${tune}`
  const heard = mix?.ratio_db != null && !mix.flag ? ` · heard ${Math.round(mix.ratio_db)} dB over the rest` : ''
  const where = mix?.raised_db ? `lifted ${Math.round(mix.raised_db)} dB over the sound under it` : "at the clip's speech level"
  return `Voice · ${where}${tune}${heard}`
}
