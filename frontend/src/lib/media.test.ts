import { describe, it, expect, vi, afterEach } from 'vitest'
import { refreshMediaToken, resetMediaToken, signed } from './media'
import { artifactUrl, frameUrl, voiceSampleUrl } from '../api'

describe('signed media URLs (launch item 2)', () => {
  afterEach(() => { resetMediaToken(); vi.unstubAllGlobals() })

  it('adds the token to every media address once there is one', async () => {
    expect(artifactUrl('p1', 'ab')).toBe('/api/videos/p1/artifacts/ab')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ token: 't.k', expires_in: 43200 }) })))
    await refreshMediaToken()
    expect(artifactUrl('p1', 'ab')).toBe('/api/videos/p1/artifacts/ab?mt=t.k')
    expect(frameUrl('p1', 2)).toBe('/api/videos/p1/frames/2?mt=t.k')
    expect(voiceSampleUrl('cd')).toBe('/api/voices/sample/cd?mt=t.k')
    expect(signed('/api/x?download=true')).toBe('/api/x?download=true&mt=t.k')
  })

  it('keeps the old token when the server says no', async () => {
    resetMediaToken('old', 100)
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })))
    await refreshMediaToken()
    expect(signed('/a')).toBe('/a?mt=old')
  })
})
