import { describe, it, expect } from 'vitest'
import { timeFromX } from './selection'

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
