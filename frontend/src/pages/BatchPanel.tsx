import { useEffect, useRef, useState } from 'react'
import type { Batch, BatchRow, BatchRowState, ProjectSummary } from '../types'
import { addAllBatch, answerBatchVideo, cancelBatch, goBatch, listBatches, planBatch, stageHold, undoBatchAdd } from '../api'
import { useFlags } from '../flags/useFlags'
import { StageWarning } from './StageWarning'
import { approvedWords } from './feedWords'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { said, usd } from './fmt'
import { Tip } from '../guides/Tip'
import { BatchGate } from './BatchGate'

/** What a Fix in all from the project check asks for: that issue, in the videos it names. */
export interface FixRequest { issueId: number; message: string; videoIds: string[] }

const STAMP: Record<BatchRowState, string> = {
  planned: 'quiet', queued: 'live', working: 'live', ready: '', nothing: 'in', failed: 'need', waiting: 'need', cancelled: 'quiet', added: 'in',
}
const STAGE_WORD: Record<string, string> = { draft: 'Draft', in_review: 'In review', changes_asked: 'Changes asked', approved: 'Approved', exported: 'Exported' }


const running = (b: Batch | null) => !!b && (b.phase === 'running' || b.rows.some((r) => r.state === 'working' || r.state === 'queued'))

/** One video on the board: its state, the video (opens its proposals in the
 *  editor), why it ended as it did; a paused video's question with its
 *  options and an answer box; Undo for lines the batch added. */
function Row({ row, busy, onAnswer, onUndo }: { row: BatchRow; busy: string | null; onAnswer: (text: string) => void; onUndo: () => void }) {
  const [text, setText] = useState('')
  const undone = row.added?.undone_at
  return (
    <li className="flex flex-col gap-1.5 border-t border-line py-2.5 first:border-t-0" data-testid="batch-row" data-state={row.state}>
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <span className={cn('stamp', STAMP[row.state])}>{row.label}</span>
        <a className="min-w-0 flex-1 truncate font-semibold text-foreground" href={hrefFor({ page: 'editor', projectId: row.video_id })} title={`Open ${row.filename}`}>{row.filename}</a>
        {row.spent_usd > 0 && <span className="tnum text-[13px] text-muted-foreground">{usd(row.spent_usd)}</span>}
      </div>
      {row.why && <span className="text-[13px] text-muted-foreground">{row.why}</span>}
      {row.state === 'waiting' && row.question && (
        <div className="flex flex-col gap-2 rounded-lg border-[1.5px] border-dashed border-ink bg-sunk p-2.5" data-testid="batch-question">
          <span className="text-sm">{row.question.text}</span>
          {row.question.options.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {row.question.options.map((o) => <button key={o} type="button" className="btn sm opt" disabled={busy !== null} onClick={() => onAnswer(o)}>{o}</button>)}
            </div>
          )}
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onAnswer(text.trim()); setText('') } }}>
            <input className="h-8 min-w-0 flex-1 rounded-md border-[1.5px] border-line2 bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={text} onChange={(e) => setText(e.target.value)} placeholder="Or say it in your words" aria-label={`Your answer for ${row.filename}`} />
            <button type="submit" className="btn sm" disabled={busy !== null || !text.trim()}>{busy === `answer-${row.video_id}` ? 'Sending…' : 'Answer'}</button>
          </form>
        </div>
      )}
      {row.added && !undone && (row.added.edit_ids.length > 0) && (
        <button type="button" className="act self-start" disabled={busy !== null} onClick={onUndo}>{busy === `undo-${row.video_id}` ? 'Undoing…' : `Undo the ${row.added.edit_ids.length === 1 ? 'line' : `${row.added.edit_ids.length} lines`} added here`}</button>
      )}
      {undone && <span className="text-[13px] text-muted-foreground">Undone. The lines are back as proposals.</span>}
    </li>
  )
}

/** B1 (projects.batch): one goal across the project's videos. Ask Voltage
 *  about all videos (or a Fix in all from the check) with the videos picked
 *  (all by default, each with its stage), one plan and one gate card with the
 *  totals and the batch's cap, then a board with one row per video, three
 *  working at a time, and Add all that passed last. */
export function BatchPanel({ projectId, videos, fix, onFixHandled, refresh = 0, onAdded }: { projectId: string; videos: ProjectSummary[]; fix?: FixRequest | null; onFixHandled?: () => void; refresh?: number; onAdded?: () => void }) {
  const [batch, setBatch] = useState<Batch | null>(null)
  // C1 (projects.review): the warning before Add all that passed lands on Approved videos.
  const reviewOn = useFlags().enabled('projects.review')
  const [hold, setHold] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [goal, setGoal] = useState('')
  const [picked, setPicked] = useState<Set<string> | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const live = useRef(true)
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    live.current = true
    let timer: ReturnType<typeof setTimeout> | null = null
    const read = () => listBatches(projectId).then((r) => {
      if (!live.current) return
      const latest = r.batches[0] ?? null
      setBatch(latest)
      setLoaded(true)
      setError(null)
      if (running(latest)) timer = setTimeout(read, 1500)
    }).catch((e) => { if (live.current) { setLoaded(true); setError(said(e, 'Could not read the batches.')) } })
    void read()
    return () => { live.current = false; if (timer) clearTimeout(timer) }
  }, [projectId, tick, refresh])

  // A Fix in all from the check: plan that issue across its videos at once (the gate still waits for Go).
  useEffect(() => {
    if (!fix) return
    onFixHandled?.()
    void act('plan-fix', () => planBatch(projectId, { source: 'fix', issue_id: fix.issueId, video_ids: fix.videoIds }), 'Could not plan the fix across the videos.')
  }, [fix]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (key: string, work: () => Promise<Batch>, fallback: string) => {
    setBusy(key)
    setNote(null)
    try {
      const next = await work()
      setBatch(next)
      setDismissed(null)
      setTick((t) => t + 1)
      return next
    } catch (e) { setNote(said(e, fallback)) } finally { setBusy(null) }
    return null
  }

  const chosen = picked ?? new Set(videos.map((v) => v.video_id))
  const toggle = (id: string) => setPicked(() => { const next = new Set(chosen); if (next.has(id)) next.delete(id); else next.add(id); return next })
  const plan = async () => {
    const g = goal.trim()
    if (!g) { setNote('Say what you want done in the videos.'); box.current?.focus(); return }
    const ids = videos.filter((v) => chosen.has(v.video_id)).map((v) => v.video_id)
    const made = await act('plan', () => planBatch(projectId, { source: 'ask', goal: g, video_ids: ids }), 'Could not plan that across the videos.')
    if (made) setGoal('')
  }

  // A batch dropped at its gate is gone; one cancelled after Go keeps its board (what finished, what did not).
  const showing = batch && !(batch.phase === 'cancelled' && !batch.started_at) && dismissed !== batch.batch_id ? batch : null
  const gate = showing?.phase === 'gate'
  const board = showing && !gate
  const passing = showing?.rows.filter((r) => r.state === 'ready').length ?? 0
  /** C1: Add all that passed on Approved videos warns first; Add anyway sends the yes. */
  const addAll = async (confirm: boolean) => {
    if (!showing) return
    if (!confirm && reviewOn) {
      const held = showing.rows.filter((r) => r.state === 'ready' && (videos.find((v) => v.video_id === r.video_id)?.stage ?? r.stage) === 'approved')
      if (held.length > 0) { setHold(approvedWords(held.map((r) => r.filename))); return }
    }
    setBusy('add')
    setNote(null)
    try {
      setBatch(await addAllBatch(projectId, showing.batch_id, confirm))
      setHold(null)
      setDismissed(null)
      setTick((t) => t + 1)
      onAdded?.()
    } catch (e) {
      const h = stageHold(e)
      if (h) setHold(h.message)
      else setNote(said(e, 'Could not add the lines.'))
    } finally { setBusy(null) }
  }

  return (
    <section aria-label="Ask Voltage about all videos" className="rise flex flex-col gap-3 rounded-xl bg-pane p-[18px] text-ptext" data-testid="batch" data-tour="batch">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="disp m-0 text-xl font-bold">Ask Voltage about all videos</h2>
        <span className="tag text-pmuted">One plan, one go, a turn per video</span>
      </div>

      {error && (
        <div className="flex items-center gap-3 text-sm" role="alert">
          <span className="flex-1 text-volt">{error}</span><button type="button" className="btn ghost sm" onClick={() => setTick((t) => t + 1)}>Try again</button>
        </div>
      )}
      {!error && !loaded && <p className="pm m-0 text-sm" role="status">Reading the last batch…</p>}

      {loaded && !showing && (
        videos.length === 0 ? <p className="pm m-0 text-sm" data-testid="batch-empty">Add videos to this project, then ask for one change across all of them.</p> : (
          <form className="flex flex-col gap-2.5" onSubmit={(e) => { e.preventDefault(); void plan() }} data-testid="batch-ask">
            <label htmlFor="batch-goal" className="sr-only">What to change in every video</label>
            <textarea id="batch-goal" ref={box} rows={2} className="w-full resize-y rounded-lg border-[1.5px] border-pline bg-psunk p-3 text-[14.5px] leading-[1.5] text-ptext outline-none placeholder:text-pmuted focus-visible:ring-[3px] focus-visible:ring-volt/50" placeholder="Like “make every offer line say 25% off”" value={goal} onChange={(e) => setGoal(e.target.value)} />
            <fieldset className="m-0 flex flex-col gap-1 border-0 p-0" data-testid="batch-picker">
              <legend className="tag mb-1 text-pmuted">{chosen.size} of {videos.length} videos</legend>
              {videos.map((v) => (
                <label key={v.video_id} className="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1 hover:bg-psunk">
                  <input type="checkbox" className="size-4 accent-volt" checked={chosen.has(v.video_id)} onChange={() => toggle(v.video_id)} />
                  <span className="min-w-0 flex-1 truncate text-sm">{v.filename}{v.language_label ? ` · ${v.language_label}` : ''}</span>
                  <span className="tag text-pmuted">{STAGE_WORD[v.stage ?? 'draft'] ?? v.stage}</span>
                </label>
              ))}
            </fieldset>
            {note && <p className="m-0 text-sm text-volt" role="alert">{note}</p>}
            <button type="submit" className="btn volt sm self-end" disabled={busy !== null || chosen.size === 0}>{busy === 'plan' ? 'Planning…' : `Plan it for ${chosen.size} ${chosen.size === 1 ? 'video' : 'videos'}`}</button>
          </form>
        )
      )}
      {loaded && !showing && busy === 'plan-fix' && <p className="pm m-0 text-sm" role="status">Planning the fix across the videos…</p>}

      {gate && showing && (
        <BatchGate batch={showing} note={note} busy={busy !== null} going={busy === 'go'}
          onCancel={() => void act('cancel', () => cancelBatch(projectId, showing.batch_id), 'Could not drop the batch.')}
          onGo={() => void act('go', () => goBatch(projectId, showing.batch_id), 'Could not start the batch.')} />
      )}

      {board && showing && (
        <div className="flex flex-col gap-2 rounded-lg bg-card p-3 text-foreground" data-testid="batch-board" role="status" aria-live="polite">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="disp text-base font-bold">{showing.phase === 'running' ? showing.step : showing.phase === 'cancelled' ? 'Batch cancelled' : 'Batch finished'}</span>
            <span className="tnum text-[13px] text-muted-foreground">{usd(showing.spent_usd)} of {usd(showing.totals.cap_usd)}</span>
          </div>
          <span className="text-[13px] text-muted-foreground">{showing.source === 'fix' ? `Fix: ${showing.goal}` : showing.source === 'brief' ? showing.goal : `“${showing.goal}”`}</span>
          <ul className="m-0 flex list-none flex-col p-0">
            {showing.rows.map((r) => (
              <Row key={r.video_id} row={r} busy={busy}
                onAnswer={(text) => void act(`answer-${r.video_id}`, () => answerBatchVideo(projectId, showing.batch_id, r.video_id, text), 'Could not send that answer.')}
                onUndo={() => void act(`undo-${r.video_id}`, () => undoBatchAdd(projectId, showing.batch_id, r.video_id), 'Could not undo those lines.')} />
            ))}
          </ul>
          {showing.phase === 'running' && <Tip id="first-batch" target="batch" />}
          {note && <p className="m-0 text-sm text-destructive" role="alert">{note}</p>}
          {hold && <StageWarning message={hold} busy={busy === 'add'} onCancel={() => setHold(null)} onAnyway={() => void addAll(true)} />}
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-2">
            {showing.phase === 'running'
              ? <button type="button" className="btn sm" disabled={busy !== null} onClick={() => void act('cancel', () => cancelBatch(projectId, showing.batch_id), 'Could not cancel the batch.')}>{busy === 'cancel' ? 'Cancelling…' : 'Cancel the rest'}</button>
              : <button type="button" className="act" onClick={() => setDismissed(showing.batch_id)}>Ask something new</button>}
            {passing > 0 && !hold && (
              <button type="button" className="btn volt sm" disabled={busy !== null} onClick={() => void addAll(false)}>
                {busy === 'add' ? 'Adding…' : `Add all that passed · ${passing} ${passing === 1 ? 'video' : 'videos'}`}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
