import { useEffect, useRef } from 'react'
import { track } from '../lib/analytics'
import { cn } from '@/lib/utils'

/** C1: the warning before an add lands on an Approved video ("This video is
 *  Approved. Adding this moves it back to Draft."), with Cancel and Add anyway
 *  (the next action, last and focused). */
export function StageWarning({ message, onAnyway, onCancel, busy, className }: {
  message: string; onAnyway: () => void; onCancel: () => void; busy?: boolean; className?: string
}) {
  const anyway = useRef<HTMLButtonElement>(null)
  useEffect(() => { anyway.current?.focus() }, [])
  return (
    <div role="alertdialog" aria-label="Adding moves an Approved video back to Draft" aria-describedby="stage-warning-text" data-testid="stage-warning"
      className={cn('rise flex flex-wrap items-center gap-3 rounded-xl border-[1.5px] border-warn bg-card p-3.5', className)}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); onCancel() } }}>
      <span className="stamp need">Approved</span>
      <span id="stage-warning-text" className="min-w-0 flex-[1_1_220px] text-sm">{message}</span>
      <button type="button" className="btn sm" onClick={() => { track('stage.add_cancelled'); onCancel() }} disabled={busy}>Cancel</button>
      <button ref={anyway} type="button" className="btn volt sm" onClick={() => { track('stage.add_anyway'); onAnyway() }} disabled={busy}>{busy ? 'Adding…' : 'Add anyway'}</button>
    </div>
  )
}
