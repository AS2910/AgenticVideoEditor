import { useState } from 'react'
import { GripVertical, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { QueueItem } from '../types'
import { queueCardLabel } from '../lib/queueState'

interface UpNextProps {
  items: QueueItem[]
  paused: boolean
  /** Another tab's or member's video work: the queue is shown, not changed. */
  readOnly?: boolean
  onRemove: (item: QueueItem) => void
  /** The waiting changes' ids in their new order. */
  onReorder: (ids: number[]) => void
  onRunNext: () => void
  onClear: () => void
}

/** Up next (2026-10-25): the changes waiting on a busy video, as chips under the status strip,
 *  in the order they will run. Each has an x; drag a chip (or Alt+arrow on it) to move it. After
 *  a failure or a Stop the row says it is paused, with Run next and Clear queue. */
export function UpNext({ items, paused, readOnly, onRemove, onReorder, onRunNext, onClear }: UpNextProps) {
  const [dragged, setDragged] = useState<number | null>(null)
  if (items.length === 0) return null
  const waiting = items.filter((i) => i.status === 'queued')
  const move = (id: number, to: number) => {
    const ids = waiting.map((i) => i.id).filter((x) => x !== id)
    ids.splice(Math.max(0, Math.min(ids.length, to)), 0, id)
    onReorder(ids)
  }
  return (
    <div className="flex min-h-9 min-w-0 flex-wrap items-center gap-2 border-b border-line bg-background px-4 py-1.5 sm:px-6" data-testid="up-next" aria-label="Up next" role="region">
      <span className="tag shrink-0 text-faint">{paused ? 'Up next · paused' : 'Up next'}</span>
      <ol className="m-0 flex min-w-0 flex-wrap items-center gap-2 p-0" aria-label="Changes waiting, in order">
        {items.map((item) => {
          const running = item.status === 'running' || item.status === 'paused'   // started: not moved, not removed
          const at = waiting.findIndex((w) => w.id === item.id)
          // Addendum 3.3: the same words as its card in the thread ("Queued 1 of 2: ...", "Running: ...").
          const label = queueCardLabel(item, items)
          return (
            <li
              key={item.id}
              className={cn('flex h-7 min-w-0 max-w-[260px] items-center gap-1 rounded-md border-[1.5px] bg-card pl-1.5 text-[13px] pointer-coarse:h-11',
                running ? 'border-ink' : 'border-line2', dragged === item.id && 'opacity-50')}
              data-testid="up-next-chip"
              draggable={!readOnly && !running}
              onDragStart={(e) => { setDragged(item.id); e.dataTransfer.effectAllowed = 'move' }}
              onDragEnd={() => setDragged(null)}
              onDragOver={(e) => { if (dragged !== null && !running) e.preventDefault() }}
              onDrop={(e) => { e.preventDefault(); if (dragged !== null && dragged !== item.id && at >= 0) move(dragged, at); setDragged(null) }}
            >
              {!readOnly && !running && <GripVertical size={12} className="shrink-0 text-faint" aria-hidden="true" />}
              <span
                className="min-w-0 truncate"
                tabIndex={!readOnly && !running ? 0 : undefined}
                title={item.label}
                aria-label={`${label}${running || readOnly ? '' : '. Alt and an arrow key moves it'}`}
                onKeyDown={(e) => {
                  if (readOnly || running || !e.altKey) return
                  if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); move(item.id, at - 1) }
                  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); move(item.id, at + 1) }
                }}
              >{label}</span>
              {!readOnly && !running ? (
                <button type="button" className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:size-11"
                  aria-label={`Remove ${item.label} from Up next`} onClick={() => onRemove(item)}><X size={12} aria-hidden="true" /></button>
              ) : <span className="w-1.5" />}
            </li>
          )
        })}
      </ol>
      {paused && !readOnly && (
        <span className="ml-auto flex shrink-0 items-center gap-2">
          <button type="button" className="btn volt sm" onClick={onRunNext} data-testid="run-next">Run next</button>
          <button type="button" className="btn sm" onClick={onClear} data-testid="clear-queue">Clear queue</button>
        </span>
      )}
    </div>
  )
}
