import type { Word, Selection } from '../types'

export function timeFromX(
  clientX: number,
  rectLeft: number,
  rectWidth: number,
  duration: number,
): number {
  if (rectWidth <= 0) return 0
  const ratio = (clientX - rectLeft) / rectWidth
  const clamped = Math.min(1, Math.max(0, ratio))
  return clamped * duration
}

/** Widen a raw time range to the words it touches, so a drag never cuts a word
 *  in half. A range touching no word is returned as dragged. */
export function snapToWords(a: number, b: number, words: Word[]): Selection {
  const lo = Math.min(a, b)
  const hi = Math.max(a, b)
  const touched = words.filter((w) => w.end > lo && w.start < hi)
  if (touched.length === 0) return { start: lo, end: hi }
  return {
    start: Math.min(...touched.map((w) => w.start)),
    end: Math.max(...touched.map((w) => w.end)),
  }
}

/** Where a moment of the edited render falls on the source's timeline. Each
 *  inserted line holds the frame at its point, so during an insert the source
 *  clock stands still, and after it the render runs `duration` ahead. */
export function sourceTime(t: number, inserts: { at: number; duration: number }[]): number {
  let shift = 0
  for (const ins of [...inserts].sort((a, b) => a.at - b.at)) {
    const start = ins.at + shift
    if (t < start) break
    if (t < start + ins.duration) return ins.at
    shift += ins.duration
  }
  return t - shift
}
