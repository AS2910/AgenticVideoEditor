import { useEffect, useState } from 'react'

/** Where the app is (Volt, 2026-10-18; folders, 2026-10-19): one hash route,
 *  read on load and on every change. `#`, `#home` or `#projects` is the
 *  start; `#v/p12` opens a video in the editor and `#v/p12/export` its
 *  export page; `#p/f3` is a project (a folder of videos); the account pages
 *  are `#voices`, `#usage`, `#settings`, `#billing` and `#help` (with an
 *  article: `#help/<slug>`). An old `#p12` link still opens the video. */
export type Route =
  | { page: 'projects' }
  | { page: 'voices' }
  | { page: 'usage' }
  | { page: 'settings' }
  | { page: 'billing' }
  | { page: 'help'; slug?: string | null }
  | { page: 'folder'; projectId: string }
  | { page: 'editor'; projectId: string }
  | { page: 'export'; projectId: string }

export function parseRoute(hash: string): Route {
  const h = hash.replace(/^#\/?/, '').trim()
  const v = /^v\/([A-Za-z0-9_-]+)(?:\/(export))?$/.exec(h)
  if (v) return v[2] === 'export' ? { page: 'export', projectId: v[1] } : { page: 'editor', projectId: v[1] }
  const f = /^p\/([A-Za-z0-9_-]+)$/.exec(h)
  if (f) return { page: 'folder', projectId: f[1] }
  // The links of the first release: `#p12` and `#p12/export` named a video.
  const old = /^(p\d+)(?:\/(export))?$/.exec(h)
  if (old) return old[2] === 'export' ? { page: 'export', projectId: old[1] } : { page: 'editor', projectId: old[1] }
  const help = /^help(?:\/([A-Za-z0-9_-]+))?$/.exec(h)
  if (help) return { page: 'help', slug: help[1] ?? null }
  if (h === 'voices' || h === 'usage' || h === 'settings' || h === 'billing') return { page: h }
  return { page: 'projects' }
}

export const hrefFor = (r: Route): string =>
  r.page === 'editor' ? `#v/${r.projectId}`
    : r.page === 'export' ? `#v/${r.projectId}/export`
    : r.page === 'folder' ? `#p/${r.projectId}`
    : r.page === 'help' ? (r.slug ? `#help/${r.slug}` : '#help')
    : r.page === 'projects' ? '#home'
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
