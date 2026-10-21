import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import type { Me } from '../api'
import { getMeAdmin } from '../api'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { initialOf } from './fmt'
import { useFlags } from '../flags/useFlags'
import { PausedBanner } from '../components/PausedBanner'
import { NotificationBell } from '../components/NotificationBell'

export type ShellPage = 'projects' | 'voices' | 'usage' | 'settings' | 'billing' | 'help' | 'bin'
const NAV: { page: ShellPage; label: string }[] = [
  { page: 'projects', label: 'Home' }, { page: 'voices', label: 'Voices' }, { page: 'usage', label: 'Usage' }, { page: 'settings', label: 'Settings' }, { page: 'help', label: 'Help' },
]

/** The bolt: a volt square with an ink bolt in it. */
export function BoltMark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <rect x=".75" y=".75" width="22.5" height="22.5" rx="6" className="fill-volt stroke-ink" strokeWidth="1.5" />
      <path d="M13.5 4 7 13h4.5l-1 7L17 11h-4.5z" className="fill-ink" />
    </svg>
  )
}
/** The small bolt that sits in a CTA. */
export const Bolt = ({ size = 13 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true"><path d="M9 1.5 3.5 9H8l-1 5.5L12.5 7H8z" fill="currentColor" /></svg>
)
export const PlayGlyph = ({ size = 12 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.5v11l9-5.5z" fill="currentColor" /></svg>
)
export const StopGlyph = ({ size = 12 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="3.5" width="9" height="9" rx="1.5" fill="currentColor" /></svg>
)

/** VOLTAGE with the bolt. A link to the projects by default; `href={null}` for a plain mark. */
export function Wordmark({ href = hrefFor({ page: 'projects' }), label = 'Voltage home', size = 26, className }: {
  href?: string | null; label?: string; size?: number; className?: string
}) {
  const cls = cn('disp inline-flex items-center gap-2.5 text-[17px] font-bold tracking-[.02em] text-foreground no-underline', className)
  const body = <><BoltMark size={size} />VOLTAGE</>
  return href ? <a href={href} aria-label={label} className={cls}>{body}</a> : <span className={cls}>{body}</span>
}

/** The account circle: the person's initial, or V when sign-in is off. Opens Settings. */
export function AccountDot({ me }: { me: Me | null }) {
  return (
    <a href={hrefFor({ page: 'settings' })} aria-label="Account" className="disp grid size-[34px] place-items-center rounded-full border-[1.5px] border-foreground text-sm font-bold text-foreground no-underline hover:bg-sunk">
      {initialOf(me)}
    </a>
  )
}

interface ShellProps {
  active: ShellPage
  right?: ReactNode
  me: Me | null
  children: ReactNode
  /** Layout classes for the page's `<main>`. */
  mainClassName?: string
}

/** The chrome of the account pages: the wordmark, the nav, a slot on the right, the account circle. */
export function Shell({ active, right, me, children, mainClassName }: ShellProps) {
  // Decision 0: the Bin is reached from Home's sidebar footer, not the main nav.
  const nav = NAV
  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      {/* The skip link focuses main by hand: a "#main" href would change the route. */}
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>Skip to content</a>
      <PausedBanner />
      <header className="flex min-h-[62px] flex-wrap items-center gap-x-[22px] gap-y-2 border-b-[1.5px] border-foreground bg-card px-4 py-2.5 sm:px-6">
        <Wordmark />
        <nav className="nav flex flex-wrap gap-1" aria-label="Main">
          {nav.map((n) => (
            <a key={n.page} href={hrefFor({ page: n.page })} aria-current={n.page === active ? 'page' : undefined}>{n.label}</a>
          ))}
        </nav>
        <span className="flex-1" />
        {right}
        <NotificationBell />
        <AccountDot me={me} />
      </header>
      <main id="main" tabIndex={-1} className={cn('flex-1 outline-none', mainClassName)}>{children}</main>
    </div>
  )
}

const SIDE = [{ id: 'agent', label: 'What Voltage may do' }, { id: 'look', label: 'Appearance' }, { id: 'account', label: 'Account' }] as const
export type SideSection = (typeof SIDE)[number]['id']

/** The side nav of Settings and Billing. On Settings the three sections scroll into view
 *  (an in-page `#agent` href would be read as a route); from Billing they open Settings. */
/** G7: whether the internal admin page is yours (asked once per page load, only with golive.g7 on). */
let adminAsked: Promise<boolean> | null = null
function useAdmin(on: boolean): boolean {
  const [admin, setAdmin] = useState(false)
  useEffect(() => {
    if (!on) return
    let live = true
    adminAsked ??= getMeAdmin().catch(() => { adminAsked = null; return false })
    void adminAsked.then((a) => { if (live) setAdmin(a) })
    return () => { live = false }
  }, [on])
  return admin
}

export function SideNav({ active, onSection }: { active: SideSection | 'usage' | 'billing' | 'members' | 'notifications' | 'admin'; onSection?: (id: SideSection) => void }) {
  const flagged = useFlags()
  const membersOn = flagged.enabled('golive.g2')
  const notesOn = flagged.enabled('golive.g4')
  const admin = useAdmin(flagged.enabled('golive.g7'))
  const item = 'block rounded-lg px-3 py-[9px] text-left font-medium text-muted-foreground no-underline hover:bg-sunk hover:text-foreground'
  const on = 'border-[1.5px] border-foreground bg-card text-foreground'
  return (
    <nav aria-label="Settings sections" className="flex shrink-0 flex-col gap-1 sm:basis-[220px]">
      {SIDE.map((s) => onSection
        ? <button key={s.id} type="button" className={cn(item, active === s.id && on)} aria-current={active === s.id ? 'true' : undefined} onClick={() => onSection(s.id)}>{s.label}</button>
        : <a key={s.id} href={hrefFor({ page: 'settings' })} className={item}>{s.label}</a>)}
      {membersOn && <a href={hrefFor({ page: 'members' })} className={cn(item, active === 'members' && on)} aria-current={active === 'members' ? 'page' : undefined}>Members</a>}
      {notesOn && <a href={hrefFor({ page: 'notifications' })} className={cn(item, active === 'notifications' && on)} aria-current={active === 'notifications' ? 'page' : undefined}>Notifications</a>}
      <a href={hrefFor({ page: 'usage' })} className={cn(item, active === 'usage' && on)}>Usage</a>
      <a href={hrefFor({ page: 'billing' })} className={cn(item, active === 'billing' && on)} aria-current={active === 'billing' ? 'page' : undefined}>Billing</a>
      {admin && <a href={hrefFor({ page: 'admin' })} className={cn(item, active === 'admin' && on)} aria-current={active === 'admin' ? 'page' : undefined}>Admin</a>}
    </nav>
  )
}
