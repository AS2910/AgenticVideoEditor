import type { Selection, Statement } from '../types'

/** One line's key: the span it covers, or `add-<end>` for a line added after it. */
export type LineKey = string
export const keyOf = (s: Selection): LineKey => `${s.start.toFixed(3)}-${s.end.toFixed(3)}`
export const addKeyOf = (s: Statement): LineKey => `add-${s.end.toFixed(3)}`
