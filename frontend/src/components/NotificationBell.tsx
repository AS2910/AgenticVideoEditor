import { useCallback, useEffect, useRef, useState } from 'react'
import type { NotificationItem } from '../types'
import { getNotificationCount, listNotifications, markNotificationsRead } from '../api'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { useFlags } from '../flags/useFlags'
import { whenLabel } from '../pages/fmt'

const POLL_MS = 20_000

const BellGlyph = () => (
  <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5a5 5 0 0 0-5 5v3.2L3.6 13.5h12.8L15 10.7V7.5a5 5 0 0 0-5-5zM8 15.5a2 2 0 0 0 4 0" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" /></svg>
)

/** G4: the bell in the header (account pages and the editor). The unread
 *  count is read every 20 s while the tab is visible; the list opens in a
 *  small card with Mark all read, each item opening where it points. */
export function NotificationBell({ dark = false }: { dark?: boolean }) {
  const on = useFlags().enabled('golive.g4')
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<NotificationItem[] | null>(null)
  const [error, setError] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)

  const count = useCallback(() => {
    getNotificationCount().then((r) => setUnread(r.unread)).catch(() => { /* the bell stays as it was */ })
  }, [])
  useEffect(() => {
    if (!on) return
    count()
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') count() }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [on, count])

  const load = useCallback(() => {
    setError(false)
    listNotifications().then((r) => { setItems(r.items); setUnread(r.unread) }).catch(() => setError(true))
  }, [])
  useEffect(() => { if (open) load() }, [open, load])
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); button.current?.focus() } }
    window.addEventListener('mousedown', away)
    window.addEventListener('keydown', esc)
    return () => { window.removeEventListener('mousedown', away); window.removeEventListener('keydown', esc) }
  }, [open])

  if (!on) return null
  const readAll = async () => {
    setItems((list) => list?.map((i) => ({ ...i, read: true })) ?? list)
    try { setUnread((await markNotificationsRead({ all: true })).unread) } catch { load() }
  }
  const openItem = (n: NotificationItem) => {
    if (!n.read) markNotificationsRead({ ids: [n.id] }).then((r) => setUnread(r.unread)).catch(() => { /* still opens */ })
    setOpen(false)
    if (n.link) window.location.hash = n.link.replace(/^#/, '')
  }
  const label = unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'
  return (
    <div className="relative" ref={box}>
      <button ref={button} type="button" aria-label={label} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((v) => !v)}
        className={cn('relative grid size-[34px] place-items-center rounded-full border-[1.5px] pointer-coarse:size-11', dark ? 'border-pline text-ptext hover:bg-psunk' : 'border-foreground text-foreground hover:bg-sunk')}
        data-testid="bell">
        <BellGlyph />
        {unread > 0 && <span className="tnum absolute -top-1.5 -right-1.5 grid h-[18px] min-w-[18px] place-items-center rounded-full border-[1.5px] border-ink bg-volt px-1 text-[12px] leading-none font-semibold text-ink" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
      </button>
      <span className="sr-only" role="status" aria-atomic="true">{unread > 0 ? `${unread} unread notification${unread === 1 ? '' : 's'}` : ''}</span>
      {open && (
        <div role="dialog" aria-label="Notifications" className="absolute right-0 z-50 mt-2 flex max-h-[70dvh] w-[min(360px,calc(100vw-32px))] flex-col overflow-hidden rounded-xl border-[1.5px] border-ink bg-card text-foreground shadow-volt" data-testid="bell-panel">
          <div className="flex items-center gap-2 border-b border-line px-4 py-3">
            <span className="disp flex-1 text-base font-bold">Notifications</span>
            {unread > 0 && <button type="button" className="act" onClick={() => void readAll()}>Mark all read</button>}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {error && <p className="m-0 flex items-center gap-2 px-4 py-3 text-sm text-destructive" role="alert">Notifications could not be read. <button type="button" className="act" onClick={load}>Try again</button></p>}
            {!error && items === null && <p className="m-0 px-4 py-3 text-sm text-muted-foreground" role="status" aria-busy="true">Reading…</p>}
            {items && items.length === 0 && <p className="m-0 px-4 py-4 text-sm text-muted-foreground">Nothing yet. Long work finishing, failures, review news and spend alerts show here.</p>}
            {items && items.length > 0 && (
              <ul className="m-0 list-none p-0">
                {items.map((n) => (
                  <li key={n.id} className="border-b border-line last:border-b-0">
                    <button type="button" className={cn('flex w-full items-start gap-2.5 px-4 py-3 text-left hover:bg-sunk', !n.read && 'bg-sunk/50')} onClick={() => openItem(n)} data-testid="bell-item">
                      <span aria-hidden="true" className={cn('mt-1.5 size-2 flex-none rounded-full', n.read ? 'bg-transparent' : n.kind === 'job_failed' || n.kind === 'spend_alert' ? 'bg-warn' : 'bg-volt ring-1 ring-ink')} />
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className={cn('text-sm', !n.read && 'font-semibold')}>{n.title}</span>
                        {n.body && <span className="line-clamp-2 text-[13px] text-muted-foreground">{n.body}</span>}
                        <span className="tag text-faint">{whenLabel(n.created_at)}{n.read ? '' : ' · unread'}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <a className="act border-t border-line px-4 py-2.5" href={hrefFor({ page: 'notifications' })} onClick={() => setOpen(false)}>Notification settings</a>
        </div>
      )}
    </div>
  )
}
