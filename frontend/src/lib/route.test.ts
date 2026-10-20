import { describe, it, expect } from 'vitest'
import { hrefFor, parseRoute } from './route'

describe('the Usage route takes a scope', () => {
  it('reads and writes one video, one project, the standalone videos, and none', () => {
    expect(parseRoute('#usage')).toEqual({ page: 'usage' })
    expect(parseRoute('#usage/v/p12')).toEqual({ page: 'usage', scope: { kind: 'video', id: 'p12' } })
    expect(parseRoute('#usage/p/f3')).toEqual({ page: 'usage', scope: { kind: 'project', id: 'f3' } })
    expect(parseRoute('#usage/none')).toEqual({ page: 'usage', scope: { kind: 'none' } })
    expect(hrefFor({ page: 'usage' })).toBe('#usage')
    expect(hrefFor({ page: 'usage', scope: { kind: 'video', id: 'p12' } })).toBe('#usage/v/p12')
    expect(hrefFor({ page: 'usage', scope: { kind: 'project', id: 'f3' } })).toBe('#usage/p/f3')
    expect(hrefFor({ page: 'usage', scope: { kind: 'none' } })).toBe('#usage/none')
    expect(parseRoute('#usage/x/1')).toEqual({ page: 'projects' })
  })
})

describe('A2: the editor route takes a time', () => {
  it('opens a video at a time and writes it back', () => {
    expect(parseRoute('#v/p12@3.5')).toEqual({ page: 'editor', projectId: 'p12', t: 3.5 })
    expect(parseRoute('#v/p12')).toEqual({ page: 'editor', projectId: 'p12' })
    expect(parseRoute('#v/p12/export')).toEqual({ page: 'export', projectId: 'p12' })
    expect(hrefFor({ page: 'editor', projectId: 'p12', t: 12.345 })).toBe('#v/p12@12.35')
    expect(hrefFor({ page: 'editor', projectId: 'p12', t: null })).toBe('#v/p12')
  })
})
