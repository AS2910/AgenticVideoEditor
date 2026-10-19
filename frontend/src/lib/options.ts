import type { PlanQuestion } from '../types'

/** One option on a question or gate card, as the pane shows it (pane-render). */
export interface OptionView {
  /** What is sent when it is picked: the option exactly as Voltage gave it. */
  value: string
  /** The button's words: short, about 40 characters. */
  label: string
  /** The full sentence beneath, quieter; null when the label says it all. */
  detail: string | null
  /** Voltage's guess: tagged "Voltage's pick". */
  pick: boolean
  /** The turn's cap caused the question and this is the way through ("Go ahead, allow $0.04 more"). */
  way: boolean
}

export const LABEL_MAX = 40

/** A label of about `max` characters: cut at the last space when there is one
 *  past the middle, else at `max` (Chinese has no spaces), with an ellipsis.
 *  Text up to `max + 8` stays whole; cutting off a word or two helps no one. */
export function shortLabel(text: string, max = LABEL_MAX): string {
  const chars = [...text]
  if (chars.length <= max + 8) return text
  const head = chars.slice(0, max).join('')
  const cut = head.lastIndexOf(' ')
  return `${(cut > max / 2 ? head.slice(0, cut) : head).replace(/[\s,.;:-]+$/, '')}…`
}

/** The options in the order the card shows them: under a gate, as given (the
 *  first is the yes); otherwise the way through the turn's cap first, then
 *  Voltage's pick, then the rest. A long option without a detail becomes a
 *  short label with the whole sentence beneath. */
export function optionsOf(q: PlanQuestion): OptionView[] {
  const views = q.options.map((o, k): OptionView => {
    const given = q.details?.[k]?.trim() || null
    const label = given ? o : shortLabel(o)
    return {
      value: o, label, detail: given ?? (label !== o ? o : null),
      pick: !q.gate && !!q.guess && o === q.guess && !(q.turn_cap && k === 0),
      way: !q.gate && !!q.turn_cap && k === 0,
    }
  })
  if (q.gate) return views
  return [...views.filter((v) => v.way), ...views.filter((v) => v.pick), ...views.filter((v) => !v.way && !v.pick)]
}
