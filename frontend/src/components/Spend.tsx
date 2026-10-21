import { useEffect, useRef, useState } from 'react'
import type { SpendScope, SpendScopeKey, SpendSummary } from '../types'
import { hrefFor } from '../lib/route'
import { ofCeiling } from '../lib/money'
import { FillBar } from '../pages/bits'

/** Spend scopes (2026-10-19): the editor's spend pill and the scope meters.
 *  The element holding a figure and its label carries `data-money-scope`. */

/** The pill's short name for a scope: "Project $0.61 of $10", "October $3.10 of $100". */
const PILL_WORD: Record<SpendScopeKey, string> = { turn: 'This turn', video: 'Video', project: 'Project', month: '' }

/** One scope as a meter: its label, what it spent of its ceiling, a bar; the binding one is stamped. */
export function ScopeMeter({ scope, s, binding = false }: { scope: SpendScopeKey; s: SpendScope; binding?: boolean }) {
  const share = s.ceiling_usd ? s.spent_usd / s.ceiling_usd : 0
  return (
    <div className="flex flex-col gap-1.5" data-money-scope={scope} data-testid={`meter-${scope}`}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="min-w-0 flex-1 truncate font-medium">{s.label}</span>
        {' '}
        <span className="tnum text-[13px]">{ofCeiling(s)}{s.ceiling_usd == null && <span className="text-faint"> · no ceiling</span>}</span>
      </div>
      {s.ceiling_usd != null && <FillBar share={share} height={8} strong={binding} label={`${s.label}: ${ofCeiling(s)}`} />}
      {binding && <span className="stamp self-start">stops paid work first</span>}
    </div>
  )
}

/** The editor header's spend: the binding scope with its label, e.g.
 *  "Project $0.61 of $10". It opens the scopes stacked (this video, the
 *  project or "No project", the month), the binding one marked, and a link
 *  to Usage filtered to this video. */
export function SpendPill({ summary, videoId }: { summary: SpendSummary | null; videoId: string }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    panel.current?.focus()
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); button.current?.focus() } }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  const key: SpendScopeKey = summary?.binding && summary[summary.binding] ? summary.binding : 'video'
  const shown = summary?.[key] ?? null
  const word = shown ? PILL_WORD[key] || shown.label : 'Spend'
  const share = shown?.ceiling_usd ? shown.spent_usd / shown.ceiling_usd : 0
  return (
    <div className="relative" ref={box}>
      <button
        ref={button}
        type="button"
        className="tnum flex min-h-8 items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-foreground outline-none hover:bg-sunk focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:min-h-11"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        data-testid="spend"
        data-tour="spend"
        data-money-scope={key}
      >
        <span className="font-medium">{word}</span>{' '}
        {shown ? <span>{ofCeiling(shown)}</span> : <span aria-hidden="true">…</span>}
        {shown?.ceiling_usd != null && (
          <span className="h-2 w-10 overflow-hidden rounded-sm bg-line max-[1600px]:hidden" aria-hidden="true"><span className="block h-full bg-foreground" style={{ width: `${Math.min(100, share * 100)}%` }} /></span>
        )}
        <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="Spend" className="rise absolute right-0 z-30 mt-1 flex w-80 max-w-[calc(100vw-32px)] flex-col gap-3.5 rounded-xl border-[1.5px] border-ink bg-card p-4 shadow-volt outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" data-testid="spend-popover">
          <span className="tag text-faint">Spend by scope</span>
          {!summary ? <p className="m-0 text-[13px] text-muted-foreground" role="status">Adding up…</p> : (
            <>
              {summary.video && <ScopeMeter scope="video" s={summary.video} binding={summary.binding === 'video'} />}
              {summary.project
                ? <ScopeMeter scope="project" s={summary.project} binding={summary.binding === 'project'} />
                : <div className="flex items-baseline gap-2" data-testid="meter-no-project"><span className="flex-1 font-medium text-muted-foreground">No project</span><span className="tag text-faint">standalone video</span></div>}
              <ScopeMeter scope="month" s={summary.month} binding={summary.binding === 'month'} />
            </>
          )}
          <a className="act self-start" href={hrefFor({ page: 'usage', scope: { kind: 'video', id: videoId } })} onClick={() => setOpen(false)}>See this video in Usage →</a>
        </div>
      )}
    </div>
  )
}
