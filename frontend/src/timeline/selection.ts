import type { Piece, Word, Selection } from '../types'

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

/** Where a moment of the source falls in the edited render — the inverse of
 *  `sourceTime`. An insert at or before `t` pushes it later. */
export function renderTime(t: number, inserts: { at: number; duration: number }[]): number {
  return t + inserts.filter((i) => i.at <= t).reduce((sum, i) => sum + i.duration, 0)
}

/** Where a moment of the edited render falls on the source's timeline. Each
 *  inserted line held the frame at its point (before Phase 16), so during an insert the source
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

/** Phase 16: the render as pieces. Where a moment of the source falls in the
 *  edited render, through the pieces: linear inside each, the moment a frame
 *  was held at resumes after its hold, and time outside every piece passes through. */
export function renderTimeFrom(t: number, pieces: Piece[]): number {
  if (pieces.length === 0) return t
  const sorted = [...pieces].sort((a, b) => a.start - b.start || a.out_start - b.out_start)
  for (const p of sorted) {
    if (p.kind === 'hold' || p.end <= p.start) continue
    if (t >= p.start && t < p.end) return p.out_start + (t - p.start) / (p.end - p.start) * (p.out_end - p.out_start)
  }
  // Only a held frame has this moment: the source resumes after the hold.
  const hold = sorted.filter((p) => (p.kind === 'hold' || p.end <= p.start) && p.start === t).pop()
  if (hold) return hold.out_end
  const first = sorted[0]
  if (t < first.start) return t
  const last = sorted[sorted.length - 1]
  return last.out_end + (t - last.end)
}

/** Phase 16: where a moment of the render falls on the source, through the
 *  pieces — the inverse of `renderTimeFrom`; inside a hold the source stands still. */
export function sourceTimeFrom(t: number, pieces: Piece[]): number {
  if (pieces.length === 0) return t
  const sorted = [...pieces].sort((a, b) => a.out_start - b.out_start)
  for (const p of sorted) {
    if (t >= p.out_start && t < p.out_end) {
      if (p.kind === 'hold' || p.end <= p.start || p.out_end <= p.out_start) return p.start
      return p.start + (t - p.out_start) / (p.out_end - p.out_start) * (p.end - p.start)
    }
  }
  const first = sorted[0]
  if (t < first.out_start) return t
  const last = sorted[sorted.length - 1]
  return last.end + (t - last.out_end)
}

/** Pieces equivalent to an older manifest's inserts: copies of the source with
 *  a held frame at each insert point, so one code path serves both. */
export function piecesFromInserts(inserts: { at: number; duration: number }[], duration: number): Piece[] {
  const pieces: Piece[] = []
  let cursor = 0
  let shift = 0
  for (const ins of [...inserts].sort((a, b) => a.at - b.at)) {
    const at = Math.min(Math.max(ins.at, 0), duration)
    if (at > cursor) pieces.push({ start: cursor, end: at, out_start: cursor + shift, out_end: at + shift, kind: 'copy', factor: 1 })
    pieces.push({ start: at, end: at, out_start: at + shift, out_end: at + shift + ins.duration, kind: 'hold', factor: null })
    shift += ins.duration
    cursor = at
  }
  if (cursor < duration || pieces.length === 0) pieces.push({ start: cursor, end: duration, out_start: cursor + shift, out_end: duration + shift, kind: 'copy', factor: 1 })
  return pieces
}
