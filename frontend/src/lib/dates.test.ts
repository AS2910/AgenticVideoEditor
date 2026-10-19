import { describe, it, expect } from 'vitest'
import { formatDate, formatRelative, monthLong, monthShort, toDate, NOT_RECORDED } from './dates'

describe('dates: one formatter for every date (bug 2)', () => {
  it('shows Not recorded for null, undefined, booleans, zero, empty and garbage — never 1970', () => {
    for (const v of [null, undefined, true, false, 0, -1, '', 'yes', 'true', NaN]) {
      expect(formatDate(v)).toBe(NOT_RECORDED)
      expect(formatRelative(v)).toBe(NOT_RECORDED)
      expect(formatDate(v)).not.toMatch(/1970/)
    }
  })

  it('reads ISO strings, and numbers sent as seconds by mistake as well as milliseconds', () => {
    const at = '2026-10-19T14:32:05.123Z'
    expect(formatDate(at, { timeZone: 'UTC' })).toBe('19 Oct 2026')
    expect(formatDate(1760884325, { timeZone: 'UTC' })).toBe('19 Oct 2025')          // seconds
    expect(formatDate(1760884325123, { timeZone: 'UTC' })).toBe('19 Oct 2025')       // milliseconds
    expect(toDate('2026-10-19T14:32:05.123456+00:00')?.toISOString()).toBe('2026-10-19T14:32:05.123Z')
  })

  it('uses the viewer’s time zone at a day boundary', () => {
    const lateUtc = '2026-10-19T20:00:00.000Z'
    expect(formatDate(lateUtc, { timeZone: 'Asia/Kolkata' })).toBe('20 Oct 2026')           // 01:30 the next day
    expect(formatDate(lateUtc, { timeZone: 'America/Los_Angeles' })).toBe('19 Oct 2026')    // 13:00 the same day
    const now = new Date('2026-10-20T03:00:00.000Z')
    expect(formatRelative(lateUtc, now, { timeZone: 'Asia/Kolkata' })).toBe('Today · 1:30')
    expect(formatRelative(lateUtc, now, { timeZone: 'America/Los_Angeles' })).toBe('Today · 13:00')
    expect(formatRelative('2026-10-18T10:00:00.000Z', now, { timeZone: 'UTC' })).toBe('19 Oct'.replace('19', '18'))
    expect(formatRelative('2026-10-19T10:00:00.000Z', now, { timeZone: 'UTC' })).toBe('Yesterday')
    expect(formatRelative('2025-03-04T08:00:00.000Z', now, { timeZone: 'UTC' })).toBe('4 Mar 2025')
  })

  it('names the month in the viewer’s zone', () => {
    const edge = new Date('2026-10-31T20:00:00.000Z')
    expect(monthShort(edge, { timeZone: 'Asia/Kolkata' })).toBe('Nov')
    expect(monthLong(edge, { timeZone: 'UTC' })).toBe('October')
  })
})
