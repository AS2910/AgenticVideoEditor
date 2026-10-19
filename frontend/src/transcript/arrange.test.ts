/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { EMPTY, moveTo, overrun, pinConflict, place, specs } from './arrange'
import type { Arrangement } from './arrange'

interface Case {
  name: string
  statements: [number, number][]
  lengths: Record<string, number>
  arrangement: Partial<Arrangement>
  duration: number
  placed: unknown[]
  overrun: number
}

// The server's own cases, read from where its tests keep them.
const CASES: Case[] = JSON.parse(readFileSync(resolve(process.cwd(), '../backend/tests/fixtures/arrange-cases.json'), 'utf8'))

describe('the arrangement, as the server places it', () => {
  it.each(CASES.map((c) => [c.name, c] as const))('%s', (_, c) => {
    const lines = specs(c.statements.map(([start, end]) => ({ start, end })), c.lengths)
    const placed = place(lines, { ...EMPTY, ...c.arrangement })
    expect(placed).toEqual(c.placed)
    expect(overrun(placed, c.duration)).toBe(c.overrun)
  })

  it('names two pins that would play at once', () => {
    const lines = specs([{ start: 0, end: 1 }, { start: 2, end: 3 }])
    expect(pinConflict(lines, { L0: 0, L1: 0.5 })).toMatch(/would play at once/)
    expect(pinConflict(lines, { L0: 0, L1: 1 })).toBeNull()
  })

  it('moves a key to a place in the order', () => {
    expect(moveTo(['L0', 'L1', 'L2'], 'L2', 0)).toEqual(['L2', 'L0', 'L1'])
    expect(moveTo(['L0', 'L1', 'L2'], 'L0', 2)).toEqual(['L1', 'L2', 'L0'])
  })
})
