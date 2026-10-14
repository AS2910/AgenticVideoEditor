import type { Insert, MouthReport, Piece, Segment } from '../types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface ExportBarProps {
  segments: Segment[]
  onExport: () => void
  /** The rendered MP4, once an export has produced one. */
  download?: { url: string; filename: string } | null
  /** Lines added after a point; each makes the export longer. */
  inserts?: Insert[]
  /** Phase 16: the render as pieces — how the picture made room, and what flexed. */
  pieces?: Piece[]
  /** Phase 17: where the mouth was moved to match the new words, and what was left alone. */
  mouth?: MouthReport | null
  /** A render is running: one button, disabled, saying so (UX-6). */
  busy?: boolean
}

const secs = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`

/** The header's export: one button that says where things stand — Export,
 *  Exporting…, then Download with Export again beside it — and a strip of
 *  where the edits fall, described in words for a screen reader. */
export function ExportBar({ segments, onExport, download, inserts = [], pieces = [], mouth, busy }: ExportBarProps) {
  const length = (p: Piece) => p.out_end - p.out_start
  const room = pieces.filter((p) => p.kind === 'living' || p.kind === 'hold').reduce((t, p) => t + length(p), 0)
  const held = pieces.filter((p) => p.kind === 'hold').reduce((t, p) => t + length(p), 0)
  const flexed = pieces.filter((p) => p.kind === 'flex' && p.factor != null && Math.abs(p.factor - 1) > 0.005)
  const flexPct = flexed.length ? Math.round(Math.max(...flexed.map((p) => Math.abs((p.factor as number) - 1))) * 100) : 0
  const total = segments.length ? segments[segments.length - 1].end : 0
  const edited = segments.filter((s) => s.kind === 'edited')
  const stripLabel = edited.length === 0
    ? 'No edited stretches'
    : `${edited.length} edited ${edited.length === 1 ? 'stretch' : 'stretches'}, between ${secs(edited[0].start)} and ${secs(edited[edited.length - 1].end)}`
  return (
    <div className="flex items-center gap-2.5 max-[960px]:flex-[1_1_100%] max-[960px]:flex-wrap">
      {segments.length > 0 && (
        <div className="flex h-1.5 w-30 overflow-hidden rounded-full bg-muted" role="img" aria-label={stripLabel}>
          {segments.map((s, i) => (
            <div
              key={i}
              data-testid="segment"
              data-kind={s.kind}
              className={cn(s.kind === 'edited' ? 'bg-ok' : 'bg-muted-foreground/25')}
              style={{ width: `${((s.end - s.start) / total) * 100}%` }}
            />
          ))}
        </div>
      )}
      {(inserts.length > 0 || flexed.length > 0) && (
        <div className="max-w-[220px] text-xs leading-snug text-muted-foreground max-[960px]:max-w-none" data-testid="inserts">
          {inserts.length > 0 && (
            <>+{inserts.length} added {inserts.length === 1 ? 'line' : 'lines'}; the picture makes room for{' '}
            {(pieces.length ? room : inserts.reduce((t, i) => t + i.duration, 0)).toFixed(2)} s{held > 0.005 ? `, ${held.toFixed(2)} s of it held` : ''}.</>
          )}
          {flexed.length > 0 && (
            <>{inserts.length > 0 ? ' ' : ''}{flexed.length} {flexed.length === 1 ? 'line' : 'lines'} flexed the picture by up to {flexPct}%.</>
          )}
        </div>
      )}
      {mouth && (mouth.moved.length > 0 || mouth.notes.length > 0) && (
        <div className="max-w-[240px] text-xs leading-snug text-muted-foreground max-[960px]:max-w-none" data-testid="mouth">
          {mouth.moved.length > 0 && (
            <>Mouth moved for {mouth.seconds.toFixed(1)} s{mouth.usd > 0 ? ` · $${mouth.usd.toFixed(2)}` : ' · from before, no charge'}.</>
          )}
          {mouth.notes.map((n, i) => <span key={i}>{mouth.moved.length > 0 || i > 0 ? ' ' : ''}{n}</span>)}
        </div>
      )}
      {busy ? (
        <Button variant="outline" size="sm" disabled aria-busy="true">Exporting…</Button>
      ) : download ? (
        <>
          <Button asChild size="sm"><a href={download.url} download={download.filename}>Download MP4</a></Button>
          <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={onExport}>Export again</Button>
        </>
      ) : (
        <Button variant="outline" size="sm" onClick={onExport}>Export MP4</Button>
      )}
    </div>
  )
}
