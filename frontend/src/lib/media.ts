import { useEffect, useState } from 'react'
import { signedInHere } from './session'

/** Launch item 2: media and exports are served only through signed,
 *  expiring URLs. The server signs a token for the signed-in owner
 *  (`GET /api/me/media-token`, 12 hours); every media address the app builds
 *  carries it as `mt`. The token is fetched once at start and again a while
 *  before it expires (a new token changes every media address, so a playing
 *  video reloads: kept rare on purpose). */

let token = ''
let expiresAt = 0
let loading: Promise<void> | null = null
const listeners = new Set<() => void>()
// Fetch a new one when less than this is left.
const REFRESH_BEFORE_MS = 60 * 60 * 1000

export function mediaToken(): string { return token }

/** `url` with the media token added (unchanged while there is none yet). */
export function signed(url: string): string {
  if (!token) return url
  return `${url}${url.includes('?') ? '&' : '?'}mt=${encodeURIComponent(token)}`
}

export function refreshMediaToken(): Promise<void> {
  if (loading) return loading
  loading = (async () => {
    try {
      if (!(await signedInHere())) return          // run 4 item 4c: signed out, no token to ask for
      const res = await fetch('/api/me/media-token', { credentials: 'same-origin' })
      if (!res.ok) return
      const body = await res.json() as { token?: unknown; expires_in?: unknown }
      if (typeof body?.token !== 'string' || typeof body.expires_in !== 'number') return
      token = body.token
      expiresAt = Date.now() + body.expires_in * 1000
      listeners.forEach((l) => l())
    } catch { /* offline or signed out: media waits for the next try */ } finally { loading = null }
  })()
  return loading
}

/** For the app's root: loads the token, keeps it fresh, and re-renders when it changes. */
export function useMediaToken(): string {
  const [, setTick] = useState(0)
  useEffect(() => {
    const changed = () => setTick((t) => t + 1)
    listeners.add(changed)
    if (!token || expiresAt - Date.now() < REFRESH_BEFORE_MS) void refreshMediaToken()
    const timer = setInterval(() => { if (expiresAt - Date.now() < REFRESH_BEFORE_MS) void refreshMediaToken() }, 5 * 60 * 1000)
    return () => { listeners.delete(changed); clearInterval(timer) }
  }, [])
  return token
}

/** Tests: forget the token. */
export function resetMediaToken(value = '', expiresInS = 0): void {
  token = value
  expiresAt = value ? Date.now() + expiresInS * 1000 : 0
}
