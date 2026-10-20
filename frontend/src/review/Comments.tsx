import { useState } from 'react'
import type { ReviewComment } from '../types'
import { replyReviewComment, resolveReviewComment } from '../api'
import { commentGoal } from './useReviewComments'
import { clock } from '../transcript/format'
import { said } from '../pages/fmt'
import { formatRelative } from '../lib/dates'

function CommentRow({ videoId, c, busy, onSeek, onAsk, onChanged }: {
  videoId: string; c: ReviewComment; busy: boolean; onSeek: (t: number) => void; onAsk: (goal: string) => void; onChanged: (c: ReviewComment) => void
}) {
  const [replying, setReplying] = useState(false)
  const [text, setText] = useState('')
  const [working, setWorking] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const act = async (fn: () => Promise<ReviewComment>, fallback: string) => {
    setWorking(true)
    setNote(null)
    try { onChanged(await fn()); return true } catch (e) { setNote(said(e, fallback)); return false } finally { setWorking(false) }
  }
  const open = c.status === 'open'
  return (
    <li className={open ? 'flex flex-col gap-1.5 rounded-[10px] border-[1.5px] border-foreground bg-card p-3' : 'flex flex-col gap-1.5 rounded-[10px] border border-line2 bg-card p-3 opacity-80'} data-testid="comment" data-status={c.status}>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="tnum act p-0 font-semibold" onClick={() => onSeek(c.at_s)} aria-label={`Go to ${clock(c.at_s)}`}>{clock(c.at_s)}</button>
        {c.version != null && <span className="tag text-faint">v{c.version}</span>}
        <span className="text-sm font-semibold">{c.author_name}</span>
        <span className="text-xs text-faint">{formatRelative(c.created_at)}</span>
        <span className="flex-1" />
        <span className={open ? 'stamp need' : 'stamp in'}>{open ? 'Open' : 'Resolved'}</span>
      </div>
      <p className="m-0 text-[15px] whitespace-pre-wrap">{c.text}</p>
      {c.replies.map((r, i) => (
        <p key={i} className="m-0 border-l-2 border-line2 pl-3 text-sm"><span className="font-semibold">{r.author_kind === 'user' ? 'You' : r.author_name}</span> {r.text}</p>
      ))}
      {replying && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={async (e) => { e.preventDefault(); if (text.trim() && await act(() => replyReviewComment(videoId, c.comment_id, text.trim()), 'Could not send the reply.')) { setText(''); setReplying(false) } }}>
          <label htmlFor={`reply-${c.comment_id}`} className="sr-only">Reply to {c.author_name}</label>
          <input id={`reply-${c.comment_id}`} autoFocus className="h-8 min-w-0 flex-[1_1_200px] rounded-md border-[1.5px] border-line2 bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={text} maxLength={2000} onChange={(e) => setText(e.target.value)} placeholder={`Reply to ${c.author_name}`} />
          <button type="button" className="act" onClick={() => setReplying(false)}>Cancel</button>
          <button type="submit" className="btn sm" disabled={!text.trim() || working}>{working ? 'Sending…' : 'Send reply'}</button>
        </form>
      )}
      {note && <span className="text-sm text-destructive" role="alert">{note}</span>}
      {!replying && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="act" onClick={() => setReplying(true)}>Reply</button>
          <button type="button" className="act" disabled={working} onClick={() => void act(() => resolveReviewComment(videoId, c.comment_id, open), open ? 'Could not resolve it.' : 'Could not open it again.')}>{open ? 'Resolve' : 'Open again'}</button>
          {open && <button type="button" className="btn volt sm" disabled={busy} onClick={() => onAsk(commentGoal(c))} title="Voltage takes this comment as a normal turn">Do what the client asked</button>}
        </div>
      )}
    </li>
  )
}

/** C2: the Comments list under the transcript: each comment at its time
 *  (select it to go there), its replies, Reply, Resolve, and Do what the
 *  client asked. Open ones first; resolved ones behind a Show. */
export function ReviewComments({ videoId, comments, error, busy, onReload, onSeek, onAsk, onChanged }: {
  videoId: string; comments: ReviewComment[] | null; error: string | null; busy: boolean
  onReload: () => void; onSeek: (t: number) => void; onAsk: (goal: string) => void; onChanged: (c: ReviewComment) => void
}) {
  const [showResolved, setShowResolved] = useState(false)
  if (comments === null && !error) return <p className="m-0 text-sm text-muted-foreground" role="status">Reading the review comments…</p>
  if (error && comments === null) return (
    <div className="flex items-center gap-2 text-sm" role="alert"><span className="flex-1 text-destructive">{error}</span><button type="button" className="btn sm" onClick={onReload}>Try again</button></div>
  )
  const all = comments ?? []
  if (all.length === 0) return null
  const open = all.filter((c) => c.status === 'open')
  const resolved = all.filter((c) => c.status === 'resolved')
  return (
    <section className="flex flex-col gap-2.5" aria-label="Review comments" data-testid="review-comments" data-tour="review-comments">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="disp m-0 text-[22px] font-bold">Comments</h2>
        <span className="tag text-faint">{open.length} open{resolved.length ? ` · ${resolved.length} resolved` : ''}</span>
      </div>
      {open.length === 0 && <span className="text-sm text-muted-foreground">Every comment is resolved.</span>}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {open.map((c) => <CommentRow key={c.comment_id} videoId={videoId} c={c} busy={busy} onSeek={onSeek} onAsk={onAsk} onChanged={onChanged} />)}
      </ul>
      {resolved.length > 0 && <button type="button" className="act self-start" aria-expanded={showResolved} onClick={() => setShowResolved((s) => !s)}>{showResolved ? 'Hide resolved' : `Show ${resolved.length} resolved`}</button>}
      {showResolved && (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {resolved.map((c) => <CommentRow key={c.comment_id} videoId={videoId} c={c} busy={busy} onSeek={onSeek} onAsk={onAsk} onChanged={onChanged} />)}
        </ul>
      )}
    </section>
  )
}
