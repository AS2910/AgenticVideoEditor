import type { Word, Selection } from '../types'
import styles from './Timeline.module.css'

interface TimelineProps {
  words: Word[]
  duration: number
  selection: Selection | null
  currentTime: number
  onSelect: (s: Selection) => void
}

const pct = (t: number, duration: number) => `${(t / duration) * 100}%`

export function Timeline({ words, duration, selection, currentTime, onSelect }: TimelineProps) {
  return (
    <div className={styles.timeline}>
      <div className={styles.track}>
        {words.map((w) => (
          <button
            key={`${w.text}-${w.start}`}
            className={styles.word}
            style={{ left: pct(w.start, duration), width: pct(w.end - w.start, duration) }}
            onClick={() => onSelect({ start: w.start, end: w.end })}
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
    </div>
  )
}
