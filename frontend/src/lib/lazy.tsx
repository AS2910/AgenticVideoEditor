import { Suspense } from 'react'
import type { ReactNode } from 'react'
import { Wave } from '../components/Wordmark'

/** Rehearsal item 7: the parts behind flags that are off for the public (phases B, C and D,
 *  A2, the admin pages) load on first use, so the first page carries less code. Each is
 *  `lazy(() => import('./pages/BinPage').then((m) => ({ default: m.BinPage })))`, shown inside
 *  one of these. */

/** A whole page while its code loads: a quiet, announced line in the middle of the screen. */
export function PageLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center gap-3 bg-background text-muted-foreground" role="status" aria-busy="true">
      <Wave busy /><span>Opening…</span>
    </div>
  )
}

/** A page that loads on first use. */
export function LazyPage({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageLoading />}>{children}</Suspense>
}

/** A part of a page (a panel, a dialog, a chip) that loads on first use: a short "Loading…"
 *  in its place, or nothing for something small (`quiet`). */
export function LazyPart({ children, quiet = false }: { children: ReactNode; quiet?: boolean }) {
  const fallback = quiet ? null : <span className="tag text-faint" role="status">Loading…</span>
  return <Suspense fallback={fallback}>{children}</Suspense>
}
