import { useCallback, useEffect, useState } from 'react'
import { track } from '../lib/analytics'
import type { LearnedItem, LearnedPage, ProjectFolder } from '../types'
import { answerLearned, getLearned, removeLearned } from '../api'
import { Tip } from '../guides/Tip'
import { said } from './fmt'

/** A page as read, with every list present (an older server or a partial answer). */
const whole = (p: Partial<LearnedPage> | null | undefined): LearnedPage => ({
  pending: p?.pending ?? null, learned: Array.isArray(p?.learned) ? p.learned : [], decisions: p?.decisions ?? 0,
  every: p?.every || 10, reasons: Array.isArray(p?.reasons) ? p.reasons : [], project: p?.project,
})

const KIND_WORD: Record<LearnedItem['kind'], string> = { brief: 'Brief', rule: 'Style rule' }

/** D2: what Voltage has learned from your decisions on its lines. Every 10
 *  decisions (added, thrown out, rewritten first) it may suggest one line for
 *  the brief or a style rule; nothing changes until you add it. Each learned
 *  item can be removed, which takes it back out of the brief or the rules. */
export function LearnedStyle({ projectId, onProject, tick = 0 }: {
  projectId: string
  /** The project after an accept or a remove (the brief may have a new version). */
  onProject?: (p: ProjectFolder) => void
  /** Read again when this changes (the brief was saved elsewhere on the page). */
  tick?: number
}) {
  const [page, setPage] = useState<LearnedPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const load = useCallback(() => {
    let live = true
    setError(null)
    getLearned(projectId).then((p) => { if (live) setPage(whole(p)) }).catch((e) => { if (live) setError(said(e, 'What Voltage has learned could not be read.')) })
    return () => { live = false }
  }, [projectId])
  useEffect(() => load(), [load, tick])

  const run = async (key: string, call: () => Promise<LearnedPage>, done: string, fallback: string) => {
    setBusy(key)
    setNote(null)
    try {
      const next = whole(await call())
      setPage(next)
      if (next.project) onProject?.(next.project)
      setNote(done)
    } catch (e) {
      setNote(said(e, fallback))
      void load()
    } finally { setBusy(null) }
  }

  const pending = page?.pending ?? null
  const pendingKey = pending ? String(pending.item_id) : ''
  useEffect(() => { if (pendingKey) track('learned.card_opened') }, [pendingKey])
  const left = page ? page.every - (page.decisions % page.every) : null
  return (
    <div className="rise d1 flex flex-col gap-2.5 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="learned" data-tour="learned">
      <div className="flex flex-wrap items-center gap-2"><span className="disp text-xl font-bold">What Voltage has learned</span><span className="flex-1" />
        {page && <span className="tag text-faint">{page.decisions} {page.decisions === 1 ? 'decision' : 'decisions'}</span>}</div>
      {error ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <span className="flex-1 text-sm text-destructive">{error}</span>
          <button type="button" className="btn sm" onClick={() => load()}>Try again</button>
        </div>
      ) : page === null ? (
        <p className="m-0 text-[13px] text-muted-foreground" role="status" aria-busy="true">Reading what Voltage has learned…</p>
      ) : (
        <>
          {pending && (
            <div className="rise flex flex-col gap-2 rounded-lg bg-pane p-3 text-ptext" data-testid="learned-suggestion">
              <span className="tag text-volt">Voltage noticed · {pending.kind === 'brief' ? 'for the brief' : 'a style rule'}</span>
              <span className="text-sm">“{pending.text}”</span>
              {pending.why && <span className="pm text-[13px]">{pending.why} Nothing changes until you add it.</span>}
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn ghost sm" disabled={busy !== null} onClick={() => void run('dismiss', () => answerLearned(projectId, pending.item_id, 'dismiss'), 'Left out. Voltage looks again after the next 10 decisions.', 'Could not dismiss it.')}>Not now</button>
                <button type="button" className="btn volt sm" disabled={busy !== null} aria-busy={busy === 'accept' || undefined}
                  onClick={() => void run('accept', () => answerLearned(projectId, pending.item_id, 'accept'), pending.kind === 'brief' ? 'Added to the brief as a new version.' : 'Added as a style rule.', 'Could not add it.')}>
                  {busy === 'accept' ? 'Adding…' : pending.kind === 'brief' ? 'Add to brief' : 'Add as a rule'}
                </button>
              </div>
            </div>
          )}
          {page.learned.length === 0 ? (
            <span className="text-[13px] text-muted-foreground" data-testid="learned-empty">
              Nothing yet. Every {page.every} decisions on Voltage's lines (added, thrown out or rewritten first), Voltage looks for a pattern and suggests one line.{left !== null && page.decisions > 0 && !pending ? ` ${left} more to the next look.` : ''}
            </span>
          ) : (
            <ul className="m-0 flex list-none flex-col p-0" aria-label="Learned">
              {page.learned.map((item) => (
                <li key={item.item_id} className="flex items-start gap-2.5 border-t border-line py-2" data-testid="learned-item">
                  <span className="tag mt-0.5 w-[76px] flex-none text-faint">{KIND_WORD[item.kind]}</span>
                  <span className="min-w-0 flex-1 text-sm">{item.text}</span>
                  <button type="button" className="act flex-none" disabled={busy !== null} aria-label={`Remove ${item.text}`} aria-busy={busy === `rm${item.item_id}` || undefined}
                    onClick={() => void run(`rm${item.item_id}`, () => removeLearned(projectId, item.item_id), item.kind === 'brief' ? 'Removed. The brief has a new version without it.' : 'Removed. The rule is gone.', 'Could not remove it.')}>
                    {busy === `rm${item.item_id}` ? 'Removing…' : 'Remove'}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {note && <span className="text-[13px] text-muted-foreground" role="status">{note}</span>}
        </>
      )}
      {pending && <Tip id="first-learned" />}
    </div>
  )
}
