import type { PlanItem } from '../types'
import { splitTags } from './tags'

/** A line that ran long for its gap (p61), with the server's own figures. */
export const ranLong = (item: PlanItem) => item.status === 'failed' && item.fit_failure?.reason === 'too_long'

/** The one quiet reason on a failed row: "3.0 s for a 2.3 s gap". */
export const fitReason = (item: PlanItem) =>
  item.fit_failure ? `${item.fit_failure.needs.toFixed(1)} s for a ${item.fit_failure.has.toFixed(1)} s gap` : null

/** What shortening the lines costs at most: each one's take that ran long (a shorter line costs no more). */
export const shortenUsd = (items: PlanItem[]) => items.reduce((sum, i) => sum + (i.fit_failure?.cost_usd ?? 0), 0)

/** The sentence said to Voltage for one turn that shortens every line named (tags left out: they are not words). */
export const shortenSentence = (items: PlanItem[]) => {
  const each = items.map((i) => `${i.item_id} (“${splitTags(i.new_text).words}”, about ${i.fit_failure?.budget ?? '?'} syllables for ${i.fit_failure?.has.toFixed(1) ?? '?'} s)`)
  return items.length === 1
    ? `Shorten ${each[0]} so it fits its gap, and voice it again.`
    : `Shorten these ${items.length} lines so each fits its gap, and voice each again once: ${each.join('; ')}.`
}
