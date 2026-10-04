import type { Insert, Segment } from '../types'
import styles from './ExportBar.module.css'

interface ExportBarProps {
  segments: Segment[]
  onExport: () => void
  /** The rendered MP4, once an export has produced one. */
  download?: { url: string; filename: string } | null
  /** Lines added after a point; each makes the export longer. */
  inserts?: Insert[]
  /** A render is running: one button, disabled, saying so (UX-6). */
  busy?: boolean
}

const secs = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`

/** The header's export: one button that says where things stand — Export,
 *  Exporting…, then Download with Export again beside it — and a strip of
 *  where the edits fall, described in words for a screen reader. */
export function ExportBar({ segments, onExport, download, inserts = [], busy }: ExportBarProps) {
  const total = segments.length ? segments[segments.length - 1].end : 0
  const edited = segments.filter((s) => s.kind === 'edited')
  const stripLabel = edited.length === 0
    ? 'No edited stretches'
    : `${edited.length} edited ${edited.length === 1 ? 'stretch' : 'stretches'}, between ${secs(edited[0].start)} and ${secs(edited[edited.length - 1].end)}`
  return (
    <div className={styles.bar}>
      {segments.length > 0 && (
        <div className={styles.strip} role="img" aria-label={stripLabel}>
          {segments.map((s, i) => (
            <div
              key={i}
              data-testid="segment"
              data-kind={s.kind}
              className={s.kind === 'edited' ? styles.edited : styles.original}
              style={{ width: `${((s.end - s.start) / total) * 100}%` }}
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
      {busy ? (
        <button className={styles.export} disabled aria-busy="true">Exporting…</button>
      ) : download ? (
        <>
          <a className={styles.download} href={download.url} download={download.filename}>Download MP4</a>
          <button className={styles.again} onClick={onExport}>Export again</button>
        </>
      ) : (
        <button className={styles.export} onClick={onExport}>Export MP4</button>
      )}
    </div>
  )
}
