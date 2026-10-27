import type { Batch, BatchRowState } from '../types'
import { usd } from '../pages/fmt'

/** "5 videos · 11 lines · about $0.42 · about 2 min": each part only when it was worked out from something measured. */
export function gateLine(t: Batch['totals']): string {
  const bits = [`${t.videos} ${t.videos === 1 ? 'video' : 'videos'}`]
  if (t.lines !== null) bits.push(`${t.lines} ${t.lines === 1 ? 'line' : 'lines'}`)
  if (t.est_usd !== null) bits.push(t.est_usd < 0.01 ? 'under $0.01' : `about ${usd(t.est_usd)}`)
  if (t.est_s !== null) bits.push(t.est_s < 60 ? `about ${t.est_s} s` : `about ${Math.round(t.est_s / 60)} min`)
  return bits.join(' · ')
}

// Run 5 item 9: examples a first-timer can press to fill the box (nothing runs until Plan it).
export const EXAMPLES = ['Make every offer line say 25% off', 'Change the price to ₹499 in every video', 'Say the sale ends on Sunday']

/** The board's one-sentence verdict, in plain words: what finished and what is left to do. */
export function boardSummary(b: Batch): string {
  const n = (state: BatchRowState) => b.rows.filter((r) => r.state === state).length
  const vids = (k: number) => `${k} ${k === 1 ? 'video' : 'videos'}`
  if (b.phase === 'running') {
    const left = n('queued') + n('working')
    return `Working on ${vids(b.rows.length)}, 3 at a time. ${left === 0 ? 'Finishing up.' : `${vids(left)} still to go.`}`
  }
  const bits: string[] = []
  if (n('ready')) bits.push(`${vids(n('ready'))} ${n('ready') === 1 ? 'has' : 'have'} changes to review`)
  if (n('added')) bits.push(`${vids(n('added'))} ${n('added') === 1 ? 'has' : 'have'} the changes added`)
  if (n('waiting')) bits.push(`${vids(n('waiting'))} ${n('waiting') === 1 ? 'needs' : 'need'} your answer`)
  if (n('nothing')) bits.push(`${vids(n('nothing'))} had nothing to change`)
  if (n('failed')) bits.push(`${vids(n('failed'))} failed`)
  if (n('cancelled')) bits.push(`${vids(n('cancelled'))} ${n('cancelled') === 1 ? 'was' : 'were'} cancelled`)
  const head = b.phase === 'cancelled' ? 'Cancelled.' : 'Done.'
  return bits.length === 0 ? head : `${head} ${bits.join(', ').replace(/, ([^,]*)$/, ' and $1')}.`
}
