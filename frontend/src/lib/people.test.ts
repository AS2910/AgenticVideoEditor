import { describe, expect, it } from 'vitest'
import { editorName } from './people'
import type { Me } from '../api'

const me: Me = { mode: 'accounts', user: { sub: '9aaddbd873949cc9', email: 'ann@x.io', name: null, picture: null, provider: 'acct' } }

describe('editorName (rehearsal item 7): a person, never an owner id', () => {
  it('says you for your own saves, whatever form the id takes', () => {
    expect(editorName('acct:9aaddbd873949cc9', me)).toBe('you')
    expect(editorName('google:x', me, 'ann@x.io')).toBe('you')
    expect(editorName('local', null)).toBe('you')
  })
  it("names someone else by their address, and never shows an id", () => {
    expect(editorName('acct:1234', me, 'ed@x.io')).toBe('ed@x.io')
    expect(editorName('acct:1234', me)).toBe('a teammate')
    expect(editorName('email:sam@x.io', me)).toBe('sam@x.io')
    expect(editorName(null, me)).toBe('someone')
  })
})
