import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Square, X } from 'lucide-react'

export interface BusyAsk {
  /** "Busy with adding 'Fresh every morning'". */
  text: string
  /** The change that was asked for, in words ("Add line 3"), when it can wait in Up next. */
  change?: string | null
  /** Where it was asked from (the control pressed); the card sits under it. */
  anchor?: DOMRect | null
}

interface BusyHintProps {
  ask: BusyAsk | null
  /** Queue this change: it runs once the video is Ready. Absent: this change cannot wait in Up next. */
  onQueue?: () => void
  /** Stop what holds the video. Absent: it is not yours to stop (another member, or an undo already running). */
  onStop?: () => void
  onClose: () => void
}

/** One edit at a time per video (2026-10-25): a locked control is never silently grey. Pressed while
 *  the video is Working, it says what the video is busy with, under the control, with the two ways on:
 *  Queue this change and Stop. Escape or a click elsewhere closes it; focus moves in and back. */
export function BusyHint({ ask, onQueue, onStop, onClose }: BusyHintProps) {
  const card = useRef<HTMLDivElement>(null)
  const back = useRef<HTMLElement | null>(null)
  const [at, setAt] = useState<{ top: number; left: number } | null>(null)
  useLayoutEffect(() => {
    if (!ask) return
    back.current = document.activeElement as HTMLElement | null
    const r = ask.anchor
    const width = Math.min(340, window.innerWidth - 32)
    setAt(r ? { top: Math.min(r.bottom + 8, window.innerHeight - 160), left: Math.max(16, Math.min(r.left, window.innerWidth - width - 16)) } : null)
    card.current?.querySelector<HTMLElement>('button')?.focus()
  }, [ask])
  useEffect(() => {
    if (!ask) return
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    const away = (e: PointerEvent) => { if (card.current && !card.current.contains(e.target as Node)) close() }
    document.addEventListener('keydown', key)
    document.addEventListener('pointerdown', away)
    return () => { document.removeEventListener('keydown', key); document.removeEventListener('pointerdown', away) }
  })
  const close = () => { onClose(); back.current?.focus?.() }
  if (!ask) return null
  return (
    <div
      ref={card}
      role="dialog"
      aria-label="The video is busy"
      data-testid="busy-hint"
      className="rise fixed z-50 flex w-[min(340px,calc(100vw-32px))] flex-col gap-2.5 rounded-xl border-[1.5px] border-ink bg-card p-3.5 text-foreground shadow-volt"
      style={at ? { top: at.top, left: at.left } : { top: 112, left: '50%', transform: 'translateX(-50%)' }}
    >
      <div className="flex items-start gap-2">
        <span className="blinkdot mt-1.5 size-2 shrink-0 rounded-full bg-warn" aria-hidden="true" />
        <p className="m-0 min-w-0 flex-1 text-sm" role="status" data-testid="busy-text">{ask.text}.{ask.change ? ` ${ask.change} can wait in Up next.` : ''}</p>
        <button type="button" className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-foreground pointer-coarse:size-11" aria-label="Close" onClick={close}><X size={14} aria-hidden="true" /></button>
      </div>
      {(onQueue || onStop) && (
        <div className="flex flex-wrap items-center gap-2">
          {onQueue && <button type="button" className="btn volt sm" onClick={() => { onQueue(); close() }} data-testid="queue-this">Queue this change</button>}
          {onStop && <button type="button" className="btn sm gap-1.5" onClick={() => { onStop(); close() }} data-testid="busy-stop"><Square size={11} fill="currentColor" aria-hidden="true" />Stop</button>}
        </div>
      )}
    </div>
  )
}
