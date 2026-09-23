import type { Segment } from '../types'
import styles from './ExportBar.module.css'

interface ExportBarProps {
  segments: Segment[]
  onExport: () => void
  /** The rendered MP4, once an export has produced one. */
  download?: { url: string; filename: string } | null
}

export function ExportBar({ segments, onExport, download }: ExportBarProps) {
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
    </div>
  )
}
