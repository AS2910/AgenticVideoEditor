import type { Segment } from '../types'
import styles from './ExportBar.module.css'

interface ExportBarProps {
  segments: Segment[]
  onExport: () => void
}

export function ExportBar({ segments, onExport }: ExportBarProps) {
  const total = segments.length ? segments[segments.length - 1].end : 0
  return (
    <div className={styles.bar}>
      <button className={styles.export} onClick={onExport}>Export</button>
      {segments.length > 0 && (
        <div className={styles.strip}>
          {segments.map((s, i) => (
            <div
              key={i}
              data-testid="segment"
              data-kind={s.kind}
              className={s.kind === 'edited' ? styles.edited : styles.original}
              style={{ width: `${((s.end - s.start) / total) * 100}%` }}
              title={`${s.kind} ${s.start}–${s.end}s`}
            />
          ))}
        </div>
      )}
    </div>
  )
}
