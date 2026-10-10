import { describe, it, expect } from 'vitest'
import { timeFromX, snapToWords, sourceTime, renderTime, renderTimeFrom, sourceTimeFrom, piecesFromInserts } from './selection'

describe('timeFromX', () => {
  it('maps the track midpoint to half the duration', () => {
    // track from x=100 to x=300 (width 200), duration 2.3
    expect(timeFromX(200, 100, 200, 2.3)).toBeCloseTo(1.15)
  })
  it('clamps below the track to 0', () => {
    expect(timeFromX(50, 100, 200, 2.3)).toBe(0)
  })
  it('clamps past the track to the duration', () => {
    expect(timeFromX(500, 100, 200, 2.3)).toBe(2.3)
  })
  it('returns 0 for a zero-width track', () => {
    expect(timeFromX(200, 100, 0, 2.3)).toBe(0)
  })
})

describe('snapToWords', () => {
  const WORDS = [
    { text: 'Get', start: 0.0, end: 0.4 },
    { text: '20%', start: 0.4, end: 0.9 },
    { text: 'off', start: 0.9, end: 1.3 },
  ]
  it('widens a drag to the words it touches', () => {
    expect(snapToWords(0.5, 1.0, WORDS)).toEqual({ start: 0.4, end: 1.3 })
  })
  it('accepts a right-to-left drag', () => {
    expect(snapToWords(1.0, 0.5, WORDS)).toEqual({ start: 0.4, end: 1.3 })
  })
  it('keeps the raw range when it touches no word', () => {
    expect(snapToWords(1.5, 2.0, WORDS)).toEqual({ start: 1.5, end: 2.0 })
  })
})

describe('sourceTime', () => {
  const INSERTS = [{ at: 7.0, duration: 1.1 }]
  it('is the render time before any insert', () => {
    expect(sourceTime(3.2, INSERTS)).toBe(3.2)
  })
  it('stands still at the insert point while the line plays', () => {
    expect(sourceTime(7.5, INSERTS)).toBe(7.0)
  })
  it('runs behind by the insert after it', () => {
    expect(sourceTime(8.6, INSERTS)).toBeCloseTo(7.5)
  })
  it('adds up several inserts, whatever their order', () => {
    expect(sourceTime(9.0, [{ at: 5, duration: 1 }, { at: 2, duration: 1 }])).toBeCloseTo(7.0)
  })
})

describe('renderTime', () => {
  it('pushes source time later by the inserts at or before it', () => {
    expect(renderTime(3, [{ at: 7, duration: 1.1 }])).toBe(3)
    expect(renderTime(7.5, [{ at: 7, duration: 1.1 }])).toBeCloseTo(8.6)
  })
  it('round-trips with sourceTime outside an insert', () => {
    const ins = [{ at: 2, duration: 1 }, { at: 5, duration: 0.5 }]
    expect(sourceTime(renderTime(6, ins), ins)).toBeCloseTo(6)
  })
})

describe('time through pieces (Phase 16)', () => {
  const PIECES = [
    { start: 0, end: 2, out_start: 0, out_end: 2, kind: 'copy' as const, factor: 1 },
    { start: 2, end: 3, out_start: 2, out_end: 3.1, kind: 'flex' as const, factor: 1.1 },      // a line's picture 10% slower
    { start: 3, end: 5, out_start: 3.1, out_end: 5.1, kind: 'copy' as const, factor: 1 },
    { start: 5, end: 5.5, out_start: 5.1, out_end: 5.9, kind: 'living' as const, factor: 1.6 }, // a pause stretched for an added line
    { start: 5.5, end: 5.5, out_start: 5.9, out_end: 6.1, kind: 'hold' as const, factor: null }, // what the pause could not absorb
    { start: 5.5, end: 8, out_start: 6.1, out_end: 8.6, kind: 'copy' as const, factor: 1 },
  ]
  it('passes time through an untouched copy', () => {
    expect(renderTimeFrom(1, PIECES)).toBe(1)
    expect(sourceTimeFrom(1, PIECES)).toBe(1)
  })
  it('stretches linearly inside a flexed line and a living pause', () => {
    expect(renderTimeFrom(2.5, PIECES)).toBeCloseTo(2.55)
    expect(sourceTimeFrom(2.55, PIECES)).toBeCloseTo(2.5)
    expect(renderTimeFrom(5.25, PIECES)).toBeCloseTo(5.5)
    expect(sourceTimeFrom(5.5, PIECES)).toBeCloseTo(5.25)
  })
  it('stands still through a held frame, and the moment held at resumes after it', () => {
    expect(sourceTimeFrom(6.0, PIECES)).toBe(5.5)
    expect(renderTimeFrom(5.5, PIECES)).toBeCloseTo(6.1)
  })
  it('runs ahead by everything added, after it all', () => {
    expect(renderTimeFrom(7, PIECES)).toBeCloseTo(7.6)
    expect(sourceTimeFrom(7.6, PIECES)).toBeCloseTo(7)
    expect(renderTimeFrom(9, PIECES)).toBeCloseTo(9.6)   // past the last piece
    expect(sourceTimeFrom(9.6, PIECES)).toBeCloseTo(9)
  })
  it('round-trips everywhere but inside a hold', () => {
    for (const t of [0.3, 2.2, 2.9, 4, 5.1, 5.4, 6, 7.9]) expect(sourceTimeFrom(renderTimeFrom(t, PIECES), PIECES)).toBeCloseTo(t)
  })
  it('is the identity with no pieces', () => {
    expect(renderTimeFrom(4.2, [])).toBe(4.2)
    expect(sourceTimeFrom(4.2, [])).toBe(4.2)
  })
  it('built from inserts, agrees with the older insert clocks', () => {
    const ins = [{ at: 2, duration: 1 }, { at: 5, duration: 0.5 }]
    const pieces = piecesFromInserts(ins, 8)
    expect(pieces.map((p) => p.kind)).toEqual(['copy', 'hold', 'copy', 'hold', 'copy'])
    expect(pieces[pieces.length - 1].out_end).toBeCloseTo(9.5)
    for (const t of [0, 1.5, 2, 3, 4.9, 5, 6, 8]) expect(renderTimeFrom(t, pieces)).toBeCloseTo(renderTime(t, ins))
    for (const t of [0, 1.5, 2.5, 3.5, 6.2, 7, 9.5]) expect(sourceTimeFrom(t, pieces)).toBeCloseTo(sourceTime(t, ins))
    expect(piecesFromInserts([], 3)).toEqual([{ start: 0, end: 3, out_start: 0, out_end: 3, kind: 'copy', factor: 1 }])
  })
})
