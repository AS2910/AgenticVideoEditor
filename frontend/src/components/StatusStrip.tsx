import { ChevronDown, Square } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { StripState } from '../jobs/model'

interface StatusStripProps {
  state: StripState
  /** Opens Activity: this video's jobs, newest first. */
  onOpen: () => void
  /** Stop: queued jobs are cancelled, running ones finish. Shown while anything can be stopped. */
  onStop?: () => void
  stopping?: boolean
  /** The tour and the tests find it here. */
  open?: boolean
}

/** The status strip (2026-10-20): one line under the header, always there.
 *  While anything runs it says what, which line and how long ("Voicing line 2
 *  of 5 · Jeevan · about 12 s"); idle it is a quiet "Up to date · v4 · 2 min
 *  ago". Clicking it opens Activity; Stop sits at its end while work runs. */
export function StatusStrip({ state, onOpen, onStop, stopping, open }: StatusStripProps) {
  return (
    <div
      className={cn('flex min-h-8 min-w-0 items-center gap-2 border-b border-line px-4 sm:px-6', state.busy ? 'bg-card' : 'bg-background')}
      data-testid="status-strip" data-tone={state.tone}
    >
      <button
        type="button"
        className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-md text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:h-11"
        onClick={onOpen}
        aria-haspopup="dialog"
        aria-expanded={open || undefined}
        aria-label={`${state.text}. Open Activity`}
      >
        {state.busy
          ? <span className="wave busy shrink-0" style={{ height: 14 }} aria-hidden="true">{[0, 1, 2, 3].map((i) => <i key={i} style={{ height: 14 }} />)}</span>
          : <span className={cn('size-2 shrink-0 rounded-full', state.tone === 'failed' ? 'bg-warn' : state.tone === 'ready' ? 'bg-volt ring-1 ring-ink' : 'bg-line2')} aria-hidden="true" />}
        <span className={cn('tag min-w-0 truncate', state.busy ? 'text-foreground' : 'text-faint')} role="status" aria-live="polite" data-testid="status-text">{state.text}</span>
        <span className="tag ml-auto hidden shrink-0 items-center gap-1 text-faint sm:inline-flex" aria-hidden="true">Activity<ChevronDown size={12} /></span>
      </button>
      {onStop && (
        <button type="button" className="act h-7 shrink-0 gap-1.5 pointer-coarse:h-11" onClick={onStop} disabled={stopping} aria-busy={stopping || undefined} data-testid="stop">
          <Square size={11} fill="currentColor" aria-hidden="true" />{stopping ? 'Stopping…' : 'Stop'}
        </button>
      )}
    </div>
  )
}
