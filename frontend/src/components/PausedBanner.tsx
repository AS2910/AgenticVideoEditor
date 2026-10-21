import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

/** Launch item 3: while new paid work is paused for everyone (the admin's
 *  switch, or the day's spend cap), a friendly line says so. Reads the public
 *  `/api/status` now and every minute; says nothing when it cannot read it. */
export const STATUS_POLL_MS = 60_000

export function PausedBanner({ floating = false }: { floating?: boolean }) {
  const [message, setMessage] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    const read = () => fetch('/api/status').then((r) => (r.ok ? r.json() : null)).then((s) => {
      if (live) setMessage(s && s.paid_paused && typeof s.message === 'string' ? s.message : null)
    }).catch(() => { /* the banner is a courtesy; no status, no banner */ })
    read()
    const timer = setInterval(read, STATUS_POLL_MS)
    return () => { live = false; clearInterval(timer) }
  }, [])
  if (!message) return null
  return (
    <div role="status" aria-live="polite" data-testid="paused-banner"
      className={cn('flex items-center gap-2.5 border-[1.5px] border-warn bg-card px-3.5 py-2.5 text-sm text-foreground',
        floating ? 'fixed bottom-4 left-4 z-40 max-w-[min(520px,calc(100vw-32px))] rounded-xl' : 'border-x-0 border-t-0')}>
      <span className="stamp need shrink-0">Paused</span>
      <span className="min-w-0">{message}</span>
    </div>
  )
}
