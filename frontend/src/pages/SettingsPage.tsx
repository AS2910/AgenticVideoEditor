import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { AskBefore, Autonomy, Effort, UserSettings } from '../types'
import type { Me } from '../api'
import { ApiError, changeEmail, deleteAccount, getUserSettings, getUsageReport, logout, updateUserSettings } from '../api'
import { go } from '../lib/route'
import { useTheme } from '../lib/theme'
import type { Theme } from '../lib/theme'
import { cn } from '@/lib/utils'
import { Shell, SideNav } from './Shell'
import type { SideSection } from './Shell'
import { initialOf, said, usd } from './fmt'
import { useFlags } from '../flags/useFlags'
import { YourData } from './YourData'
import { LegalLinks } from './LegalPage'

interface SettingsPageProps { me: Me | null; onSignedOut: () => void }

const AUTOS: { key: Autonomy; tag: string; title: string; desc: string }[] = [
  { key: 'ask', tag: 'Default', title: 'Check with me', desc: 'Every paid step or change to the video waits for your go.' },
  { key: 'draft', tag: 'Fast', title: 'Just do it', desc: 'Voltage voices, fixes and keeps going. It still asks for the steps below.' },
]
const EFFORTS: { key: Effort; label: string }[] = [{ key: 'medium', label: 'Medium' }, { key: 'high', label: 'High' }, { key: 'xhigh', label: 'Extra' }]
const THEMES: { key: Theme; label: string }[] = [{ key: 'light', label: 'Light' }, { key: 'dark', label: 'Dark' }, { key: 'system', label: 'System' }]
const ASKS: { key: keyof AskBefore; label: string; desc: string }[] = [
  { key: 'ship', label: 'Exporting the video', desc: 'Rendering a new file with what is added' },
  { key: 'clone', label: 'Cloning a speaker', desc: 'Uses a voice slot and their speech' },
  { key: 'design', label: 'Designing a new voice', desc: 'About $0.06 and a voice slot' },
]
// The turn cap moves in 10¢ steps between 10¢ and $2.00, counted in cents so nothing drifts.
const CAP_MIN = 10, CAP_MAX = 200, CAP_STEP = 10

function Switch({ on, label, disabled, onToggle }: { on: boolean; label: string; disabled?: boolean; onToggle?: () => void }) {
  return (
    <button
      type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={onToggle}
      className={cn('relative h-[26px] w-[46px] shrink-0 rounded-full border-[1.5px] p-0 transition-colors', on ? 'border-ink bg-volt' : 'border-foreground bg-sunk', disabled && 'cursor-not-allowed opacity-55')}
    >
      <span aria-hidden="true" className={cn('absolute top-0.5 left-0.5 block size-[19px] rounded-full transition-transform', on ? 'translate-x-5 bg-ink' : 'bg-foreground')} />
    </button>
  )
}

const Row = ({ title, desc, children, tone }: { title: string; desc: string; children: ReactNode; tone?: 'danger' }) => (
  <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-5 border-t border-line py-3.5">
    <div><div className={cn('font-semibold', tone === 'danger' && 'text-destructive')}>{title}</div><div className="text-[13px] text-muted-foreground">{desc}</div></div>
    {children}
  </div>
)

/** Your defaults for new projects, the look, and the account. Every change saves at once. */
export function SettingsPage({ me, onSignedOut }: SettingsPageProps) {
  const safetyOn = useFlags().enabled('golive.g6')   // G6: your data, the policies
  const [settings, setSettings] = useState<UserSettings | null>(null)
  const [projectCap, setProjectCap] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [theme, setTheme] = useTheme()
  const [section, setSection] = useState<SideSection>('agent')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState<'out' | 'delete' | null>(null)
  const [accountError, setAccountError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    getUserSettings().then((s) => { if (live) setSettings(s) }).catch((e) => { if (live) setLoadError(said(e, 'Your settings could not be read.')) })
    getUsageReport('month').then((r) => { if (live) setProjectCap(r.project_cap_usd) }).catch(() => { /* the row is left out */ })
    return () => { live = false }
  }, [])
  useEffect(() => () => { if (savedTimer.current) clearTimeout(savedTimer.current) }, [])

  const save = async (change: Partial<UserSettings>) => {
    if (!settings) return
    const before = settings
    setSettings({ ...settings, ...change })
    setSaveError(null)
    try {
      setSettings(await updateUserSettings(change))
      setSaved(true)
      if (savedTimer.current) clearTimeout(savedTimer.current)
      savedTimer.current = setTimeout(() => setSaved(false), 1800)
    } catch (e) {
      setSettings(before)
      setSaveError(said(e, 'That change did not save.'))
    }
  }
  const cents = settings ? Math.round(settings.turn_usd * 100) : CAP_MIN
  const setCap = (c: number) => void save({ turn_usd: Math.min(CAP_MAX, Math.max(CAP_MIN, c)) / 100 })
  const toggleAsk = (k: keyof AskBefore) => { if (settings) void save({ ask_before: { ...settings.ask_before, [k]: !settings.ask_before[k] } }) }

  const jump = (id: SideSection) => {
    setSection(id)
    const el = document.getElementById(id)
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    el?.focus({ preventScroll: true })
  }
  const signOut = async () => {
    setBusy('out')
    try { await logout() } catch { /* the cookie is gone either way */ }
    finally { setBusy(null) }
    onSignedOut()
    go({ page: 'projects' })
  }
  const deleteAll = async () => {
    if (typed !== 'DELETE') return
    setBusy('delete'); setAccountError(null)
    try {
      await deleteAccount()
      onSignedOut()
      go({ page: 'projects' })
    } catch (e) { setAccountError(said(e, 'Nothing was deleted.')); setBusy(null) }
  }

  const who = me?.user
  const displayName = who?.name ?? who?.email ?? 'Local'
  const signedWith = me?.mode === 'google' ? 'Signed in with Google' : 'Local, sign-in is off'
  const sect = 'rise flex scroll-mt-6 flex-col gap-[18px] border-b-[1.5px] border-line pb-9'

  return (
    <Shell active="settings" me={me} mainClassName="mx-auto flex w-full max-w-[1100px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active={section} onSection={jump} />
      <div className="flex min-w-0 flex-1 flex-col gap-9">
        <h1 className="disp rise m-0 text-[56px] leading-none font-bold">Settings</h1>

        <section id="agent" tabIndex={-1} className={cn(sect, 'outline-none')} aria-labelledby="agent-h" aria-busy={!settings && !loadError ? true : undefined}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex flex-col gap-1">
              <h2 id="agent-h" className="disp m-0 text-[26px] font-bold">What Voltage may do</h2>
              <span className="text-muted-foreground">Your defaults for new projects. Each project can change them from its header.</span>
            </div>
            <span role="status" aria-live="polite" className="tag min-h-5 text-faint">{saved ? 'Saved' : !settings && !loadError ? 'Loading your settings…' : ''}</span>
          </div>
          {loadError && <p className="m-0 text-sm text-destructive" role="alert">{loadError}</p>}
          {saveError && <p className="m-0 text-sm text-destructive" role="alert">{saveError}</p>}

          <div role="radiogroup" aria-label="Autonomy" className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
            {AUTOS.map((a) => {
              const on = settings?.autonomy === a.key
              return (
                <button
                  key={a.key} type="button" role="radio" aria-checked={on} disabled={!settings}
                  className={cn('flex flex-col gap-2 rounded-xl border-[1.5px] p-[18px] text-left transition-all duration-150', on ? 'border-ink bg-volt text-ink shadow-ink -translate-x-0.5 -translate-y-0.5' : 'border-line2 bg-card text-foreground hover:border-foreground')}
                  onClick={() => { if (!on) void save({ autonomy: a.key }) }}
                >
                  <span className="tag">{a.tag}</span>
                  <span className="disp text-[22px] font-bold">{a.title}</span>
                  <span className="text-sm opacity-80">{a.desc}</span>
                </button>
              )
            })}
          </div>

          <div className="flex flex-col">
            <Row title="Money per turn" desc="Voltage stops and asks before a turn spends more than this.">
              <div className="flex items-center gap-2.5">
                <button type="button" className="size-9 rounded-lg border-[1.5px] border-foreground text-lg disabled:opacity-50" aria-label="Lower the turn cap" disabled={!settings || cents <= CAP_MIN} onClick={() => setCap(cents - CAP_STEP)}>−</button>
                <span key={cents} className="tnum inline-block min-w-16 animate-[pop_.3s_ease] text-center text-xl font-semibold" data-testid="turn-cap">{settings ? usd(cents / 100) : '…'}</span>
                <button type="button" className="size-9 rounded-lg border-[1.5px] border-foreground text-lg disabled:opacity-50" aria-label="Raise the turn cap" disabled={!settings || cents >= CAP_MAX} onClick={() => setCap(cents + CAP_STEP)}>+</button>
              </div>
            </Row>
            {projectCap !== null && (
              <Row title="Project ceiling" desc="No project spends past this. Set by your plan.">
                <span className="tnum text-xl font-semibold">{usd(projectCap)}</span>
              </Row>
            )}
            <Row title="How hard Voltage thinks" desc="Higher is slower and costs more, but handles hard videos better.">
              <div role="group" aria-label="Effort" className="segs">
                {EFFORTS.map((e) => (
                  <button key={e.key} type="button" className="seg" aria-pressed={settings?.effort === e.key} disabled={!settings} onClick={() => { if (settings?.effort !== e.key) void save({ effort: e.key }) }}>{e.label}</button>
                ))}
              </div>
            </Row>
          </div>

          <div className="flex flex-col">
            <span className="tag pb-2 text-faint">Under Just do it, still ask before</span>
            {ASKS.map((k) => (
              <Row key={k.key} title={k.label} desc={k.desc}>
                <Switch on={settings?.ask_before[k.key] ?? false} label={k.label} disabled={!settings} onToggle={() => toggleAsk(k.key)} />
              </Row>
            ))}
            <Row title="Deleting a voice" desc="Always asks">
              <Switch on label="Deleting a voice" disabled />
            </Row>
          </div>
        </section>

        <section id="look" tabIndex={-1} className={cn(sect, 'outline-none')} aria-labelledby="look-h">
          <h2 id="look-h" className="disp m-0 text-[26px] font-bold">Appearance</h2>
          <div role="group" aria-label="Theme" className="segs self-start">
            {THEMES.map((t) => (
              <button key={t.key} type="button" className="seg" aria-pressed={theme === t.key} onClick={() => setTheme(t.key)}>{t.label}</button>
            ))}
          </div>
        </section>

        <section id="account" tabIndex={-1} className={cn(sect, 'border-b-0 outline-none')} aria-labelledby="acc-h">
          <h2 id="acc-h" className="disp m-0 text-[26px] font-bold">Account</h2>
          <div className="flex flex-wrap items-center gap-4">
            <span className="disp grid size-14 place-items-center rounded-full border-[1.5px] border-ink bg-volt text-[22px] font-bold text-ink" aria-hidden="true">{initialOf(me)}</span>
            <div className="flex flex-[1_1_200px] flex-col"><span className="text-base font-semibold">{displayName}</span><span className="tnum text-[13px] text-muted-foreground">{signedWith}</span></div>
            {me && me.mode !== 'off' && who && <button type="button" className="btn sm" onClick={() => void signOut()} disabled={busy !== null}>{busy === 'out' ? 'Signing out…' : 'Sign out'}</button>}
          </div>
          {who?.provider === 'acct' && <ChangeEmail current={who.email ?? ''} />}
          {safetyOn && (
            <div className="flex flex-col gap-2 border-t border-line pt-4" aria-labelledby="data-h">
              <h3 id="data-h" className="m-0 text-sm font-semibold">Your data</h3>
              <YourData onDelete={() => { setConfirmDelete(true); document.getElementById('account')?.scrollIntoView({ block: 'end' }) }} />
            </div>
          )}
          <Row title="Delete everything" desc="Every project, take and voice, and the consent records with them. This can't be undone." tone="danger">
            {!confirmDelete && <button type="button" className="btn sm border-destructive text-destructive" onClick={() => setConfirmDelete(true)}>Delete…</button>}
          </Row>
          {confirmDelete && (
            <div className="flex flex-col gap-3 rounded-xl border-[1.5px] border-destructive bg-card p-4" role="group" aria-label="Delete everything?">
              <label htmlFor="confirm-delete" className="text-sm">Type <strong className="tnum font-semibold">DELETE</strong> to confirm. Everything of yours goes, for good.</label>
              <div className="flex flex-wrap gap-2">
                <input id="confirm-delete" className="h-9 rounded-lg border-[1.5px] border-foreground bg-background px-3 font-mono text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoFocus />
                <button type="button" className="btn sm border-destructive text-destructive" disabled={typed !== 'DELETE' || busy !== null} onClick={() => void deleteAll()}>{busy === 'delete' ? 'Deleting…' : 'Delete everything'}</button>
                <button type="button" className="btn sm" onClick={() => { setConfirmDelete(false); setTyped('') }} disabled={busy === 'delete'}>Cancel</button>
              </div>
              {accountError && <p className="m-0 text-sm text-destructive" role="alert">{accountError}</p>}
            </div>
          )}
          {safetyOn && <LegalLinks className="pt-2" />}
        </section>
      </div>
    </Shell>
  )
}

/** Launch item 5: a new address, confirmed by a link sent to it (the old one is told). */
function ChangeEmail({ current }: { current: string }) {
  const [open, setOpen] = useState(false)
  const [address, setAddress] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState<string | null>(null)
  const field = 'box-border h-10 min-w-0 rounded-lg border-[1.5px] border-foreground bg-card px-2.5 text-base text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-volt'
  const send = async () => {
    setBusy(true)
    setError(null)
    try { setSent((await changeEmail(address.trim(), password)).message); setOpen(false); setPassword('') } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The link could not be sent.')
    } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-4" data-testid="change-email">
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 flex-1 text-sm">Email <span className="tnum text-muted-foreground">{current}</span></span>
        {!open && <button type="button" className="btn sm" onClick={() => { setOpen(true); setSent(null) }}>Change email</button>}
      </div>
      {sent && <p className="m-0 text-sm" role="status">{sent}</p>}
      {open && (
        <form className="flex flex-col gap-2.5" aria-label="Change email" onSubmit={(e) => { e.preventDefault(); void send() }}>
          <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">New email</span>
            <input className={field} type="email" autoComplete="email" value={address} onChange={(e) => setAddress(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">Your password</span>
            <input className={field} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <span className="text-[13px] text-destructive" role="alert">{error}</span>}
          <div className="flex gap-2">
            <button type="button" className="btn sm" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
            <button type="submit" className="btn volt sm" disabled={!address.trim() || !password || busy} aria-busy={busy || undefined}>{busy ? 'Sending…' : 'Send the link'}</button>
          </div>
        </form>
      )}
    </div>
  )
}
