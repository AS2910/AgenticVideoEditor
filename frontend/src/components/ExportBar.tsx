import type { Insert, Segment } from '../types'
import styles from './ExportBar.module.css'

interface ExportBarProps {
  segments: Segment[]
  onExport: () => void
  /** The rendered MP4, once an export has produced one. */
  download?: { url: string; filename: string } | null
  /** Lines added after a point; each makes the export longer. */
  inserts?: Insert[]
}

export function ExportBar({ segments, onExport, download, inserts = [] }: ExportBarProps) {
  const total = segments.length ? segments[segments.length - 1].end : 0
  return (
    <div className={styles.bar}>
      <button className={styles.export} onClick={onExport}>Export</button>
      {download && (
        <a className={styles.download} href={download.url} download={download.filename}>
          Download MP4
        </a>
      )}
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
      {inserts.length > 0 && (
        <div className={styles.inserts} data-testid="inserts">
          +{inserts.length} added {inserts.length === 1 ? 'line' : 'lines'}, holding the frame for{' '}
          {inserts.reduce((t, i) => t + i.duration, 0).toFixed(2)}s
        </div>
      )}
    </div>
  )
}
