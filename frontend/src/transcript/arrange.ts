/** The arrangement of the spoken lines (2026-10-19), the same function as
 *  the server's `app/arrange.py`, so a drag can show where every line lands
 *  before it is dropped. The transcript's order is the playback order; each
 *  line starts where the one before it ends plus its own pause; a pinned
 *  line holds its time and a flowing one that would run into it waits until
 *  it has played. Both are tested against `backend/tests/fixtures/arrange-cases.json`. */

export const DEFAULT_MIN_GAP = 0.15
const EPS = 1e-6

export interface LineSpec { key: string; orig_start: number; orig_end: number; length: number; gap: number }
export interface Placed { key: string; start: number; end: number; pinned: boolean; pushed_after: number | null; moved: boolean }
export interface Arrangement { order: string[]; pins: Record<string, number>; min_gap: number | null; end: 'hold' | 'trim' | null }

export const EMPTY: Arrangement = { order: [], pins: {}, min_gap: null, end: null }

const r3 = (x: number) => Math.round(x * 1000) / 1000

/** The spoken lines as the arrangement sees them, in their original order. */
export function specs(statements: { start: number; end: number }[], lengths: Record<string, number> = {}): LineSpec[] {
  let prevEnd = 0
  return statements.map((st, i) => {
    const key = `L${i}`
    const length = lengths[key] ?? st.end - st.start
    const spec = { key, orig_start: r3(st.start), orig_end: r3(st.end), length: r3(Math.max(0, length)), gap: r3(Math.max(0, st.start - prevEnd)) }
    prevEnd = st.end
    return spec
  })
}

/** The lines in the arrangement's order; lines it does not name follow, in their own order. */
export function ordered(lines: LineSpec[], a: Arrangement): LineSpec[] {
  const byKey = new Map(lines.map((ln) => [ln.key, ln]))
  const named = a.order.filter((k) => byKey.has(k)).map((k) => byKey.get(k)!)
  const seen = new Set(named.map((ln) => ln.key))
  return [...named, ...lines.filter((ln) => !seen.has(ln.key))]
}

/** The pause before the i-th line played. The first keeps the clip's
 *  lead-in, whichever line it is; the line that was first, played later,
 *  takes the pause that followed it, so it does not carry the lead-in along. */
function gapOf(lines: LineSpec[], seq: LineSpec[], i: number, minGap: number | null): number {
  if (i === 0) return lines.length ? lines[0].gap : 0
  const ln = seq[i]
  const gap = lines.length && ln.key === lines[0].key ? (lines.length > 1 ? lines[1].gap : 0) : ln.gap
  return minGap !== null ? Math.min(gap, minGap) : gap
}

/** Where each line plays, sorted by when it starts (the transcript's order). */
export function place(lines: LineSpec[], a: Arrangement): Placed[] {
  const seq = ordered(lines, a)
  const pinned = new Map<string, [number, number]>()
  for (const ln of seq) if (ln.key in a.pins) pinned.set(ln.key, [r3(a.pins[ln.key]), r3(a.pins[ln.key] + ln.length)])
  const pins = [...pinned.values()].sort((x, y) => x[0] - y[0])
  const out: Placed[] = []
  let cursor = 0
  seq.forEach((ln, i) => {
    const pin = pinned.get(ln.key)
    if (pin) {
      out.push({ key: ln.key, start: pin[0], end: pin[1], pinned: true, pushed_after: null, moved: Math.abs(pin[0] - ln.orig_start) > 0.005 })
      cursor = pin[1]
      return
    }
    const gap = gapOf(lines, seq, i, a.min_gap)
    let start = r3(cursor + gap)
    let pushed: number | null = null
    let changed = true
    while (changed) {
      changed = false
      for (const [ps, pe] of pins) {
        if (start < pe - EPS && start + ln.length > ps + EPS) { start = r3(pe + gap); pushed = ps; changed = true }
      }
    }
    const end = r3(start + ln.length)
    out.push({ key: ln.key, start, end, pinned: false, pushed_after: pushed, moved: Math.abs(start - ln.orig_start) > 0.005 })
    cursor = end
  })
  return out.sort((x, y) => x.start - y.start || (x.key < y.key ? -1 : x.key > y.key ? 1 : 0))
}

/** How far the arrangement runs past the end of the clip (0 when it fits). */
export function overrun(placed: Placed[], duration: number): number {
  const last = placed.reduce((m, p) => Math.max(m, p.end), 0)
  return r3(Math.max(0, last - duration))
}

/** Two pinned lines that would play at once: the sentence that says so, else null. */
export function pinConflict(lines: LineSpec[], pins: Record<string, number>): string | null {
  const length = new Map(lines.map((ln) => [ln.key, ln.length]))
  const spans = Object.entries(pins).filter(([k]) => length.has(k)).map(([k, s]) => [s, s + length.get(k)!, k] as const).sort((x, y) => x[0] - y[0])
  for (let i = 1; i < spans.length; i++) {
    const [, a1, ka] = spans[i - 1]
    const [b0, , kb] = spans[i]
    if (b0 < a1 - EPS) return `Those two pinned lines would play at once (${ka} until ${a1.toFixed(1)} s, ${kb} from ${b0.toFixed(1)} s). Unpin one or move it.`
  }
  return null
}

/** The order the lines play in now, as keys: what a drag starts from. */
export const playingOrder = (placed: Placed[]) => placed.map((p) => p.key)

/** `key` moved to sit at `index` among the others (0 = first), as a new order. */
export function moveTo(order: string[], key: string, index: number): string[] {
  const rest = order.filter((k) => k !== key)
  const at = Math.max(0, Math.min(rest.length, index))
  return [...rest.slice(0, at), key, ...rest.slice(at)]
}
