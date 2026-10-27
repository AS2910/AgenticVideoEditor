import { describe, it, expect, beforeEach } from 'vitest'
import { loadSession, newSession, noteShown, pickTip, rollSession, saveSession, SESSION_IDLE_MS, SESSION_KEY, TIPS_PER_SESSION, withinAllowance } from './tipRules'

const T0 = 1_000_000_000_000
const req = (id: string, seq: number, placeable = true) => ({ id, seq, placeable })

describe('the tip queue rules', () => {
  beforeEach(() => window.localStorage.clear())

  it('shows one tip at a time: the earliest ask', () => {
    const s = newSession(T0)
    expect(pickTip({ requests: [req('b', 2), req('a', 1), req('c', 3)], dismissed: [], session: s })).toBe('a')
    expect(pickTip({ requests: [], dismissed: [], session: s })).toBeNull()
  })

  it('never shows a dismissed tip', () => {
    const s = newSession(T0)
    expect(pickTip({ requests: [req('a', 1), req('b', 2)], dismissed: ['a'], session: s })).toBe('b')
    expect(pickTip({ requests: [req('a', 1)], dismissed: ['a'], session: noteShown(s, 'a') })).toBeNull()
  })

  it('allows at most two tips a session, and lets one already counted come back until it is put away', () => {
    expect(TIPS_PER_SESSION).toBe(2)
    let s = newSession(T0)
    s = noteShown(s, 'a')
    s = noteShown(s, 'b')
    expect(s.shown).toEqual(['a', 'b'])
    expect(pickTip({ requests: [req('c', 1)], dismissed: [], session: s })).toBeNull()
    expect(pickTip({ requests: [req('c', 1), req('b', 2)], dismissed: [], session: s })).toBe('b')
    expect(withinAllowance(s, 'a')).toBe(true)
    expect(withinAllowance(s, 'c')).toBe(false)
    // Counting the same tip twice changes nothing.
    expect(noteShown(s, 'a')).toBe(s)
  })

  it('skips a tip with no place to show, and shows nothing while paused', () => {
    const s = newSession(T0)
    expect(pickTip({ requests: [req('a', 1, false), req('b', 2)], dismissed: [], session: s })).toBe('b')
    expect(pickTip({ requests: [req('a', 1)], dismissed: [], session: s, paused: true })).toBeNull()
  })

  it('keeps the session through short gaps and starts a new one after 30 minutes idle', () => {
    expect(SESSION_IDLE_MS).toBe(30 * 60 * 1000)
    const s = noteShown(noteShown(newSession(T0), 'a'), 'b')
    const later = rollSession(s, T0 + SESSION_IDLE_MS - 1)
    expect(later.started).toBe(T0)
    expect(later.shown).toEqual(['a', 'b'])
    expect(later.last).toBe(T0 + SESSION_IDLE_MS - 1)
    const fresh = rollSession(s, T0 + SESSION_IDLE_MS + 1)
    expect(fresh).toEqual({ started: T0 + SESSION_IDLE_MS + 1, last: T0 + SESSION_IDLE_MS + 1, shown: [] })
    expect(rollSession(null, T0)).toEqual(newSession(T0))
  })

  it('persists the session across reloads in localStorage, and survives bad or blocked storage', () => {
    const s = noteShown(newSession(T0), 'a')
    saveSession(s)
    expect(JSON.parse(window.localStorage.getItem(SESSION_KEY)!)).toEqual(s)
    expect(loadSession()).toEqual(s)
    window.localStorage.setItem(SESSION_KEY, '{nope')
    expect(loadSession()).toBeNull()
    window.localStorage.setItem(SESSION_KEY, JSON.stringify({ started: 'x' }))
    expect(loadSession()).toBeNull()
    const real = window.localStorage
    Object.defineProperty(window, 'localStorage', { configurable: true, get: () => { throw new Error('blocked') } })
    try {
      expect(loadSession()).toBeNull()
      expect(() => saveSession(s)).not.toThrow()
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real })
    }
  })
})
