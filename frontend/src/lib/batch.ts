import type { Batch } from '../types'
import { usd } from '../pages/fmt'

/** "5 videos · 11 lines · about $0.42 · about 2 min": each part only when it was worked out from something measured. */
export function gateLine(t: Batch['totals']): string {
  const bits = [`${t.videos} ${t.videos === 1 ? 'video' : 'videos'}`]
  if (t.lines !== null) bits.push(`${t.lines} ${t.lines === 1 ? 'line' : 'lines'}`)
  if (t.est_usd !== null) bits.push(t.est_usd < 0.01 ? 'under $0.01' : `about ${usd(t.est_usd)}`)
  if (t.est_s !== null) bits.push(t.est_s < 60 ? `about ${t.est_s} s` : `about ${Math.round(t.est_s / 60)} min`)
  return bits.join(' · ')
}
