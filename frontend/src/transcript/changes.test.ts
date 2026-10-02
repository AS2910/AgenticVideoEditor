import { describe, it, expect } from 'vitest'
import { diffWords, lineAfter, trackedChanges } from './changes'

const WORDS = [
  { text: 'Get', start: 0.0, end: 0.4 }, { text: '20%', start: 0.4, end: 0.9 },
  { text: 'off', start: 0.9, end: 1.3 }, { text: 'today', start: 1.3, end: 1.8 }, { text: 'only', start: 1.8, end: 2.3 },
]
const LINE = { text: 'Get 20% off today only.', start: 0, end: 2.3 }

describe('diffWords', () => {
  it('strikes the old word and adds the new one', () => {
    expect(diffWords('Start a live Bajicam session.', 'Start a live Bhaji Cam session.')).toEqual([
      { kind: 'same', text: 'Start a live' }, { kind: 'del', text: 'Bajicam' },
      { kind: 'ins', text: 'Bhaji Cam' }, { kind: 'same', text: 'session.' },
    ])
  })

  it('treats punctuation and case as the same word, keeping the original spelling', () => {
    expect(diffWords('Sure, sir.', 'sure sir, everything is off')).toEqual([
      { kind: 'same', text: 'Sure, sir.' }, { kind: 'ins', text: 'everything is off' },
    ])
  })

  it('marks an unchanged line as all the same', () => {
    expect(diffWords('Feed is live.', 'Feed is live.')).toEqual([{ kind: 'same', text: 'Feed is live.' }])
  })
})

describe('lineAfter', () => {
  it('keeps the words either side of a revision over part of the line', () => {
    expect(lineAfter(LINE, { start: 0.4, end: 1.3, text: '30% off', mix: 'replace' }, WORDS))
      .toBe('Get 30% off today only')
  })

  it('replaces the whole line when the revision covers it', () => {
    expect(lineAfter(LINE, { start: 0, end: 2.3, text: 'Get half off today.', mix: 'replace' }, WORDS))
      .toBe('Get half off today.')
  })

  it('appends an added or layered line', () => {
    expect(lineAfter(LINE, { start: 0, end: 2.3, text: 'Hurry!', mix: 'concatenate' }, WORDS))
      .toBe('Get 20% off today only. Hurry!')
  })
})

describe('trackedChanges', () => {
  it('shows a partial revision inline with the rest of the line intact', () => {
    expect(trackedChanges(LINE, { start: 0.4, end: 1.3, text: '30% off', mix: 'replace' }, WORDS)).toEqual([
      { kind: 'same', text: 'Get' }, { kind: 'del', text: '20%' }, { kind: 'ins', text: '30%' },
      { kind: 'same', text: 'off today only.' },
    ])
  })
})
