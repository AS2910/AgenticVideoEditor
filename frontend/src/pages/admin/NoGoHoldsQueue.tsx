import { useCallback, useEffect, useState } from 'react'
import { formatDate } from '../../lib/dates'
import { hrefFor } from '../../lib/route'
import { cn } from '@/lib/utils'
import { said } from '../fmt'
import type { NoGoHold } from './noGoApi'
import { decideNoGoHold, listNoGoHolds, noGoHoldAudioUrl } from './noGoApi'
import { field } from './ui'

const num = (x: number | null) => (x == null ? 'not measured' : x.toFixed(2))
const STAMP: Record<NoGoHold['status'], [string, string]> = {
  waiting: ['stamp need', 'Waiting'], approved: ['stamp', 'Approved'], rejected: ['stamp inkd', 'Rejected'], closed: ['stamp quiet', 'Closed'],
}

/** Voice consent V1, step 5: clones that sound close to a no-go voice (0.84 to 0.92), or that
 *  could not be measured, waiting for a person. Listen, then approve (the clone goes ahead the
 *  next time it is tried) or reject (it is blocked), with a reason for the audit trail. The
 *  person is told either way. Oldest first. A part of the Voice safety tab. */
export function NoGoHoldsQueue() {
  const [show, setShow] = useState<'waiting' | 'decided'>('waiting')
  const [items, setItems] = useState<NoGoHold[] | null>(null)
  const [waiting, setWaiting] = useState<number | null>(null)
  const [unread, setUnread] = useState(false)
  const load = useCallback(() => {
    setUnread(false)
    listNoGoHolds(show).then((r) => { if (Array.isArray(r?.items)) { setItems(r.items); setWaiting(r.waiting) } })
      .catch(() => setUnread(true))
  }, [show])
  useEffect(load, [load])
  return (
    <section className="flex flex-col gap-3" aria-labelledby="nogo-holds-h" data-testid="admin-no-go-holds">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h3 id="nogo-holds-h" className="disp m-0 text-[18px] font-bold">Close to a no-go voice</h3>
        <span className="tag text-faint">clones waiting for a person, oldest first</span>
      </div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
        <button type="button" className={cn('pill', show === 'waiting' && 'on')} aria-pressed={show === 'waiting'} onClick={() => setShow('waiting')}>
          Waiting{waiting != null ? ` · ${waiting}` : ''}
        </button>
        <button type="button" className={cn('pill', show === 'decided' && 'on')} aria-pressed={show === 'decided'} onClick={() => setShow('decided')}>Decided</button>
      </div>
      {unread && <p className="m-0 text-sm text-muted-foreground">The queue could not be read.</p>}
      {!unread && !items && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading the queue…</p>}
      {items && items.length === 0 && <p className="m-0 text-muted-foreground">{show === 'waiting' ? 'Nothing waiting.' : 'Nothing decided yet.'}</p>}
      {items && items.map((h) => <HoldRow key={h.id} h={h} onDone={load} />)}
    </section>
  )
}

function HoldRow({ h, onDone }: { h: NoGoHold; onDone: () => void }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const decide = async (decision: 'approve' | 'reject') => {
    setBusy(decision); setError(null)
    try { await decideNoGoHold(h.id, decision, reason.trim()); onDone() } catch (e) { setError(said(e, 'That did not save.')) } finally { setBusy(null) }
  }
  const open = h.status === 'waiting'
  const [stamp, word] = STAMP[h.status] ?? STAMP.closed
  const who = h.speaker_name || (h.speaker_label && h.speaker_label !== '_' ? `Speaker ${h.speaker_label}` : 'the speaker')
  const ready = reason.trim().length >= 3
  return (
    <article className="flex flex-col gap-2 border-t border-line py-3 text-[13px]" data-testid="no-go-hold" aria-label={`Held clone ${h.id}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={stamp}>{word}</span>
        <span className="tnum min-w-0 text-muted-foreground [overflow-wrap:anywhere]">
          {formatDate(h.created_at)} · {h.owner}
          {h.video_id && <> · <a href={hrefFor({ page: 'editor', projectId: h.video_id })} className="underline">video {h.video_id}</a></>}
          {' · '}{who}
        </span>
      </div>
      <p className="m-0">
        {h.no_go_id
          ? <><span className="tag text-faint">Close to</span> <span className="text-sm font-medium">{h.no_go_name ?? h.no_go_id}</span></>
          : <span className="text-sm">The voice could not be measured here, so a person listens.</span>}
      </p>
      <p className="tnum m-0 text-muted-foreground">Voice match {num(h.score)} (blocked at {num(h.block_at)}, review from {num(h.review_from)})</p>
      <div className="flex min-w-0 flex-col gap-1"><span className="font-semibold">The voice being cloned</span>
        {open && h.has_audio
          ? <audio controls preload="none" src={noGoHoldAudioUrl(h.id)} className="w-full" aria-label={`The voice being cloned: ${who}`} />
          : <span className="text-muted-foreground">{open ? 'Not kept.' : 'Deleted once decided.'}</span>}
      </div>
      {open ? (
        <div className="flex flex-wrap items-end gap-2.5">
          <label className="flex min-w-0 flex-[1_1_220px] flex-col gap-1"><span className="font-semibold">Why</span>
            <input className={field} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="kept in the audit trail" />
          </label>
          <button type="button" className="btn ink sm" disabled={!!busy || !ready} onClick={() => void decide('reject')}>{busy === 'reject' ? 'Rejecting…' : 'Reject'}</button>
          <button type="button" className="btn volt sm" disabled={!!busy || !ready} onClick={() => void decide('approve')}>{busy === 'approve' ? 'Approving…' : 'Approve'}</button>
        </div>
      ) : (
        <p className="m-0 [overflow-wrap:anywhere]">{h.decided_by} {h.decided_at ? formatDate(h.decided_at) : ''}: {h.reason}</p>
      )}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
    </article>
  )
}
