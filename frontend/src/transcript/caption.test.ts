import { describe, it, expect } from 'vitest'
import { captionAt } from './caption'
import type { Statement, Word } from '../types'

const LINES: Statement[] = [
  { text: 'Get 20% off today only.', start: 0, end: 2.3, speaker: 'A' },
  { text: 'Done, sir.', start: 3, end: 4, speaker: 'B' },
]
const WORDS: Word[] = [
  { text: 'Get', start: 0, end: 0.4 }, { text: '20%', start: 0.4, end: 0.9 }, { text: 'off', start: 0.9, end: 1.3 },
  { text: 'today', start: 1.3, end: 1.8 }, { text: 'only', start: 1.8, end: 2.3 },
]

describe('the caption at the playhead (UX-7b)', () => {
  it('is the line being said, as shot', () => {
    expect(captionAt(1, LINES)).toEqual([{ kind: 'same', text: 'Get 20% off today only.' }])
    expect(captionAt(2.5, LINES)).toBeNull()
  })

  it('marks the words a kept revision adds, and leaves the struck ones out', () => {
    const runs = captionAt(1, LINES, [{ edit_id: 'e1', start: 0.4, end: 0.9, text: '30%', mix: 'replace' }], [], WORDS)
    expect(runs).toEqual([{ kind: 'same', text: 'Get' }, { kind: 'ins', text: '30%' }, { kind: 'same', text: 'off today only.' }])
  })

  it("shows the plan's words while it is still being voiced", () => {
    const runs = captionAt(1, LINES, [], [{ selection: { start: 0, end: 2.3 }, text: 'Get 30% off today only.' }], WORDS)
    expect(runs).toEqual([{ kind: 'same', text: 'Get' }, { kind: 'ins', text: '30%' }, { kind: 'same', text: 'off today only.' }])
  })

  it('shows nothing for a removed line, and a moved line where it now starts', () => {
    const removed = { edit_id: 'e1', start: 3, end: 4, text: '', mix: 'remove' as const, partner: 'e2' }
    const moved = { edit_id: 'e2', start: 5, end: 6, text: 'Done, sir.', mix: 'layer' as const, partner: 'e1' }
    expect(captionAt(3.5, LINES, [removed, moved])).toBeNull()
    expect(captionAt(5.5, LINES, [removed, moved])).toEqual([{ kind: 'same', text: 'Done, sir.' }])
  })

  it('captions a voice-over placed on a silent clip as an added line', () => {
    const placed: Statement[] = [{ text: '', start: 0.4, end: 2.4, speaker: null, placed: true }]
    expect(captionAt(1, placed, [], [{ selection: { start: 0.4, end: 2.4 }, text: 'Welcome to Goa.', mix: 'layer' }])).toEqual([{ kind: 'ins', text: 'Welcome to Goa.' }])
    expect(captionAt(1, placed)).toBeNull()
  })

  it('shows the words as shot when the original plays', () => {
    const runs = captionAt(1, LINES, [{ edit_id: 'e1', start: 0.4, end: 0.9, text: '30%', mix: 'replace' }], [], WORDS, true)
    expect(runs).toEqual([{ kind: 'same', text: 'Get 20% off today only.' }])
  })
})
