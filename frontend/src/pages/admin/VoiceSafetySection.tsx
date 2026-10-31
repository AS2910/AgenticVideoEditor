import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Tabs as TabsPrimitive } from 'radix-ui'
import { formatDate } from '../../lib/dates'
import { hrefFor } from '../../lib/route'
import { cn } from '@/lib/utils'
import { said } from '../fmt'
import { field } from './ui'
import type { HeldLine } from './voiceSafetyApi'
import { decideHeldLine, listHeldLines } from './voiceSafetyApi'
import { NoGoHoldsQueue } from './NoGoHoldsQueue'
import { NoGoVoicesList } from './NoGoVoicesList'

/** Voice consent V1: the Voice safety tab. One queue per slot; each is an id, its tab label and
 *  what to draw. Step 4 adds held lines, step 5 the borderline no-go matches and the no-go
 *  list; the third queue (borderline own-voice checks) slots in the same way, one line. */
export interface VoiceSafetyQueue { id: string; label: string; render: () => ReactNode }

export const VOICE_SAFETY_QUEUES: VoiceSafetyQueue[] = [
  { id: 'lines', label: 'Held lines', render: () => <HeldLinesQueue /> },
  { id: 'no-go', label: 'No-go matches', render: () => <NoGoQueues /> },
]

/** Step 5: borderline no-go matches above the no-go list itself. A change to the list redraws
 *  the queue, since a removed voice closes the clones waiting on it. */
function NoGoQueues() {
  const [n, setN] = useState(0)
  return (
    <div className="flex flex-col gap-5">
      <NoGoHoldsQueue key={n} />
      <NoGoVoicesList onChange={() => setN((x) => x + 1)} />
    </div>
  )
}

export function VoiceSafetySection({ card, queues = VOICE_SAFETY_QUEUES }: { card: string; queues?: VoiceSafetyQueue[] }) {
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="voice-safety-h" data-testid="admin-voice-safety">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id="voice-safety-h" className="disp m-0 text-[22px] font-bold">Voice safety</h2>
        <span className="tag text-faint">what waits for a person before a voice speaks, oldest first</span>
      </div>
      <TabsPrimitive.Root defaultValue={queues[0]?.id} className="flex flex-col gap-3">
        <TabsPrimitive.List aria-label="Voice safety queues" className="flex flex-wrap gap-1.5">
          {queues.map((q) => (
            <TabsPrimitive.Trigger key={q.id} value={q.id}
              className="pill">
              {q.label}
            </TabsPrimitive.Trigger>
          ))}
        </TabsPrimitive.List>
        {queues.map((q) => (
          <TabsPrimitive.Content key={q.id} value={q.id} className="flex flex-col gap-3 focus-visible:outline-none">
            {q.render()}
          </TabsPrimitive.Content>
        ))}
      </TabsPrimitive.Root>
    </section>
  )
}

const STATE_WORDS: Record<HeldLine['review_state'], string> = {
  waiting: 'Waiting', approved: 'Cleared', rejected: 'Not cleared', expired: 'Not checked in 48 hours',
}

/** Step 4: lines held before they were voiced (a claim, or the check was not sure). Read the
 *  line, why it was held and who wrote it, then clear or refuse it with a reason (kept in the
 *  audit trail; the owner is told). Nobody decides on their own line. */
export function HeldLinesQueue() {
  const [show, setShow] = useState<'waiting' | 'decided'>('waiting')
  const [items, setItems] = useState<HeldLine[] | null>(null)
  const [waiting, setWaiting] = useState<number | null>(null)
  const [unread, setUnread] = useState(false)
  const load = useCallback(() => {
    setUnread(false)
    listHeldLines(show).then((r) => { if (Array.isArray(r?.items)) { setItems(r.items); setWaiting(r.waiting) } })
      .catch(() => setUnread(true))
  }, [show])
  useEffect(load, [load])
  return (
    <div className="flex flex-col gap-3" data-testid="held-lines">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
        <button type="button" className={cn('pill', show === 'waiting' && 'on')} aria-pressed={show === 'waiting'} onClick={() => setShow('waiting')}>
          Waiting{waiting != null ? ` · ${waiting}` : ''}
        </button>
        <button type="button" className={cn('pill', show === 'decided' && 'on')} aria-pressed={show === 'decided'} onClick={() => setShow('decided')}>Decided</button>
      </div>
      {unread && <p className="m-0 text-sm text-muted-foreground">The held lines could not be read.</p>}
      {items && items.length === 0 && <p className="m-0 text-muted-foreground">{show === 'waiting' ? 'Nothing waiting.' : 'Nothing decided yet.'}</p>}
      {items && items.map((r) => <HeldRow key={r.id} r={r} onDone={load} />)}
    </div>
  )
}

function HeldRow({ r, onDone }: { r: HeldLine; onDone: () => void }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const decide = async (decision: 'approve' | 'reject') => {
    setBusy(decision); setError(null)
    try { await decideHeldLine(r.id, decision, reason.trim()); onDone() } catch (e) { setError(said(e, 'That did not save.')) } finally { setBusy(null) }
  }
  const open = r.review_state === 'waiting'
  const why = `why-${r.id}`
  return (
    <article className="flex flex-col gap-2 border-t border-line py-3 text-[13px]" data-testid="held-line" aria-label={`Held line ${r.id}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={open ? 'stamp need' : r.review_state === 'approved' ? 'stamp' : 'stamp inkd'}>{STATE_WORDS[r.review_state]}</span>
        <span className="text-muted-foreground">
          <span className="tnum">{formatDate(r.created_at)}</span> · {r.owner}
          {r.video_id && <> · <a href={hrefFor({ page: 'editor', projectId: r.video_id })} className="underline">video {r.video_id}</a></>}
          {open && <> · rejected on its own <span className="tnum">{formatDate(r.due_at)}</span></>}
        </span>
      </div>
      <p className="m-0 text-[15px] leading-normal">{r.text ?? 'The words were not kept.'}</p>
      <p className="m-0"><span className="tag text-faint">Held for</span> {r.category_words.join(', ') || 'no reason given'}</p>
      {r.reason && <p className="m-0 text-muted-foreground">{r.reason}</p>}
      <span className="truncate text-faint" title={[r.model, ...r.rule_hits].join(' · ')}>{r.model}{r.rule_hits.length ? ` · ${r.rule_hits.length} rule ${r.rule_hits.length === 1 ? 'hit' : 'hits'}` : ''}</span>
      {open ? (
        <div className="flex flex-wrap items-end gap-2.5">
          <label htmlFor={why} className="flex min-w-0 flex-[1_1_220px] flex-col gap-1"><span className="font-semibold">Why</span>
            <input id={why} className={field} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="kept in the audit trail" />
          </label>
          <button type="button" className="btn ink sm pointer-coarse:min-h-11" disabled={!!busy || reason.trim().length < 3} onClick={() => void decide('reject')}>{busy === 'reject' ? 'Not clearing…' : 'Don’t clear'}</button>
          <button type="button" className="btn volt sm pointer-coarse:min-h-11" disabled={!!busy || reason.trim().length < 3} onClick={() => void decide('approve')}>{busy === 'approve' ? 'Clearing…' : 'Clear it'}</button>
        </div>
      ) : (
        <p className="m-0">{r.reviewed_by === 'auto' ? 'Nobody checked it in 48 hours.' : r.reviewed_by} {r.reviewed_at ? formatDate(r.reviewed_at) : ''}{r.review_reason && r.reviewed_by !== 'auto' ? `: ${r.review_reason}` : ''}</p>
      )}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
    </article>
  )
}
