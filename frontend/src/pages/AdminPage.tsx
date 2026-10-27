import { useCallback, useEffect, useState } from 'react'
import type { AdminAnalytics } from '../types'
import type { Me } from '../api'
import { getAdminAnalytics, getAdminFlags, getAdminSpend, setAdminFlag, setPaidPause } from '../api'
import type { AdminFlags, AdminSpend } from '../api'
import { track } from '../lib/analytics'
import { usd } from '../lib/money'
import { Shell, SideNav } from './Shell'
import { FillBar } from './bits'
import { said } from './fmt'
import { PeopleSection } from './admin/PeopleSection'
import { ADMIN_SECTIONS } from './admin/sections'

const pct = (n: number | null) => (n == null ? null : `${Math.round(n * 100)}%`)

/** G7 (golive.g7): the internal admin page, for the owners in AVE_ADMIN_OWNERS only.
 *  The funnel from sign-up to first export, take acceptance (added over voiced), cost per
 *  exported minute (the ledger over exported minutes), SIM-o and UTMOS per vendor where they
 *  were measured, and every event's count. A number with nothing under it says so instead. */
export function AdminPage({ me }: { me: Me | null }) {
  const [data, setData] = useState<AdminAnalytics | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => {
    setError(null)
    getAdminAnalytics().then((d) => setData(Array.isArray(d?.funnel) ? d : null)).catch((e) => setError(said(e, 'The numbers could not be read.')))
  }, [])
  useEffect(() => { load(); track('admin.opened') }, [load])
  const card = 'rounded-xl border-[1.5px] border-foreground bg-card p-[22px]'
  // Item 10: the user view's "Features for this person" opens the flags card on them.
  const [flagsFor, setFlagsFor] = useState<{ owner: string; n: number } | null>(null)
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ block: 'start' })
  const JUMPS = [{ id: 'admin-spend-s', label: 'Spend today' }, { id: 'admin-people-s', label: 'People' }, { id: 'admin-flags-s', label: 'Features' },
    ...ADMIN_SECTIONS.map((x) => ({ id: `admin-${x.id}-s`, label: x.label, href: x.href })), { id: 'admin-numbers-s', label: 'Numbers' }]
  const top = data?.funnel[0]?.owners ?? 0

  return (
    <Shell active="settings" me={me} mainClassName="mx-auto flex w-full max-w-[1100px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active="admin" />
      <div className="flex min-w-0 flex-1 flex-col gap-[22px]" data-testid="admin-page">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="disp rise m-0 text-[56px] leading-none font-bold">Admin</h1>
          <span className="stamp quiet">Internal</span>
        </div>
        <p className="m-0 max-w-[640px] text-muted-foreground">Launch day tools: spend and the kill switch, one person's account, and every admin action. Then how people move from signing up to their first export. Only admins see this page.</p>
        <nav aria-label="Admin sections" className="flex flex-wrap gap-1.5">
          {JUMPS.map((j) => ('href' in j && j.href)
            ? <a key={j.id} href={j.href} className="act">{j.label}</a>
            : <button key={j.id} type="button" className="act" onClick={() => jump(j.id)}>{j.label}</button>)}
        </nav>
        {error && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {error}<button type="button" className="btn sm" onClick={load}>Try again</button>
          </div>
        )}
        {!error && !data && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Adding up…</p>}
        <div id="admin-spend-s" className="scroll-mt-4"><SpendCard card={card} /></div>
        <div id="admin-people-s" className="scroll-mt-4"><PeopleSection card={card} onFlags={(owner) => { setFlagsFor((f) => ({ owner, n: (f?.n ?? 0) + 1 })); window.setTimeout(() => jump('admin-flags-s'), 0) }} /></div>
        <div id="admin-flags-s" className="scroll-mt-4"><FlagsCard card={card} lookFor={flagsFor} /></div>
        {/* Item 10: the mount point. Other admin tools are one entry each in ./admin/sections.tsx. */}
        {ADMIN_SECTIONS.filter((x) => x.render).map((x) => <div key={x.id} id={`admin-${x.id}-s`} className="scroll-mt-4">{x.render?.(card)}</div>)}
        <span id="admin-numbers-s" className="scroll-mt-4" />
        {data && (
          <>
            <section className={`${card} flex flex-col gap-3`} aria-labelledby="funnel-h" data-testid="admin-funnel">
              <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="funnel-h" className="disp m-0 text-[22px] font-bold">Funnel</h2><span className="tag text-faint">people at each step</span></div>
              {top === 0 && <p className="m-0 text-muted-foreground">Nobody has signed up yet.</p>}
              <ol className="m-0 flex list-none flex-col gap-2.5 p-0">
                {data.funnel.map((s, i) => {
                  const prev = i > 0 ? data.funnel[i - 1].owners : null
                  const step = prev ? pct(s.owners / prev) : null
                  return (
                    <li key={s.step} className="grid grid-cols-[minmax(0,200px)_minmax(0,1fr)_48px] items-center gap-3" data-testid="funnel-step">
                      <span className="flex flex-col"><span className="font-medium">{s.label}</span>{step && <span className="text-[12px] text-muted-foreground">{step} of the step before</span>}</span>
                      <FillBar share={s.share ?? 0} height={10} label={`${s.label}: ${s.owners}`} />
                      <span className="tnum text-right text-[13px]">{s.owners}</span>
                    </li>
                  )
                })}
              </ol>
            </section>

            <div className="grid gap-[22px] sm:grid-cols-2">
              <section className={`${card} flex flex-col gap-2`} aria-labelledby="accept-h" data-testid="admin-acceptance">
                <h2 id="accept-h" className="tag m-0 text-faint">Take acceptance</h2>
                <span className="disp text-[30px] font-bold">{pct(data.take_acceptance.rate) ?? 'No takes yet'}</span>
                <span className="text-[13px] text-muted-foreground">{data.take_acceptance.added} added of {data.take_acceptance.voiced} voiced</span>
              </section>
              <section className={`${card} flex flex-col gap-2`} aria-labelledby="cost-h" data-testid="admin-cost">
                <h2 id="cost-h" className="tag m-0 text-faint">Cost per exported minute</h2>
                <span className="disp text-[30px] font-bold">{data.cost_per_exported_minute.per_minute != null ? usd(data.cost_per_exported_minute.per_minute) : 'Nothing exported yet'}</span>
                <span className="text-[13px] text-muted-foreground">{usd(data.cost_per_exported_minute.cost_usd)} spent over {data.cost_per_exported_minute.minutes.toFixed(1)} exported minutes</span>
              </section>
            </div>

            <section className={card} aria-labelledby="quality-h" data-testid="admin-quality">
              <div className="mb-2 flex flex-wrap items-baseline gap-2.5"><h2 id="quality-h" className="disp m-0 text-[22px] font-bold">Voice quality by vendor</h2><span className="tag text-faint">SIM-o and UTMOS, measured takes only</span></div>
              {data.vendor_quality.length === 0 && <p className="m-0 text-muted-foreground">No takes voiced yet.</p>}
              {data.vendor_quality.map((v) => (
                <div key={v.vendor} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-baseline gap-4 border-t border-line py-2.5" data-testid="vendor-row">
                  <span className="font-medium">{v.vendor} <span className="tag text-faint">{v.takes} {v.takes === 1 ? 'take' : 'takes'}</span></span>
                  <span className="tnum text-[13px]">SIM-o {v.sim_o != null ? `${v.sim_o.toFixed(2)} (${v.sim_o_takes})` : 'not measured yet'}</span>
                  <span className="tnum text-[13px]">UTMOS {v.utmos != null ? `${v.utmos.toFixed(2)} (${v.utmos_takes})` : 'not measured yet'}</span>
                </div>
              ))}
            </section>

            {data.feedback && (
              <section className={card} aria-labelledby="fb-h" data-testid="admin-feedback">
                <div className="mb-2 flex flex-wrap items-baseline gap-2.5"><h2 id="fb-h" className="disp m-0 text-[22px] font-bold">Feedback</h2><span className="tag text-faint">thumbs on takes and replies</span></div>
                <div className="flex flex-wrap gap-6">
                  {data.feedback.totals.map((t) => (
                    <span key={t.target} className="tnum text-[13px]"><span className="tag text-faint">{t.target === 'take' ? 'Takes' : 'Replies'}</span> {t.up} up · {t.down} down</span>
                  ))}
                </div>
                {data.feedback.recent.length === 0
                  ? <p className="m-0 mt-2 text-muted-foreground">No feedback yet.</p>
                  : data.feedback.recent.map((f, i) => (
                    <div key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-line py-2 text-[13px]" data-testid="feedback-row">
                      <span className={f.vote === 'up' ? 'stamp in' : 'stamp need'}>{f.vote === 'up' ? 'Up' : 'Down'}</span>
                      <span className="tag text-faint">{f.target} · {f.video_id}</span>
                      <span className="min-w-0 flex-1">{f.reason || <span className="text-muted-foreground">No reason given</span>}</span>
                    </div>
                  ))}
                {data.feedback.errors && (
                  <div className="mt-3 flex flex-col gap-1" data-testid="admin-errors">
                    <span className="tag text-faint">Errors reported · {data.feedback.errors.count}</span>
                    {data.feedback.errors.recent.map((e, i) => (
                      <span key={i} className="truncate text-[13px]" title={e.message}><span className="tag text-faint">{e.source}</span> {e.message}</span>
                    ))}
                  </div>
                )}
              </section>
            )}

            {data.abuse_reports && (
              <section className={card} aria-labelledby="abuse-h" data-testid="admin-abuse">
                <div className="mb-2 flex flex-wrap items-baseline gap-2.5"><h2 id="abuse-h" className="disp m-0 text-[22px] font-bold">Abuse reports</h2><span className="tag text-faint">{data.abuse_reports.length} newest</span></div>
                {data.abuse_reports.length === 0 ? <p className="m-0 text-muted-foreground">No reports.</p> : data.abuse_reports.map((r) => (
                  <div key={r.id} className="flex flex-col gap-0.5 border-t border-line py-2.5 text-[13px]" data-testid="abuse-row">
                    <span className="flex flex-wrap items-baseline gap-2"><span className="stamp need">{r.kind.replace('_', ' ')}</span><span className="tnum min-w-0 truncate">{r.location}</span></span>
                    {r.details && <span>{r.details}</span>}
                    <span className="text-muted-foreground">{r.contact ? `Reply to ${r.contact}` : 'No contact given'}</span>
                  </div>
                ))}
              </section>
            )}

            <section className={card} aria-labelledby="counts-h" data-testid="admin-counts">
              <div className="mb-2 flex flex-wrap items-baseline gap-2.5"><h2 id="counts-h" className="disp m-0 text-[22px] font-bold">Events</h2><span className="tag text-faint">{data.counts.length} names</span></div>
              {data.counts.length === 0 && <p className="m-0 text-muted-foreground">No events yet.</p>}
              {data.counts.map((c) => (
                <div key={`${c.name}:${c.source}`} className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-baseline gap-4 border-t border-line py-2" data-testid="count-row">
                  <span className="tnum min-w-0 truncate text-[13px]">{c.name}</span>
                  <span className="tag text-faint">{c.source}</span>
                  <span className="tnum text-[13px]">{c.count} · {c.owners} {c.owners === 1 ? 'person' : 'people'}</span>
                </div>
              ))}
            </section>
          </>
        )}
      </div>
    </Shell>
  )
}

/** Launch item 3: today's spend across everyone against the day's cap, by
 *  vendor, and the kill switch that pauses new paid work for everyone. */
function SpendCard({ card }: { card: string }) {
  const [spend, setSpend] = useState<AdminSpend | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unread, setUnread] = useState(false)
  useEffect(() => { getAdminSpend().then((v) => { if (typeof v?.today_usd === 'number') setSpend(v) }).catch(() => setUnread(true)) }, [])
  const flip = async () => {
    if (!spend) return
    setBusy(true)
    setError(null)
    try { const v = await setPaidPause(!spend.switch); if (typeof v?.today_usd === 'number') setSpend(v) } catch (e) { setError(said(e, 'The switch did not move.')) } finally { setBusy(false) }
  }
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="spend-h" data-testid="admin-spend">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id="spend-h" className="disp m-0 text-[22px] font-bold">Spend today</h2>
        <span className="tag text-faint">everyone, since midnight UTC</span>
        {spend?.paused && <span className="stamp need">{spend.reason === 'daily_cap' ? 'Paused: day cap reached' : 'Paused'}</span>}
      </div>
      {unread && <p className="m-0 text-sm text-muted-foreground">Today's spend could not be read.</p>}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {spend && (
        <>
          <span className="disp text-[30px] font-bold" data-testid="spend-today">{usd(spend.today_usd)}{spend.cap_usd != null && <span className="text-base font-normal text-muted-foreground"> of {usd(spend.cap_usd)} a day</span>}</span>
          {spend.cap_usd != null && <FillBar share={Math.min(1, spend.today_usd / Math.max(spend.cap_usd, 0.01))} height={10} label="Share of the day's cap" />}
          <span className="text-[13px] text-muted-foreground">
            {Object.keys(spend.by_vendor).length ? Object.entries(spend.by_vendor).map(([v, n]) => `${v} ${usd(n)}`).join(' · ') : 'Nothing spent yet today.'}
          </span>
          <div className="flex flex-wrap items-center gap-3">
            <span className="min-w-0 flex-1 text-sm">{spend.switch ? 'New paid work is paused for everyone. Free steps still work, and everyone sees a short notice.' : 'Pausing stops new paid work for everyone at once; running steps stop at their next paid call.'}</span>
            <button type="button" className={spend.switch ? 'btn volt sm' : 'btn sm'} onClick={() => void flip()} disabled={busy} aria-pressed={spend.switch}>
              {busy ? 'Moving…' : spend.switch ? 'Resume paid work' : 'Pause paid work'}
            </button>
          </div>
        </>
      )}
    </section>
  )
}

const SOURCE_WORDS: Record<AdminFlags['flags'][number]['source'], string> = {
  owner: 'set for them', everyone: 'set for everyone', profile: 'launch profile', default_owner: 'default owner', default: 'on by default', off: 'off by default',
}

/** Launch item 10: turn a feature on or off for one person (their owner id,
 *  e.g. acct:1a2b or google:123), on top of the launch profile. */
function FlagsCard({ card, lookFor = null }: { card: string; lookFor?: { owner: string; n: number } | null }) {
  const [owner, setOwner] = useState('')
  const [view, setView] = useState<AdminFlags | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const act = async (key: string, run: () => Promise<AdminFlags>) => {
    setBusy(key)
    setError(null)
    try { const v = await run(); if (Array.isArray(v?.flags)) setView(v) } catch (e) { setError(said(e, 'That did not work.')) } finally { setBusy(null) }
  }
  useEffect(() => {
    if (!lookFor) return
    setOwner(lookFor.owner)
    void act('look', () => getAdminFlags(lookFor.owner))
  }, [lookFor]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="flags-h" data-testid="admin-flags">
      <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="flags-h" className="disp m-0 text-[22px] font-bold">Features for one person</h2><span className="tag text-faint">on top of the launch profile</span></div>
      <form className="flex flex-wrap items-end gap-2.5" onSubmit={(e) => { e.preventDefault(); if (owner.trim()) void act('look', () => getAdminFlags(owner.trim())) }}>
        <label className="flex min-w-0 flex-[1_1_240px] flex-col gap-1"><span className="text-[13px] font-semibold">Owner id</span>
          <input className="box-border h-10 min-w-0 rounded-lg border-[1.5px] border-foreground bg-card px-2.5 font-mono text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-volt" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="acct:1a2b3c or google:123" />
        </label>
        <button type="submit" className="btn sm" disabled={!owner.trim() || busy !== null}>{busy === 'look' ? 'Looking…' : 'Look up'}</button>
      </form>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {view && (
        <ul className="m-0 flex list-none flex-col p-0">
          {view.flags.map((f) => (
            <li key={f.flag} className="flex flex-wrap items-center gap-3 border-t border-line py-2" data-testid="flag-row">
              <span className="min-w-0 flex-1 font-mono text-sm">{f.flag}</span>
              <span className={f.on ? 'stamp' : 'stamp quiet'}>{f.on ? 'On' : 'Off'}</span>
              <span className="w-32 text-[13px] text-muted-foreground">{SOURCE_WORDS[f.source]}</span>
              <button type="button" className="btn sm" disabled={busy !== null} onClick={() => void act(f.flag, () => setAdminFlag(view.owner, f.flag, !f.on))}>{f.on ? 'Turn off' : 'Turn on'}</button>
              {f.source === 'owner' && <button type="button" className="act" disabled={busy !== null} onClick={() => void act(f.flag, () => setAdminFlag(view.owner, f.flag, null))}>Reset</button>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
