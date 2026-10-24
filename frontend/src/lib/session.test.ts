import { describe, it, expect, vi, afterEach } from 'vitest'
import { askWhoIsHere, resetSession, signedInHere } from './session'
import { refreshMediaToken, resetMediaToken, signed } from './media'
import { flagOn, resetFlags } from '../flags/useFlags'

const answer = (me: unknown) => vi.fn(async (url: string) => {
  if (url.endsWith('/auth/me')) return new Response(JSON.stringify(me), { status: 200, headers: { 'Content-Type': 'application/json' } })
  if (url.endsWith('/me/flags')) return new Response(JSON.stringify({ flags: ['golive.g7'] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  return new Response(JSON.stringify({ token: 't.k', expires_in: 43200 }), { status: 200, headers: { 'Content-Type': 'application/json' } })
})

describe('who is here (run 4 item 4c)', () => {
  afterEach(() => { resetSession(); resetFlags(); resetMediaToken(); vi.unstubAllGlobals() })

  it('asks nothing that needs a session for someone signed out', async () => {
    const f = answer({ mode: 'accounts', user: null })
    vi.stubGlobal('fetch', f)
    void askWhoIsHere()
    expect(await signedInHere()).toBe(false)
    expect(await flagOn('golive.g7')).toBe(false)
    await refreshMediaToken()
    expect(signed('/a')).toBe('/a')
    expect(f.mock.calls.map((c) => String(c[0]))).toEqual(['/api/auth/me'])
  })

  it('asks as the person once signed in, or with sign-in off', async () => {
    for (const me of [{ mode: 'accounts', user: { sub: 'a', email: 'a@x.co', name: null, picture: null } }, { mode: 'off', user: null }]) {
      resetFlags()
      vi.stubGlobal('fetch', answer(me))
      void askWhoIsHere()
      expect(await signedInHere()).toBe(true)
      expect(await flagOn('golive.g7')).toBe(true)
    }
  })

  it('goes ahead as before when the app has not asked', async () => {
    expect(await signedInHere()).toBe(true)
  })
})
