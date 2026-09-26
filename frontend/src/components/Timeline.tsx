import { useRef } from 'react'
import type { MouseEvent, PointerEvent } from 'react'
import type { Word, Selection } from '../types'
import { snapToWords, timeFromX } from '../timeline/selection'
import styles from './Timeline.module.css'

interface TimelineProps {
  words: Word[]
  duration: number
  selection: Selection | null
  currentTime: number
  onSelect: (s: Selection) => void
}

const pct = (t: number, duration: number) => `${(t / duration) * 100}%`

// A press that moves less than this is a click, not a drag.
const DRAG_THRESHOLD_PX = 4

export function Timeline({ words, duration, selection, currentTime, onSelect }: TimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null)
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

  const clickWord = (e: MouseEvent, w: Word) => {
    if (suppressClick.current) {
      suppressClick.current = false
      return
    }
    if (e.shiftKey && selection) {
      onSelect({ start: Math.min(selection.start, w.start), end: Math.max(selection.end, w.end) })
    } else {
      onSelect({ start: w.start, end: w.end })
    }
  }

  return (
    <div className={styles.timeline}>
      <div ref={trackRef} className={styles.track} onPointerDown={startDrag}>
        {words.length === 0 && (
          <div className={styles.empty}>No speech found in this video — there are no words to edit.</div>
        )}

        {words.map((w) => (
          <button
            key={`${w.text}-${w.start}`}
            className={styles.word}
            style={{ left: pct(w.start, duration), width: pct(w.end - w.start, duration) }}
            onClick={(e) => clickWord(e, w)}
          >
            {w.text}
          </button>
        ))}

        {selection && (
          <div
            data-testid="selection-region"
            className={styles.selection}
            style={{
              left: pct(selection.start, duration),
              width: pct(selection.end - selection.start, duration),
            }}
          />
        )}

        <div
          data-testid="playhead"
          className={styles.playhead}
          style={{ left: pct(currentTime, duration) }}
        />
      </div>
      {words.length > 0 && (
        <div className={styles.hint}>Click a word, shift-click to extend, or drag across words.</div>
      )}
    </div>
  )
}
