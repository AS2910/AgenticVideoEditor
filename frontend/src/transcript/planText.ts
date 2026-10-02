import type { Plan, PlanItem } from '../types'

/** "Sounds right": the weakest measured score, or the weakest there is. */
export const soundsRight = (item: PlanItem): number | null => {
  const c = item.candidate?.continuity
  if (!c) return null
  const keys = ['voice_match', 'prosody', 'audio_integration', 'lip_sync'] as const
  const measured = keys.filter((k) => c.measured.includes(k) && c[k] !== null).map((k) => c[k] as number)
  const any = keys.filter((k) => c[k] !== null).map((k) => c[k] as number)
  const pool = measured.length ? measured : any
  return pool.length ? Math.min(...pool) : null
}

/** A rough reading of the estimate, in words. */
export const estimateText = (e: Plan['estimate']) => {
  const chars = e.voice_characters > 0 ? `About ${e.voice_characters} voice characters` : 'No paid voice'
  const usd = e.usd >= 0.01 ? ` and about $${e.usd.toFixed(2)}` : e.voice_characters > 0 ? ' and under $0.01' : ''
  const secs = e.seconds >= 60 ? `about ${Math.round(e.seconds / 60)} minute${e.seconds >= 90 ? 's' : ''}` : `about ${e.seconds} seconds`
  return `${chars}${usd}. Ready in ${secs}.`
}
