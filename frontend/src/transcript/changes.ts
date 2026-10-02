import type { Revision, Statement, Word } from '../types'

/** One run of a line with tracked changes: words kept, struck, or added. */
export interface Run { kind: 'same' | 'del' | 'ins'; text: string }

const tokens = (text: string) => text.split(/\s+/).filter(Boolean)
// Words compare without punctuation or case, so "only." and "only" are the
// same word — the transcript's statements carry punctuation, its words don't.
const norm = (t: string) => t.toLowerCase().replace(/[^\p{L}\p{N}%]/gu, '')

/** A word-level diff of two lines (longest common subsequence). Kept words
 *  are shown as `before` spelt them, so punctuation survives. */
export function diffWords(before: string, after: string): Run[] {
  const a = tokens(before), b = tokens(after)
  const n = a.length, m = b.length
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = norm(a[i]) === norm(b[j]) ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const runs: Run[] = []
  const push = (kind: Run['kind'], text: string) => {
    const last = runs[runs.length - 1]
    if (last && last.kind === kind) last.text += ` ${text}`
    else runs.push({ kind, text })
  }
  let i = 0, j = 0
  while (i < n && j < m) {
    if (norm(a[i]) === norm(b[j])) { push('same', a[i]); i++; j++ }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { push('del', a[i]); i++ }
    else { push('ins', b[j]); j++ }
  }
  while (i < n) push('del', a[i++])
  while (j < m) push('ins', b[j++])
  return runs
}

const overlaps = (a: { start: number; end: number }, b: { start: number; end: number }) =>
  a.start < b.end && b.start < a.end

/** What a statement reads as once a revision is applied to it. A revision
 *  over part of the line (its timed words are known) keeps the words either
 *  side; one over the whole line, or without word timings, replaces it. An
 *  added line (concatenate) or a layered one follows the original. */
export function lineAfter(statement: Statement, revision: Revision, words: Word[] = []): string {
  if (revision.mix !== 'replace') return `${statement.text} ${revision.text}`
  const inside = words.filter((w) => overlaps(w, statement))
  const before = inside.filter((w) => w.end <= revision.start + 1e-6).map((w) => w.text)
  const after = inside.filter((w) => w.start >= revision.end - 1e-6).map((w) => w.text)
  if (inside.length === 0 || (before.length === 0 && after.length === 0)) return revision.text
  return [...before, revision.text, ...after].join(' ')
}

/** The line with its revision shown as tracked changes. */
export function trackedChanges(statement: Statement, revision: Revision, words: Word[] = []): Run[] {
  return diffWords(statement.text, lineAfter(statement, revision, words))
}
