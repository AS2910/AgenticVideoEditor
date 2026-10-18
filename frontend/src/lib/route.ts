import { useEffect, useState } from 'react'

/** Where the app is (Volt, 2026-10-18): one hash route, read on load and on
 *  every change. `#` or `#projects` is the start; `#p12` opens a project;
 *  `#p12/export` its export page; the account pages are `#voices`, `#usage`,
 *  `#settings` and `#billing`. */
export type Route =
  | { page: 'projects' }
  | { page: 'voices' }
  | { page: 'usage' }
  | { page: 'settings' }
  | { page: 'billing' }
  | { page: 'editor'; projectId: string }
  | { page: 'export'; projectId: string }

export function parseRoute(hash: string): Route {
  const h = hash.replace(/^#\/?/, '').trim()
  const m = /^(p\d+)(?:\/(export))?$/.exec(h)
  if (m) return m[2] === 'export' ? { page: 'export', projectId: m[1] } : { page: 'editor', projectId: m[1] }
  if (h === 'voices' || h === 'usage' || h === 'settings' || h === 'billing') return { page: h }
  return { page: 'projects' }
}

export const hrefFor = (r: Route): string =>
  r.page === 'editor' ? `#${r.projectId}` : r.page === 'export' ? `#${r.projectId}/export` : r.page === 'projects' ? '#projects' : `#${r.page}`

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
