import { describe, it, expect } from 'vitest'
import { changedWords, quickRoute } from './fastpath'

describe('changedWords', () => {
  it('counts the longer side of each changed run, ignoring case and punctuation', () => {
    expect(changedWords('Get 20% off today only.', 'Get 30% off today only.')).toBe(1)
    expect(changedWords('Get 20% off today only.', 'Get 30% off this weekend only!')).toBe(3)
    expect(changedWords('Fresh bread every single morning.', 'Warm rolls every Sunday afternoon.')).toBe(4)
    expect(changedWords('Same words.', 'same words')).toBe(0)
  })
})

describe('quickRoute', () => {
  it('sends a four-word change in the line\'s own voice the fast way', () => {
    expect(quickRoute('Fresh bread every single morning.', 'Warm rolls every Sunday afternoon.', false))
      .toEqual({ fast: true, changed: 4, reason: '4 words changed' })
  })
  it('sends more than eight words, a new voice, or nothing changed the full way', () => {
    expect(quickRoute('Get 20% off today.', 'Get thirty percent off every single thing in the shop until Sunday.', false).fast).toBe(false)
    expect(quickRoute('a b', 'a c', true).reason).toBe('a different voice')
    expect(quickRoute('a b', 'a b', false).fast).toBe(false)
  })
})
