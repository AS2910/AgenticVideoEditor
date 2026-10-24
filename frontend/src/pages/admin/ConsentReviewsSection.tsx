import { useCallback, useEffect, useState } from 'react'
import type { ConsentReview } from '../../api'
import { consentRecordingUrl, consentSourceUrl, decideConsentReview, listConsentReviews } from '../../api'
import { formatDate } from '../../lib/dates'
import { hrefFor } from '../../lib/route'
import { cn } from '@/lib/utils'
import { said } from '../fmt'
import { field } from './ui'

const num = (x: number | null, digits = 2) => (x == null ? 'not measured' : x.toFixed(digits))

/** Run 4 item 2: consent checks that were close, waiting for a person. Listen to the
 *  recording and the speaker in the video, read what was heard, then approve or reject with
 *  a reason (kept in the audit trail; the owner is told). Oldest first. */
export function ConsentReviewsSection({ card }: { card: string }) {
  const [show, setShow] = useState<'review' | 'decided'>('review')
  const [items, setItems] = useState<ConsentReview[] | null>(null)
  const [waiting, setWaiting] = useState<number | null>(null)
  const [unread, setUnread] = useState(false)
  const load = useCallback(() => {
    setUnread(false)
    listConsentReviews(show).then((r) => { if (Array.isArray(r?.items)) { setItems(r.items); setWaiting(r.waiting) } })
      .catch(() => setUnread(true))
  }, [show])
  useEffect(load, [load])
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="consent-h" data-testid="admin-consent-reviews">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id="consent-h" className="disp m-0 text-[22px] font-bold">Consent reviews</h2>
        <span className="tag text-faint">read-aloud checks that were close, oldest first</span>
      </div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
        <button type="button" className={cn('pill', show === 'review' && 'on')} aria-pressed={show === 'review'} onClick={() => setShow('review')}>
          Waiting{waiting != null ? ` · ${waiting}` : ''}
        </button>
        <button type="button" className={cn('pill', show === 'decided' && 'on')} aria-pressed={show === 'decided'} onClick={() => setShow('decided')}>Decided</button>
      </div>
      {unread && <p className="m-0 text-sm text-muted-foreground">The queue could not be read.</p>}
      {items && items.length === 0 && <p className="m-0 text-muted-foreground">{show === 'review' ? 'Nothing waiting.' : 'Nothing decided yet.'}</p>}
      {items && items.map((r) => <ReviewRow key={r.id} r={r} onDone={load} />)}
    </section>
  )
}

function ReviewRow({ r, onDone }: { r: ConsentReview; onDone: () => void }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const decide = async (decision: 'approve' | 'reject') => {
    setBusy(decision); setError(null)
    try { await decideConsentReview(r.id, decision, reason.trim()); onDone() } catch (e) { setError(said(e, 'That did not save.')) } finally { setBusy(null) }
  }
  const open = r.status === 'review'
  return (
    <article className="flex flex-col gap-2 border-t border-line py-3 text-[13px]" data-testid="consent-review" aria-label={`Consent check ${r.id}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={open ? 'stamp need' : r.status === 'passed' ? 'stamp' : 'stamp inkd'}>{open ? 'Waiting' : r.status === 'passed' ? 'Approved' : 'Rejected'}</span>
        <span className="tnum text-muted-foreground">{formatDate(r.created_at)} · {r.owner} · <a href={hrefFor({ page: 'editor', projectId: r.video_id })} className="underline">video {r.video_id}</a>{r.speaker ? ` · ${r.speaker}` : ''}</span>
      </div>
      <p className="m-0"><span className="tag text-faint">Phrase</span> <span className="text-sm">{r.sentence}</span></p>
      <p className="m-0"><span className="tag text-faint">Heard</span> <span className="text-sm">{r.heard ?? 'not heard (no transcriber)'}</span></p>
      <p className="tnum m-0 text-muted-foreground">
        Voice match {num(r.similarity)} (passes at {num(r.pass_at)}, review from {num(r.review_from)}) · word errors {r.wer == null ? 'not measured' : `${Math.round(r.wer * 100)}%`} · {num(r.seconds, 1)} s
      </p>
      <p className="m-0 text-muted-foreground">{r.reason}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-1"><span className="font-semibold">The recording</span>
          {r.has_recording ? <audio controls preload="none" src={consentRecordingUrl(r.id)} className="w-full" aria-label="The consent recording" /> : <span className="text-muted-foreground">Not kept.</span>}
        </div>
        <div className="flex min-w-0 flex-col gap-1"><span className="font-semibold">The speaker in the video</span>
          <audio controls preload="none" src={consentSourceUrl(r.id)} className="w-full" aria-label="The speaker in the video" />
        </div>
      </div>
      <span className="truncate text-faint" title={`${r.asr_model} · ${r.speaker_model}`}>{r.asr_model || 'no transcriber'} · {r.speaker_model}</span>
      {open ? (
        <div className="flex flex-wrap items-end gap-2.5">
          <label className="flex min-w-0 flex-[1_1_220px] flex-col gap-1"><span className="font-semibold">Why</span>
            <input className={field} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="kept in the audit trail" />
          </label>
          <button type="button" className="btn ink sm" disabled={!!busy || reason.trim().length < 3} onClick={() => void decide('reject')}>{busy === 'reject' ? 'Rejecting…' : 'Reject'}</button>
          <button type="button" className="btn volt sm" disabled={!!busy || reason.trim().length < 3} onClick={() => void decide('approve')}>{busy === 'approve' ? 'Approving…' : 'Approve'}</button>
        </div>
      ) : (
        <p className="m-0">{r.reviewed_by} {r.reviewed_at ? formatDate(r.reviewed_at) : ''}: {r.review_reason}</p>
      )}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
    </article>
  )
}
