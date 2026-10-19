import type { SpendScope, SpendSummary } from '../types'

/** Spend scopes (2026-10-19): every money figure names what it measures. The
 *  element that holds a figure and its label carries `data-money-scope`
 *  (turn, video, project, month, step, all, none), so a test can find any
 *  "$" that has lost its label. */

export const usd = (n: number) => `$${n.toFixed(2)}`
/** A ceiling in a sentence: "$10" when whole, "$2.50" otherwise. */
export const ceilingWord = (n: number) => (Number.isInteger(n) ? `$${n}` : usd(n))

/** "$0.61 of $10", or "$0.61" with no ceiling. */
export const ofCeiling = (s: SpendScope) => (s.ceiling_usd != null ? `${usd(s.spent_usd)} of ${ceilingWord(s.ceiling_usd)}` : usd(s.spent_usd))

/** The trace's footer, the same words as Voltage's closing line: "This turn
 *  $0.03 · video $0.61 · project $0.61"; a standalone video has no project part. */
export function spendLine(s: SpendSummary): string {
  const parts = [`This turn ${usd(s.turn?.spent_usd ?? 0)}`]
  if (s.video) parts.push(`video ${usd(s.video.spent_usd)}`)
  if (s.project) parts.push(`project ${usd(s.project.spent_usd)}`)
  return parts.join(' · ')
}

/** The figures in the DOM that have lost their label: a "$" amount with no
 *  `data-money-scope` ancestor, or one whose scope element has no words
 *  besides the amounts. The pages' tests call it on what they render. */
export function unlabelledMoney(root: Node): string[] {
  const out: string[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.textContent ?? ''
    if (!/\$\d/.test(text)) continue
    const scoped = n.parentElement?.closest('[data-money-scope]')
    const words = scoped ? (scoped.textContent ?? '').replace(/~?\$\d[\d,]*(\.\d+)?/g, '').replace(/[^A-Za-z]/g, '') : ''
    if (!scoped || !scoped.getAttribute('data-money-scope') || words.length === 0) out.push(text.trim())
  }
  return out
}
