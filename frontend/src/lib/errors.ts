/** G8: the browser's error hook. window.onerror and unhandledrejection (installed once by
 *  main.tsx) and the React error boundary send what broke to `POST /errors`, with where it
 *  happened, when `golive.g8` is on. At most 5 a minute leave this tab (the server also limits);
 *  the same message twice in a row is sent once. Never throws. */
import { flagOn } from '../flags/useFlags'

const WINDOW_MS = 60_000
const MAX_PER_WINDOW = 5
let sent: number[] = []
let last = ''

export interface ErrorReport { message: string; stack?: string; where?: string; kind?: 'error' | 'rejection' | 'boundary' }

export function reportError(report: ErrorReport): void {
  const now = Date.now()
  sent = sent.filter((t) => now - t < WINDOW_MS)
  const message = (report.message || 'Unknown error').slice(0, 2000)
  if (sent.length >= MAX_PER_WINDOW || message === last) return
  sent.push(now)
  last = message
  void (async () => {
    try {
      if (!(await flagOn('golive.g8'))) return
      await fetch('/api/errors', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'voltage' },
        body: JSON.stringify({ message, stack: (report.stack ?? '').slice(0, 6000), where: report.where ?? window.location.hash, kind: report.kind ?? 'error' }),
        keepalive: true,
      })
    } catch {
      // A report that cannot be sent is dropped.
    }
  })()
}

let installed = false
/** Listen for errors nothing else caught. Once per page. */
export function installErrorHooks(): void {
  if (installed || typeof window === 'undefined') return
  installed = true
  window.addEventListener('error', (e) => {
    reportError({ message: e.message || String(e.error ?? 'Script error'), stack: e.error instanceof Error ? e.error.stack : '', kind: 'error' })
  })
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason
    reportError({ message: r instanceof Error ? r.message : String(r), stack: r instanceof Error ? r.stack : '', kind: 'rejection' })
  })
}

/** Tests: forget what was sent. */
export function resetErrorReports(): void { sent = []; last = '' }
