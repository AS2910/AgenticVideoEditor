import { useCallback, useEffect, useState } from 'react'
import type { AdminAnalytics } from '../types'
import type { Me } from '../api'
import { getAdminAnalytics } from '../api'
import { track } from '../lib/analytics'
import { usd } from '../lib/money'
import { Shell, SideNav } from './Shell'
import { FillBar } from './bits'
import { said } from './fmt'

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
    getAdminAnalytics().then(setData).catch((e) => setError(said(e, 'The numbers could not be read.')))
  }, [])
  useEffect(() => { load(); track('admin.opened') }, [load])
  const card = 'rounded-xl border-[1.5px] border-foreground bg-card p-[22px]'
  const top = data?.funnel[0]?.owners ?? 0

  return (
    <Shell active="settings" me={me} mainClassName="mx-auto flex w-full max-w-[1100px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active="admin" />
      <div className="flex min-w-0 flex-1 flex-col gap-[22px]" data-testid="admin-page">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="disp rise m-0 text-[56px] leading-none font-bold">Admin</h1>
          <span className="stamp quiet">Internal</span>
        </div>
        <p className="m-0 max-w-[640px] text-muted-foreground">How people move from signing up to their first export, and what it costs. Only admins see this page.</p>
        {error && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {error}<button type="button" className="btn sm" onClick={load}>Try again</button>
          </div>
        )}
        {!error && !data && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Adding up…</p>}
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
