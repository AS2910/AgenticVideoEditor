import { memo, useCallback, useEffect, useRef, useState } from 'react'
import type { MouseEvent, PointerEvent } from 'react'
import type { Word, Selection } from '../types'
import { snapToWords, timeFromX } from '../timeline/selection'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface TimelineProps {
  words: Word[]
  duration: number
  selection: Selection | null
  currentTime: number
  onSelect: (s: Selection) => void
}

const pct = (t: number, duration: number) => `${(t / duration) * 100}%`

/** The words on the track. Memoised: the playhead moves many times a second
 *  and must not re-render every word with it (UX-6). */
const Words = memo(function Words({ words, duration, selection, onClickWord }: {
  words: Word[]
  duration: number
  selection: Selection | null
  onClickWord: (e: MouseEvent, w: Word) => void
}) {
  return (
    <>
      {words.map((w, i) => (
        <button
          key={`${w.text}-${w.start}`}
          // Alternate words sit on two rows, so a label can run past its
          // word's own (often very short) span without covering the next.
          className={cn(
            'absolute h-6.5 min-w-6 overflow-hidden rounded-r-sm border-l border-muted-foreground bg-card px-1 text-left text-xs leading-[26px] text-ellipsis whitespace-nowrap text-foreground outline-none hover:z-10 hover:bg-accent focus-visible:z-10 focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:h-11 pointer-coarse:leading-[44px]',
            i % 2 === 0 ? 'top-1.5 pointer-coarse:top-1' : 'top-8 pointer-coarse:top-[52px]',
          )}
          data-lane={i % 2}
          aria-pressed={selection ? w.start < selection.end && selection.start < w.end : undefined}
          style={{ left: pct(w.start, duration), width: pct(w.end - w.start, duration) }}
          onClick={(e) => onClickWord(e, w)}
        >
          {w.text}
        </button>
      ))}
    </>
  )
})

// A press that moves less than this is a click, not a drag.
const DRAG_THRESHOLD_PX = 4

// Zoom, in pixels per second of video. Clips longer than FIT_UP_TO open
// zoomed to READABLE, where an average spoken word gets ~40 px.
const READABLE = 110
const FIT_UP_TO = 15
const MIN_ZOOM = 10
const MAX_ZOOM = 400
const STEP = 1.5

export function Timeline({ words, duration, selection, currentTime, onSelect }: TimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  // null = fit the whole clip in view.
  const [zoom, setZoom] = useState<number | null>(duration > FIT_UP_TO ? READABLE : null)

  // Keep the playhead in view while zoomed: when it leaves, page to it.
  useEffect(() => {
    const box = scrollRef.current
    if (zoom === null || !box) return
    const x = currentTime * zoom
    if (x < box.scrollLeft || x > box.scrollLeft + box.clientWidth - 24) {
      box.scrollLeft = Math.max(0, x - box.clientWidth * 0.2)
    }
  }, [currentTime, zoom])

  const zoomBy = (factor: number) => {
    const box = scrollRef.current
    // From "fit", zooming starts at the width the clip currently fills.
    const base = zoom ?? (box && duration > 0 ? box.clientWidth / duration : READABLE)
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, base * factor))
    setZoom(box && duration * next <= box.clientWidth ? null : next)
  }
  // Set when a drag ends on a word, so that word's click doesn't replace the
  // dragged range with itself.
  const suppressClick = useRef(false)

  const timeAt = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect()
    return rect ? timeFromX(clientX, rect.left, rect.width, duration) : 0
  }

  const startDrag = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    const originX = e.clientX
    const anchor = timeAt(originX)
    let dragging = false
    suppressClick.current = false

    const move = (ev: globalThis.PointerEvent) => {
      if (!dragging && Math.abs(ev.clientX - originX) < DRAG_THRESHOLD_PX) return
      dragging = true
      onSelect(snapToWords(anchor, timeAt(ev.clientX), words))
    }
    const end = () => {
      suppressClick.current = dragging
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
  }

  const clickWord = useCallback((e: MouseEvent, w: Word) => {
    if (suppressClick.current) {
      suppressClick.current = false
      return
    }
    if (e.shiftKey && selection) {
      onSelect({ start: Math.min(selection.start, w.start), end: Math.max(selection.end, w.end) })
    } else {
      onSelect({ start: w.start, end: w.end })
    }
  }, [selection, onSelect])

  return (
    <div className="relative">
      <div className="mb-1.5 flex justify-end gap-1" role="group" aria-label="Timeline zoom">
        <Button variant="outline" size="sm" onClick={() => zoomBy(1 / STEP)} aria-label="Zoom out">−</Button>
        <Button variant="outline" size="sm" onClick={() => zoomBy(STEP)} aria-label="Zoom in">+</Button>
        <Button variant={zoom === null ? 'secondary' : 'outline'} size="sm" onClick={() => setZoom(null)} aria-pressed={zoom === null}>Fit</Button>
      </div>
      <div ref={scrollRef} className="overflow-x-auto overflow-y-hidden pb-1" data-testid="timeline-scroller">
        <div
          ref={trackRef}
          data-testid="timeline-track"
          className="relative h-16 cursor-col-resize touch-none rounded-lg bg-muted select-none pointer-coarse:h-25"
          style={zoom === null ? undefined : { width: `${duration * zoom}px` }}
          onPointerDown={startDrag}
        >
          {words.length === 0 && (
            <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-muted-foreground">No speech found in this video. There are no words to edit.</div>
          )}

          <Words words={words} duration={duration} selection={selection} onClickWord={clickWord} />

          {selection && (
            <div
              data-testid="selection-region"
              className="pointer-events-none absolute top-0 z-20 h-full border-x-2 border-changed bg-changed-soft/70"
              style={{
                left: pct(selection.start, duration),
                width: pct(selection.end - selection.start, duration),
              }}
            />
          )}

          <div
            data-testid="playhead"
            className="pointer-events-none absolute -top-0.75 z-30 h-[calc(100%+6px)] w-0.5 bg-foreground"
            style={{ left: pct(currentTime, duration) }}
          />
        </div>
      </div>
      {words.length > 0 && (
        <div className="mt-1.5 text-sm text-muted-foreground">Tap or click a word, shift-click to extend, or drag across words.</div>
      )}
      <span className="sr-only" role="status">{selection ? `Selected ${selection.start.toFixed(2)} to ${selection.end.toFixed(2)} seconds` : ''}</span>
    </div>
  )
}
