import { useCallback, useEffect, useState } from 'react'
import type { NotificationSetting } from '../types'
import type { Me } from '../api'
import { getNotificationSettings, putNotificationSettings } from '../api'
import { cn } from '@/lib/utils'
import { Shell, SideNav } from './Shell'
import { said } from './fmt'
import { Tip } from '../guides/Tip'

/** A checkbox styled as a small switch, labelled for its row and channel. */
function Toggle({ on, label, onToggle, disabled }: { on: boolean; label: string; onToggle: () => void; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={onToggle} disabled={disabled}
      className={cn('relative h-[26px] w-[46px] shrink-0 rounded-full border-[1.5px] p-0 transition-colors pointer-coarse:h-11 pointer-coarse:w-16', on ? 'border-ink bg-volt' : 'border-foreground bg-sunk')}>
      <span aria-hidden="true" className={cn('absolute top-0.5 left-0.5 block size-[19px] rounded-full transition-transform', on ? 'translate-x-5 bg-ink' : 'bg-foreground')} />
    </button>
  )
}

/** G4: Settings > Notifications. Per kind, in the app and by email. Email
 *  arrives batched (one email at most every 10 minutes). Saves at once. */
export function NotificationsPage({ me }: { me: Me | null }) {
  const [kinds, setKinds] = useState<NotificationSetting[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const load = useCallback(() => {
    setError(null)
    getNotificationSettings().then((r) => setKinds(r.kinds)).catch((e) => setError(said(e, 'Your notification settings could not be read.')))
  }, [])
  useEffect(() => { load() }, [load])

  const flip = async (kind: string, channel: 'in_app' | 'email') => {
    if (!kinds) return
    const before = kinds
    const now = kinds.find((k) => k.kind === kind)
    if (!now) return
    setKinds(kinds.map((k) => (k.kind === kind ? { ...k, [channel]: !k[channel] } : k)))
    try {
      setKinds((await putNotificationSettings({ [kind]: { [channel]: !now[channel] } })).kinds)
      setStatus('Saved.')
    } catch (e) {
      setKinds(before)
      setStatus(said(e, 'That did not save. Try again.'))
    }
  }

  return (
    <Shell active="settings" me={me} mainClassName="mx-auto flex w-full max-w-[1100px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active="notifications" />
      <div className="flex min-w-0 flex-1 flex-col gap-[22px]">
        <h1 className="disp rise m-0 mb-1 text-[56px] leading-none font-bold">Notifications</h1>
        <p className="m-0 max-w-[640px] text-muted-foreground">The bell shows what you choose here. Email comes batched, at most one every 10 minutes.</p>
        {error && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {error}<button type="button" className="btn sm" onClick={load}>Try again</button>
          </div>
        )}
        {!error && !kinds && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading your settings…</p>}
        {kinds && (
          <section className="rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" data-testid="notification-settings" data-tour="notification-settings">
            <div className="grid grid-cols-[minmax(0,1fr)_64px_64px] items-center gap-x-4 pb-2">
              <span className="tag text-faint">What</span><span className="tag text-center text-faint">In app</span><span className="tag text-center text-faint">Email</span>
            </div>
            {kinds.map((k) => (
              <div key={k.kind} className="grid grid-cols-[minmax(0,1fr)_64px_64px] items-center gap-x-4 border-t border-line py-3.5" data-testid="notification-kind">
                <div><div className="font-semibold">{k.label}</div><div className="text-[13px] text-muted-foreground">{k.help}</div></div>
                <span className="grid place-items-center"><Toggle on={k.in_app} label={`${k.label} in the app`} onToggle={() => void flip(k.kind, 'in_app')} /></span>
                <span className="grid place-items-center"><Toggle on={k.email} label={`${k.label} by email`} onToggle={() => void flip(k.kind, 'email')} /></span>
              </div>
            ))}
          </section>
        )}
        {kinds && <Tip id="first-notifications" />}
        <p className="m-0 min-h-5 text-sm text-muted-foreground" role="status" aria-live="polite">{status}</p>
      </div>
    </Shell>
  )
}
