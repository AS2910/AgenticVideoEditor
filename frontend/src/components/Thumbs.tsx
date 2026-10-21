import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { FeedbackMark, FeedbackTarget, FeedbackVote } from '../api'
import { getFeedback, putFeedback } from '../api'
import { useFlags } from '../flags/useFlags'
import { cn } from '@/lib/utils'

/** G8 (golive.g8): thumbs up or down, with an optional reason, on every take and every reply.
 *  The editor wraps the video in a FeedbackProvider; a Thumbs outside one draws nothing. */
interface FeedbackState {
  marks: Record<FeedbackTarget, Record<string, FeedbackMark>>
  give: (target: FeedbackTarget, id: string, vote: FeedbackVote | null, reason?: string) => Promise<void>
}
const Ctx = createContext<FeedbackState | null>(null)

export function FeedbackProvider({ videoId, children }: { videoId: string; children: ReactNode }) {
  const on = useFlags().enabled('golive.g8')
  const [marks, setMarks] = useState<FeedbackState['marks']>({ take: {}, turn: {} })
  useEffect(() => {
    if (!on) return
    let live = true
    getFeedback(videoId).then((m) => { if (live) setMarks({ take: m.take ?? {}, turn: m.turn ?? {} }) }).catch(() => { /* no marks shown */ })
    return () => { live = false }
  }, [on, videoId])
  const give = useCallback(async (target: FeedbackTarget, id: string, vote: FeedbackVote | null, reason = '') => {
    const set = (v: FeedbackVote | null, r: string) => setMarks((m) => {
      const next = { ...m[target] }
      if (v) next[id] = { vote: v, reason: r }
      else delete next[id]
      return { ...m, [target]: next }
    })
    const before = marks[target][id] ?? null
    set(vote, reason)
    try { await putFeedback(videoId, { target, target_id: id, vote, reason }) } catch (e) { set(before?.vote ?? null, before?.reason ?? ''); throw e }
  }, [videoId, marks])
  const value = useMemo(() => (on ? { marks, give } : null), [on, marks, give])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

function Thumb({ up }: { up: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" style={up ? undefined : { transform: 'scaleY(-1)' }}>
      <path d="M5 7.5V14H2.5V7.5H5Zm0 0 3-5.5c1.2 0 1.9.8 1.6 2L9.2 6h3.6c.9 0 1.5.8 1.3 1.6l-1.2 5c-.2.8-.8 1.4-1.6 1.4H5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

export function Thumbs({ target, targetId, dark = false }: { target: FeedbackTarget; targetId: string; dark?: boolean }) {
  const fb = useContext(Ctx)
  const [asking, setAsking] = useState<FeedbackVote | null>(null)
  const [reason, setReason] = useState('')
  const [note, setNote] = useState<string | null>(null)
  if (!fb) return null
  const mine = fb.marks[target][targetId]?.vote ?? null
  const what = target === 'take' ? 'take' : 'reply'
  const vote = async (v: FeedbackVote) => {
    setNote(null)
    const next = mine === v ? null : v
    try {
      await fb.give(target, targetId, next)
      setAsking(next)
      setReason('')
    } catch { setNote('That did not save. Try again.') }
  }
  const send = async () => {
    if (!asking) return
    try { await fb.give(target, targetId, asking, reason.trim()); setAsking(null); setNote('Thanks. That helps.') } catch { setNote('That did not save. Try again.') }
  }
  const quiet = dark ? 'text-pmuted hover:text-ptext' : 'text-muted-foreground hover:text-foreground'
  const pressed = dark ? 'text-volt' : 'text-foreground'
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid={`thumbs-${target}`}>
      <button type="button" className={cn('act min-h-8 w-8 justify-center p-0 pointer-coarse:min-h-11 pointer-coarse:w-11', mine === 'up' ? pressed : quiet)}
        aria-pressed={mine === 'up'} aria-label={`Good ${what}`} title={`Good ${what}`} onClick={() => void vote('up')}><Thumb up /></button>
      <button type="button" className={cn('act min-h-8 w-8 justify-center p-0 pointer-coarse:min-h-11 pointer-coarse:w-11', mine === 'down' ? pressed : quiet)}
        aria-pressed={mine === 'down'} aria-label={`Not a good ${what}`} title={`Not a good ${what}`} onClick={() => void vote('down')}><Thumb up={false} /></button>
      {asking && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); void send() }}>
          <input className={cn('h-8 w-[220px] rounded-md border-[1.5px] px-2 text-[13px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50', dark ? 'border-pline bg-psunk text-ptext' : 'border-line2 bg-card text-foreground')}
            aria-label={asking === 'down' ? `What was off with this ${what}? (optional)` : `What was good about this ${what}? (optional)`}
            placeholder={asking === 'down' ? 'What was off? (optional)' : 'What was good? (optional)'} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          <button type="button" className={cn('act', quiet)} onClick={() => setAsking(null)}>Skip</button>
          <button type="submit" className={cn('btn sm', dark && 'ghost')}>Send</button>
        </form>
      )}
      {note && <span className={cn('text-[12px]', dark ? 'text-pmuted' : 'text-muted-foreground')} role="status">{note}</span>}
    </span>
  )
}
