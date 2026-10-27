import { useEffect, useState } from 'react'

/** Where the app is (Volt, 2026-10-18; folders, 2026-10-19): one hash route,
 *  read on load and on every change. `#`, `#home` or `#projects` is the
 *  start; `#v/p12` opens a video in the editor and `#v/p12/export` its
 *  export page; `#p/f3` is a project (a folder of videos); the account pages
 *  are `#voices`, `#usage`, `#settings`, `#billing`, `#bin` (D3), `#templates` (D1), `#members` (G2), `#notifications` (G4) and `#help` (with an
 *  article: `#help/<slug>`). Usage takes a scope: `#usage/v/p12` (one
 *  video), `#usage/p/f3` (one project), `#usage/none` (standalone videos).
 *  An old `#p12` link still opens the video. A2: `#v/p12@3.5` opens the
 *  editor at 3.5 s of the source (a link from the project check). G2:
 *  `#invite/<token>` opens a workspace invite. */
export type UsageScope = { kind: 'video'; id: string } | { kind: 'project'; id: string } | { kind: 'none' }

export type Route =
  | { page: 'projects' }
  | { page: 'voices' }
  | { page: 'usage'; scope?: UsageScope | null }
  | { page: 'settings' }
  | { page: 'billing' }
  | { page: 'bin' }
  | { page: 'templates' }
  | { page: 'help'; slug?: string | null }
  | { page: 'folder'; projectId: string }
  | { page: 'editor'; projectId: string; t?: number | null }
  | { page: 'export'; projectId: string }
  | { page: 'members' }
  | { page: 'notifications' }
  | { page: 'admin' }
  // Launch item 9: the email preview (admins only).
  | { page: 'adminEmails' }
  // Run 5 item 7: the voice A/B listening page (admins only).
  | { page: 'adminVoiceAb' }
  | { page: 'legal'; doc: 'terms' | 'privacy' | 'acceptable-use' | 'subprocessors' }
  | { page: 'invite'; token: string }
  // Launch item 5: a password reset link, and the sign-in page (with an error a link landed on).
  | { page: 'reset'; token: string }
  | { page: 'login'; error?: string | null }
  // Launch item 8: the public landing page for anyone (signed-out people see it at the start too).
  | { page: 'welcome' }
  // Beta kit: what we know is not right yet (the Beta badge links here).
  | { page: 'knownIssues' }

export function parseRoute(hash: string): Route {
  const h = hash.replace(/^#\/?/, '').trim()
  const v = /^v\/([A-Za-z0-9_-]+)(?:@(\d+(?:\.\d+)?))?(?:\/(export))?$/.exec(h)
  if (v) return v[3] === 'export' ? { page: 'export', projectId: v[1] } : v[2] ? { page: 'editor', projectId: v[1], t: Number(v[2]) } : { page: 'editor', projectId: v[1] }
  const f = /^p\/([A-Za-z0-9_-]+)$/.exec(h)
  if (f) return { page: 'folder', projectId: f[1] }
  // The links of the first release: `#p12` and `#p12/export` named a video.
  const old = /^(p\d+)(?:\/(export))?$/.exec(h)
  if (old) return old[2] === 'export' ? { page: 'export', projectId: old[1] } : { page: 'editor', projectId: old[1] }
  const usage = /^usage(?:\/(?:(v|p)\/([A-Za-z0-9_-]+)|(none)))?$/.exec(h)
  if (usage) {
    if (usage[3]) return { page: 'usage', scope: { kind: 'none' } }
    if (usage[1]) return { page: 'usage', scope: { kind: usage[1] === 'v' ? 'video' : 'project', id: usage[2] } }
    return { page: 'usage' }
  }
  const reset = /^reset\/([A-Za-z0-9_-]+)$/.exec(h)
  if (reset) return { page: 'reset', token: reset[1] }
  const login = /^login(?:\?error=(.*))?$/.exec(h)
  if (login) return { page: 'login', error: login[1] ? decodeURIComponent(login[1]) : null }
  const invite = /^invite\/([A-Za-z0-9_.-]+)$/.exec(h)
  if (invite) return { page: 'invite', token: invite[1] }
  if (h === 'welcome') return { page: 'welcome' }
  if (h === 'known-issues') return { page: 'knownIssues' }
  if (h === 'members') return { page: 'members' }
  if (h === 'notifications') return { page: 'notifications' }
  if (h === 'admin') return { page: 'admin' }
  if (h === 'admin/emails') return { page: 'adminEmails' }
  if (h === 'admin/voice-ab') return { page: 'adminVoiceAb' }
  if (h === 'terms' || h === 'privacy' || h === 'acceptable-use' || h === 'subprocessors') return { page: 'legal', doc: h }
  const help = /^help(?:\/([A-Za-z0-9_-]+))?$/.exec(h)
  if (help) return { page: 'help', slug: help[1] ?? null }
  if (h === 'voices' || h === 'settings' || h === 'billing' || h === 'bin' || h === 'templates') return { page: h }
  return { page: 'projects' }
}

export const hrefFor = (r: Route): string =>
  r.page === 'editor' ? `#v/${r.projectId}${r.t != null ? `@${Math.max(0, Math.round(r.t * 100) / 100)}` : ''}`
    : r.page === 'export' ? `#v/${r.projectId}/export`
    : r.page === 'folder' ? `#p/${r.projectId}`
    : r.page === 'help' ? (r.slug ? `#help/${r.slug}` : '#help')
    : r.page === 'projects' ? '#home'
    : r.page === 'adminEmails' ? '#admin/emails'
    : r.page === 'adminVoiceAb' ? '#admin/voice-ab'
    : r.page === 'knownIssues' ? '#known-issues'
    : r.page === 'invite' ? `#invite/${r.token}`
    : r.page === 'reset' ? `#reset/${r.token}`
    : r.page === 'login' ? (r.error ? `#login?error=${encodeURIComponent(r.error)}` : '#login')
    : r.page === 'legal' ? `#${r.doc}`
    : r.page === 'usage' ? (!r.scope ? '#usage' : r.scope.kind === 'none' ? '#usage/none' : `#usage/${r.scope.kind === 'video' ? 'v' : 'p'}/${r.scope.id}`)
    : `#${r.page}`

export function go(r: Route): void {
  window.location.hash = hrefFor(r)
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(typeof window === 'undefined' ? '' : window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
