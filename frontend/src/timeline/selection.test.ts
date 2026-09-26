import { describe, it, expect } from 'vitest'
import { timeFromX, snapToWords, sourceTime } from './selection'

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
