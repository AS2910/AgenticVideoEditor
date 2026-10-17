import type { PlanItem } from '../types'

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
