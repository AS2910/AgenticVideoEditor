import type { Mix, Revision, Selection, Statement, Word } from '../types'
import type { Run } from './changes'
import { trackedChanges } from './changes'

/** A line the plan is working on, as the caption needs it: its span and new words. */
export interface CaptionPending { selection: Selection; text?: string; mix?: Mix }

const overlaps = (a: { start: number; end: number }, b: { start: number; end: number }) => a.start < b.end && b.start < a.end
const at = (t: number, s: { start: number; end: number }) => t >= s.start && t < s.end

/** The line being said at `t`, as the picture should caption it (UX-7b): the
 *  current wording with added words marked `ins`, struck words left out. A
 *  line the plan is rewriting shows the plan's words; a kept revision shows
 *  its words; a removed line shows nothing; a moved line is captioned where
 *  it now starts. With `original`, the words as shot, whatever has changed. */
export function captionAt(
  t: number, statements: Statement[], revisions: Revision[] = [], pending: CaptionPending[] = [], words: Word[] = [], original = false,
): Run[] | null {
  const s = statements.find((x) => at(t, x))
  if (!s) {
    if (original) return null
    const moved = revisions.find((r) => r.mix === 'layer' && r.partner && at(t, r))
    return moved ? [{ kind: 'same', text: moved.text }] : null
  }
  if (original) return s.text ? [{ kind: 'same', text: s.text }] : null
  const live = revisions.filter((r) => overlaps(r, s) && !(r.mix === 'layer' && r.partner))
  const revision = live.length ? live[live.length - 1] : null
  if (revision?.mix === 'remove') return null
  const plan = pending.find((p) => overlaps(p.selection, s) && p.text)
  const shown: Revision | null = plan?.text
    ? { start: plan.selection.start, end: plan.selection.end, text: plan.text, mix: plan.mix ?? 'replace' }
    : revision
  if (!shown) return s.text ? [{ kind: 'same', text: s.text }] : null
  if (!s.text) return [{ kind: 'ins', text: shown.text }]
  return trackedChanges(s, shown, words).filter((r) => r.kind !== 'del')
}

/** A take playing in place, captioned from its own word times (the polish
 *  pass): every word of the take, each marked `said` once the take has
 *  reached it. `elapsed` is how far into the take the clock is. */
export function takeCaption(words: Word[], elapsed: number): { text: string; said: boolean }[] {
  return words.map((w) => ({ text: w.text, said: elapsed >= w.start }))
}
