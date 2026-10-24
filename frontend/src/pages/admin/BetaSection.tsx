import { useCallback, useEffect, useState } from 'react'
import type { BetaView } from '../../api'
import { getAdminBeta, joinBeta } from '../../api'
import { formatDate } from '../../lib/dates'
import { usd } from '../../lib/money'
import { said } from '../fmt'
import { field } from './ui'

const USEFUL: Record<string, string> = { very: 'Very useful', somewhat: 'Somewhat useful', not: 'Not useful' }
const PAY: Record<string, string> = { yes: 'Would pay', maybe: 'Maybe pay', no: 'Would not pay' }

/** Beta kit: everyone in the beta cohort, newest first: last active, exports, spend, the credits
 *  given, what they told us (Send feedback and the three questions) and their error reports.
 *  Add to beta puts someone in (by address or owner id): flags on, credits once, the beta email. */
export function BetaSection({ card }: { card: string }) {
  const [view, setView] = useState<BetaView | null>(null)
  const [unread, setUnread] = useState(false)
  const [who, setWho] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const load = useCallback(() => {
    setUnread(false)
    getAdminBeta().then((v) => { if (Array.isArray(v?.people)) setView(v) }).catch(() => setUnread(true))
  }, [])
  useEffect(load, [load])
  const add = async () => {
    setBusy(true); setError(null); setDone(null)
    try {
      const r = await joinBeta(who.trim())
      setDone(r.joined
        ? `${r.owner} is in the beta${r.granted ? `, with ${r.credits} credits` : ''}${r.emailed ? '. The beta email went.' : '.'}`
        : `${r.owner} was in the beta already.`)
      setWho('')
      load()
    } catch (e) { setError(said(e, 'They could not be added.')) } finally { setBusy(false) }
  }
  const s = view?.survey
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="beta-view-h" data-testid="admin-beta">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id="beta-view-h" className="disp m-0 text-[22px] font-bold">Beta</h2>
        {view && <span className="tag text-faint">{view.people.length} in the cohort · {view.credits_each} credits each</span>}
      </div>
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (who.trim()) void add() }}>
        <label className="sr-only" htmlFor="beta-who">Address or owner id</label>
        <input id="beta-who" className={`${field} flex-[1_1_260px]`} placeholder="ann@example.com or acct:…" value={who} onChange={(e) => setWho(e.target.value)} autoComplete="off" />
        <button type="submit" className="btn volt sm" disabled={busy || !who.trim()}>{busy ? 'Adding…' : 'Add to beta'}</button>
      </form>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {done && <p className="m-0 text-sm" role="status">{done}</p>}
      {unread && <p className="m-0 text-sm text-muted-foreground">The beta could not be read.</p>}
      {s && s.answered > 0 && (
        <p className="m-0 text-[13px] text-muted-foreground" data-testid="beta-answers">
          {s.answered} of {s.shown} answered the three questions: {Object.entries(s.useful).map(([k, n]) => `${n} ${USEFUL[k].toLowerCase()}`).join(', ')}; {Object.entries(s.would_pay).map(([k, n]) => `${n} ${PAY[k].toLowerCase()}`).join(', ')}.
        </p>
      )}
      {view && view.people.length === 0 && <p className="m-0 text-muted-foreground">Nobody is in the beta yet.</p>}
      {view && view.people.map((p) => (
        <article key={p.owner} className="flex flex-col gap-1.5 border-t border-line py-2.5 text-[13px]" data-testid="beta-person" aria-label={p.emails[0] ?? p.owner}>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-sm font-medium break-all">{p.emails[0] ?? p.owner}</span>
            <span className="tnum text-faint">since {formatDate(p.since)} · last active {p.last_active ? formatDate(p.last_active) : 'not yet'}</span>
          </div>
          <div className="tnum flex flex-wrap gap-x-4 gap-y-1">
            <span>{p.exports} {p.exports === 1 ? 'export' : 'exports'}</span>
            <span>{usd(p.spend_usd)} spent</span>
            <span>{p.credits_given} credits given</span>
            <span>{p.feedback.messages} {p.feedback.messages === 1 ? 'message' : 'messages'}</span>
            <span className={p.errors.count ? 'text-destructive' : undefined}>{p.errors.count} {p.errors.count === 1 ? 'error' : 'errors'}</span>
          </div>
          {p.survey?.answered_at && (
            <span className="text-muted-foreground [overflow-wrap:anywhere]">
              {USEFUL[p.survey.useful ?? ''] ?? ''} · {PAY[p.survey.would_pay ?? ''] ?? ''}{p.survey.almost_stopped ? ` · almost stopped by: “${p.survey.almost_stopped}”` : ''}
            </span>
          )}
          {p.survey && !p.survey.answered_at && <span className="text-faint">Shown the questions, not answered.</span>}
          {p.feedback.latest && <span className="text-muted-foreground [overflow-wrap:anywhere]">Latest message: {p.feedback.latest}</span>}
          {p.errors.latest && <span className="text-muted-foreground [overflow-wrap:anywhere]">Latest error: {p.errors.latest}</span>}
        </article>
      ))}
    </section>
  )
}
