import { useCallback, useEffect, useState } from 'react'
import type { BetaFeedbackItem, BetaStatus } from '../../api'
import { betaScreenshotUrl, listBetaFeedback, setBetaFeedbackStatus } from '../../api'
import { formatDate } from '../../lib/dates'
import { hrefFor } from '../../lib/route'
import { cn } from '@/lib/utils'
import { said } from '../fmt'

const STATUSES: BetaStatus[] = ['new', 'seen', 'done']
const WORD: Record<BetaStatus, string> = { new: 'New', seen: 'Seen', done: 'Done' }

/** Rehearsal item 11: what people sent with "Send feedback", newest first, with a status to move. */
export function BetaFeedbackSection({ card }: { card: string }) {
  const [filter, setFilter] = useState<BetaStatus | null>('new')
  const [items, setItems] = useState<BetaFeedbackItem[] | null>(null)
  const [counts, setCounts] = useState<Record<BetaStatus, number> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [unread, setUnread] = useState(false)
  const load = useCallback(() => {
    setError(null); setUnread(false)
    listBetaFeedback(filter ?? undefined).then((r) => { if (Array.isArray(r?.items)) { setItems(r.items); setCounts(r.counts) } })
      .catch(() => setUnread(true))
  }, [filter])
  useEffect(load, [load])
  const move = async (id: number, status: BetaStatus) => {
    setBusy(id); setError(null)
    try { await setBetaFeedbackStatus(id, status); load() } catch (e) { setError(said(e, 'The status did not change.')) } finally { setBusy(null) }
  }
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="beta-h" data-testid="admin-beta-feedback">
      <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="beta-h" className="disp m-0 text-[22px] font-bold">Beta feedback</h2><span className="tag text-faint">from Send feedback, newest first</span></div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
        {([null, ...STATUSES] as (BetaStatus | null)[]).map((s) => (
          <button key={s ?? 'all'} type="button" className={cn('pill', filter === s && 'on')} aria-pressed={filter === s} onClick={() => setFilter(s)}>
            {s ? WORD[s] : 'All'}{s && counts ? ` · ${counts[s]}` : ''}
          </button>
        ))}
      </div>
      {unread && <p className="m-0 text-sm text-muted-foreground">Feedback could not be read.</p>}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {items && items.length === 0 && <p className="m-0 text-muted-foreground">Nothing here.</p>}
      {items && items.map((f) => (
        <article key={f.id} className="flex flex-col gap-1.5 border-t border-line py-2.5 text-[13px]" data-testid="beta-row" aria-label={`Message ${f.id}`}>
          <div className="flex flex-wrap items-baseline gap-2">
            <span className={f.status === 'new' ? 'stamp need' : f.status === 'seen' ? 'stamp' : 'stamp quiet'}>{WORD[f.status]}</span>
            <span className="tnum text-muted-foreground">#{f.id} · {formatDate(f.created_at)} · {f.owner}</span>
          </div>
          <p className="m-0 text-sm [overflow-wrap:anywhere] whitespace-pre-wrap">{f.message}</p>
          <span className="tnum text-muted-foreground [overflow-wrap:anywhere]">
            {f.route || 'no route'}
            {f.video_id && <> · <a href={hrefFor({ page: 'editor', projectId: f.video_id })} className="underline">video {f.video_id}</a></>}
            {f.job_id && <> · job {f.job_id}</>}
            {f.app_version && <> · {f.app_version}</>}
          </span>
          {f.user_agent && <span className="truncate text-faint" title={f.user_agent}>{f.user_agent}</span>}
          <div className="flex flex-wrap items-center gap-2">
            {f.screenshot && <a className="act" href={betaScreenshotUrl(f.id)} target="_blank" rel="noreferrer">Open the screenshot</a>}
            <span className="flex-1" />
            {STATUSES.filter((s) => s !== f.status).map((s) => (
              <button key={s} type="button" className="btn sm" disabled={busy === f.id} onClick={() => void move(f.id, s)}>Mark {WORD[s].toLowerCase()}</button>
            ))}
          </div>
        </article>
      ))}
    </section>
  )
}
