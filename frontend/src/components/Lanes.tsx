import { useId, useRef } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode, Ref } from 'react'
import type { ItemStatus, Mix, Piece, PlanItem, Revision, Speaker, Statement } from '../types'
import { speakerSlot } from '../transcript/speakers'
import { clock } from '../transcript/format'
import { cn } from '@/lib/utils'

/** The lanes (UX-9): a DAW-style multitrack under the monitor that makes
 *  coexisting audio visible. The x axis is SOURCE time. Top to bottom: a
 *  ruler with the playhead and an invisible seek slider; V1 Picture (the
 *  render's pieces: as shot, flexed, held); A1 Spoken (one pill per line,
 *  tinted by speaker, struck through when removed, lit when changed); A2
 *  Added (every added or proposed line — overlapping ones packed into their
 *  own sub-rows, never collapsed); A3 Tone (a room-tone patch per removal). */

export interface LanesProps {
  /** The source's length in seconds (the x axis is source time). */
  duration: number
  /** The playhead, in source time. */
  currentTime: number
  /** The spoken lines. */
  statements: Statement[]
  /** Where each spoken line plays now, by its place in `statements` (the arrangement, 2026-10-19); missing = as shot. */
  placedAt?: ({ start: number; end: number } | undefined)[]
  /** The cast; an unnamed speaker shows as "Speaker N" by order of appearance. */
  speakers: Speaker[]
  /** The live edits: the added lines are in the video, a removal strikes its line. */
  revisions: Revision[]
  /** The plan: a proposed or working added line is a pill in A2; a replace or
   *  remove item marks its spoken line. */
  items: PlanItem[]
  /** The render's pieces for V1; none means the picture is as shot. */
  pieces?: Piece[]
  /** A click on a pill or the ruler seeks, in source time. */
  onSeek: (t: number) => void
  /** A take being moved: a draggable block in A2 (pointer drag, Arrow keys ±0.1 s, Shift ±1 s). */
  placing?: { start: number; duration: number } | null
  onPlace?: (start: number) => void
  /** As shot (2026-10-19): the added lines are not in this version, so A2 greys out. */
  asShot?: boolean
}

/** The ruler: a label every `step` seconds, chosen so there are about five,
 *  and the end. Player's logic, kept local so the lanes stand on their own. */
const RULER_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]
function rulerMarks(length: number): { at: number; label: string }[] {
  if (!(length > 0)) return []
  const step = RULER_STEPS.find((s) => length / s <= 5.5) ?? 600
  const marks: { at: number; label: string }[] = []
  // The last regular label gives way to the end label when they would touch.
  for (let t = 0; t < length - Math.max(step * 0.2, length * 0.06); t += step) {
    marks.push({ at: t, label: step < 1 ? `${clock(t)}.${Math.round((t % 1) * 10)}` : clock(t) })
  }
  const tenth = Math.round((length % 1) * 10)
  marks.push({ at: length, label: length < 10 && tenth > 0 && tenth < 10 ? `${clock(length)}.${tenth}` : clock(Math.round(length)) })
  return marks
}

/** The mixes that add a line beside the speech rather than changing it. */
const ADDS: ReadonlySet<Mix> = new Set<Mix>(['layer', 'over', 'concatenate'])
/** The item states that are on the table: proposed, being voiced, stuck. */
const LIVE: ReadonlySet<ItemStatus> = new Set<ItemStatus>(['ready', 'working', 'needs-you', 'failed'])

interface Span { start: number; end: number }
const overlaps = (a: Span, b: Span) => a.start < b.end && b.start < a.end

const SPEAKER_TONES: Record<string, string> = {
  a: 'border-spk-a bg-spk-a/25',
  b: 'border-spk-b bg-spk-b/25',
  c: 'border-spk-c bg-spk-c/25',
  d: 'border-spk-d bg-spk-d/25',
  x: 'border-muted-foreground bg-muted-foreground/25',
}
// Volt: a line in the video is ink on the lane, a proposal volt with an ink edge, a stuck one amber.
const TONES = {
  ok: 'border-foreground bg-foreground text-background',
  changed: 'border-ink bg-volt text-ink',
  needs: 'border-ink bg-warn text-ink',
  plain: 'border-transparent bg-lane text-foreground',
} as const
type Tone = keyof typeof TONES

/** A pill is never thinner than this, so a held frame or a one-word line can still be seen and clicked. */
const MIN_WIDTH_PCT = 0.6
const clampPct = (v: number) => Math.min(100, Math.max(0, v))

/** Where a span sits on the lane, as percentages of the source's length. */
const place = (duration: number, start: number, end: number) => {
  if (!(duration > 0)) return { left: 0, width: MIN_WIDTH_PCT }
  const left = clampPct((start / duration) * 100)
  const right = clampPct((end / duration) * 100)
  const width = Math.max(MIN_WIDTH_PCT, right - left)
  return { left: Math.min(left, 100 - width), width }
}

/** Greedy interval packing: sorted by start, each span takes the first
 *  sub-row whose last end is at or before its start, else a new sub-row. */
export function packRows<T extends Span>(spans: T[]): T[][] {
  const rows: { end: number; items: T[] }[] = []
  for (const s of [...spans].sort((a, b) => a.start - b.start || a.end - b.end)) {
    const row = rows.find((r) => r.end <= s.start)
    if (row) {
      row.items.push(s)
      row.end = Math.max(row.end, s.end)
    } else rows.push({ end: s.end, items: [s] })
  }
  return rows.map((r) => r.items)
}

/** "+8%" for 1.08, "−8%" for 0.92 — a true minus, as the type sets numbers. */
const flexPct = (factor: number | null) => {
  const pct = Math.round(((factor ?? 1) - 1) * 100)
  return `${pct < 0 ? '−' : '+'}${Math.abs(pct)}%`
}
/** "0.6 s": the seconds a frame is held, to the hundredth, trailing zeros dropped. */
const heldFor = (p: Piece) => `${Math.round((p.out_end - p.out_start) * 100) / 100} s`
/** "−12 dB" for a line mixed under the words. */
const levelTag = (db: number) => `−${Math.round(Math.abs(db))} dB`

const ROW = 'relative h-7 pointer-coarse:h-12'

interface PillProps {
  at: { left: number; width: number }
  tone: string
  label: string
  title: string
  onClick: () => void
  className?: string
  testid?: string
  children: ReactNode
  /** data-state, data-kind: what the pill is, for styling hooks and tests. */
  [data: `data-${string}`]: string | undefined
}

/** One span on a lane: a real button, named for a screen reader, titled with the full text. */
function Pill({ at, tone, label, title, onClick, className, testid = 'pill', children, ...data }: PillProps) {
  return (
    <button
      {...data}
      type="button"
      className={cn(
        'grow absolute inset-y-0.5 flex min-h-6 min-w-0 items-center gap-1 overflow-hidden rounded-sm border px-1.5 text-left font-mono text-xs whitespace-nowrap outline-none hover:z-10 focus-visible:z-10 focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:min-h-11',
        tone, className,
      )}
      style={{ left: `${at.left}%`, width: `${at.width}%` }}
      aria-label={label}
      title={title}
      data-testid={testid}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

/** A lane: its label in the left column, its body (the track) filling the rest. */
function Lane({ id, label, bodyRef, children, muted }: { id: string; label: string; bodyRef?: Ref<HTMLDivElement>; children: ReactNode; muted?: boolean }) {
  const labelId = useId()
  return (
    <div className={cn('flex items-stretch gap-2 transition-opacity', muted && 'opacity-40 grayscale')} role="group" aria-labelledby={labelId} data-testid={`lane-${id}`} data-muted={muted || undefined}>
      <div id={labelId} className="lane-n flex w-20 shrink-0 items-center whitespace-nowrap">{label}{muted && <span className="sr-only"> (not in this version)</span>}</div>
      <div ref={bodyRef} className="relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-md bg-sunk/60">{children}</div>
    </div>
  )
}

/** The playhead, drawn through a lane. */
const Head = ({ pct, testid = 'lane-head', className }: { pct: number; testid?: string; className?: string }) => (
  <span className={cn('pointer-events-none absolute inset-y-0 z-20 -ml-px w-0.5 bg-foreground', className)} data-testid={testid} style={{ left: `${pct}%` }} aria-hidden="true" />
)

/** A line in A2: in the video, or proposed, being voiced, stuck. */
interface Added extends Span {
  key: string
  text: string
  tone: Tone
  state: 'added' | 'proposed' | 'voicing' | 'needs-you' | 'failed'
  level: number | null
}
const ADDED_WORD: Record<Added['state'], string> = {
  added: 'Added', proposed: 'Proposed', voicing: 'Voicing…', 'needs-you': 'Needs you', failed: 'Failed',
}
const ADDED_NAME: Record<Added['state'], string> = {
  added: 'Added line', proposed: 'Proposed line', voicing: 'Voicing line', 'needs-you': 'Line needing you', failed: 'Failed line',
}

export function Lanes({
  duration, currentTime, statements, placedAt = [], speakers, revisions, items, pieces = [], onSeek, placing, onPlace, asShot,
}: LanesProps) {
  const addedRef = useRef<HTMLDivElement>(null)
  const at = (start: number, end: number) => place(duration, start, end)
  const head = duration > 0 ? clampPct((currentTime / duration) * 100) : 0

  /** The speaker's name; an unnamed one is Speaker 1, 2, 3 in order of appearance (20e). */
  const name = (label?: string | null) => {
    if (!label) return 'Speaker'
    const sp = speakers.find((s) => s.label === label)
    if (sp?.name) return sp.name
    const order = speakers.length ? speakers.map((x) => x.label) : ([...new Set(statements.map((st) => st.speaker).filter(Boolean))] as string[])
    const n = order.indexOf(label)
    return `Speaker ${n >= 0 ? n + 1 : label}`
  }

  // A1: what stands on each spoken line now.
  const removals = revisions.filter((r) => r.mix === 'remove')
  const replacements = revisions.filter((r) => r.mix === 'replace')
  const lineItems = items.filter((i) => (i.mix === 'replace' || i.mix === 'remove') && LIVE.has(i.status))
  type Standing = { kind: 'as-shot' } | { kind: 'removed' } | { kind: 'changed'; text: string } | { kind: 'removing' }
  const standing = (s: Statement): Standing => {
    if (removals.some((r) => overlaps(r, s))) return { kind: 'removed' }
    const replaced = replacements.filter((r) => overlaps(r, s))
    if (replaced.length) return { kind: 'changed', text: replaced[replaced.length - 1].text }
    const item = lineItems.find((i) => overlaps(i.selection, s))
    if (item?.mix === 'replace') return { kind: 'changed', text: item.candidate?.plan.new_text ?? item.new_text }
    if (item?.mix === 'remove') return { kind: 'removing' }
    return { kind: 'as-shot' }
  }

  // A2: every added line in the video and every proposed or working one, packed so none hides another.
  const added: Added[] = [
    ...revisions
      .filter((r) => ADDS.has(r.mix) && !r.partner)
      .map((r, i): Added => ({ key: `rev-${r.edit_id ?? i}`, start: r.start, end: r.end, text: r.text, tone: 'ok', state: 'added', level: r.level_db ?? null })),
    ...items
      .filter((i) => ADDS.has(i.mix) && LIVE.has(i.status))
      .map((i): Added => {
        const c = i.candidate
        const start = c ? c.plan.selection.start : i.selection.start
        const end = c ? start + c.audio.duration : i.selection.end
        const state: Added['state'] = i.status === 'ready' ? 'proposed' : i.status === 'working' ? 'voicing' : i.status === 'needs-you' ? 'needs-you' : 'failed'
        const tone: Tone = state === 'proposed' || state === 'voicing' ? 'changed' : 'needs'
        return { key: `item-${i.item_id}`, start, end, text: c?.plan.new_text ?? i.new_text, tone, state, level: c?.plan.level_db ?? null }
      }),
  ]
  const subRows = packRows(added)

  // The take being placed: dragged along A2; the pointer's offset inside it is kept.
  const startPlacing = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!placing || !onPlace || !addedRef.current) return
    e.preventDefault()
    const rect = addedRef.current.getBoundingClientRect()
    const grabbed = ((e.clientX - rect.left) / rect.width) * duration - placing.start
    const move = (ev: PointerEvent) => {
      const t = ((ev.clientX - rect.left) / rect.width) * duration - grabbed
      onPlace(Math.round(Math.min(Math.max(0, t), Math.max(0, duration - placing.duration)) * 100) / 100)
    }
    const end = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
  }

  const marks = rulerMarks(duration)
  const time = (t: number) => <span className="tnum font-mono">{clock(t)}</span>

  return (
    <section className="flex flex-col gap-1.5 text-xs" aria-label="Lanes" data-testid="lanes">
      {/* The ruler: the marks, the playhead, and the real range input laid
          invisibly over it so a click there is a seek and a keyboard user has a slider. */}
      <div className="flex items-stretch gap-2">
        <div className="w-20 shrink-0" aria-hidden="true" />
        <div className="relative h-5 min-w-0 flex-1">
          <div className="tnum relative h-full font-mono text-xs whitespace-nowrap text-muted-foreground" aria-hidden="true" data-testid="ruler">
            {marks.map((m, i, all) => (
              <span
                key={i}
                className={cn('absolute top-0 -translate-x-1/2', i === 0 && 'translate-x-0', i === all.length - 1 && '-translate-x-full')}
                data-end={i === all.length - 1 || undefined}
                style={{ left: `${duration > 0 ? clampPct((m.at / duration) * 100) : 0}%` }}>{m.label}</span>
            ))}
          </div>
          <Head pct={head} testid="head" />
          <input
            // Invisible over the ruler, but a keyboard user sees it focused.
            className="absolute inset-0 z-20 m-0 size-full cursor-pointer opacity-0 focus-visible:opacity-100 focus-visible:ring-[3px] focus-visible:ring-ring/50"
            type="range"
            min={0}
            max={Math.max(duration, 0)}
            step={0.01}
            value={Math.min(Math.max(0, currentTime), Math.max(duration, 0))}
            onChange={(e) => onSeek(Number(e.target.value))}
            aria-label="Seek"
            aria-valuetext={`${clock(currentTime)} of ${clock(duration)}`}
          />
        </div>
      </div>

      {/* V1: the picture, piece by piece — as shot, slowed or sped a touch, or a frame held. */}
      <Lane id="v1" label="V1 Pic">
        <div className={ROW}>
          {pieces.length === 0 ? (
            <Pill at={at(0, duration)} tone={TONES.plain} label={`Picture as shot at ${clock(0)}`} title="As shot" onClick={() => onSeek(0)} testid="piece">
              As shot
            </Pill>
          ) : pieces.map((p, i) => {
            const label = p.kind === 'flex' ? `Flexed ${flexPct(p.factor)}` : p.kind === 'copy' ? 'As shot' : `Held ${heldFor(p)}`
            const said = p.kind === 'flex' ? `Picture flexed ${flexPct(p.factor)}` : p.kind === 'copy' ? 'Picture as shot' : `Picture held ${heldFor(p)}`
            return (
              <Pill key={i} at={at(p.start, p.end)} tone={p.kind === 'copy' ? TONES.plain : TONES.changed} label={`${said} at ${clock(p.start)}`} title={label} onClick={() => onSeek(p.start)} testid="piece" data-kind={p.kind}>
                <span className="truncate">{label}</span>
              </Pill>
            )
          })}
          <Head pct={head} className="bg-foreground/50" />
        </div>
      </Lane>

      {/* A1: the spoken lines, by speaker; a removed one struck through, a changed one lit with its new words. */}
      {statements.length > 0 && (
        <Lane id="a1" label="A1 Said">
          <div className={ROW}>
            {statements.map((s, i) => {
              const who = name(s.speaker)
              const st = standing(s)
              const tone = st.kind === 'changed' || st.kind === 'removing' ? TONES.changed : SPEAKER_TONES[speakerSlot(speakers, s.speaker)]
              const label =
                st.kind === 'removed' ? `Removed line at ${clock(s.start)}, ${who}`
                  : st.kind === 'changed' ? `Changed line at ${clock(s.start)}, ${who}: ${st.text}`
                    : st.kind === 'removing' ? `Spoken line at ${clock(s.start)}, ${who}, removal proposed`
                      : `Spoken line at ${clock(s.start)}, ${who}`
              const title = st.kind === 'changed' ? st.text : s.text
              return (
                <Pill key={i} at={at(placedAt[i]?.start ?? s.start, placedAt[i]?.end ?? s.end)} tone={tone} label={label} title={title} onClick={() => onSeek(placedAt[i]?.start ?? s.start)} data-moved={placedAt[i] && Math.abs(placedAt[i]!.start - s.start) > 0.005 ? true : undefined} className={cn(st.kind === 'removed' && 'text-muted-foreground line-through')} data-state={st.kind}>
                  <span className="shrink-0">{who} {time(s.start)}</span>
                  {st.kind === 'removed' && <span className="truncate">Removed</span>}
                  {st.kind === 'removing' && <span className="truncate">Removal proposed</span>}
                  {st.kind === 'changed' && <span className="truncate">{st.text}</span>}
                </Pill>
              )
            })}
            <Head pct={head} className="bg-foreground/50" />
          </div>
        </Lane>
      )}

      {/* A2: the added lines. Overlapping ones take their own sub-rows, so
          coexisting audio is seen as such; the take being placed rides on top. */}
      <Lane id="a2" label="A2 Added" bodyRef={addedRef} muted={asShot}>
        {placing && duration > 0 && (
          <div className={ROW} data-testid="placing-row">
            <div
              className="absolute inset-y-0.5 z-30 min-h-6 cursor-grab touch-none rounded-sm border border-changed bg-changed-soft outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 active:cursor-grabbing pointer-coarse:min-h-11"
              data-testid="placing"
              role="slider"
              aria-label="Where the take starts"
              aria-valuemin={0}
              aria-valuemax={duration}
              aria-valuenow={placing.start}
              aria-valuetext={`${placing.start.toFixed(2)} seconds`}
              tabIndex={0}
              style={{ left: `${clampPct((placing.start / duration) * 100)}%`, width: `${Math.max(MIN_WIDTH_PCT, (placing.duration / duration) * 100)}%` }}
              onPointerDown={startPlacing}
              onKeyDown={(e) => {
                if (!onPlace) return
                if (e.key === 'ArrowLeft') { e.preventDefault(); onPlace(Math.max(0, placing.start - (e.shiftKey ? 1 : 0.1))) }
                if (e.key === 'ArrowRight') { e.preventDefault(); onPlace(Math.min(Math.max(0, duration - placing.duration), placing.start + (e.shiftKey ? 1 : 0.1))) }
              }}
            />
            <Head pct={head} className="bg-foreground/50" />
          </div>
        )}
        {subRows.length === 0 ? (
          <div className={ROW}>
            <p className="m-0 flex h-full items-center px-2 text-xs text-muted-foreground">Nothing added yet</p>
            <Head pct={head} className="bg-foreground/50" />
          </div>
        ) : subRows.map((row, r) => (
          <div key={r} className={ROW} data-testid="sublane">
            {row.map((a) => (
              <Pill key={a.key} at={at(a.start, a.end)} tone={TONES[a.tone]} label={`${ADDED_NAME[a.state]} at ${clock(a.start)}: ${a.text}`} title={a.text} onClick={() => onSeek(a.start)} data-state={a.state}>
                {a.state === 'voicing' && <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-changed" aria-hidden="true" data-testid="pulse" />}
                <span className="truncate"><span className="font-medium">{`${ADDED_WORD[a.state]} · `}</span>{a.text}</span>
                {a.level !== null && a.level < 0 && <span className="tnum ml-auto shrink-0 rounded-sm bg-card/70 px-1 font-mono" data-testid="level">{levelTag(a.level)}</span>}
              </Pill>
            ))}
            <Head pct={head} className="bg-foreground/50" />
          </div>
        ))}
      </Lane>

      {/* A3: room tone laid under each removal, so the cut does not go dead. */}
      {removals.length > 0 && (
        <Lane id="a3" label="A3 Tone">
          <div className={ROW}>
            {removals.map((r, i) => (
              <Pill key={r.edit_id ?? i} at={at(r.start, r.end)} tone={TONES.ok} label={`Room tone at ${clock(r.start)}`} title="Tone patch" onClick={() => onSeek(r.start)}>
                <span className="truncate">Tone patch</span>
              </Pill>
            ))}
            <Head pct={head} className="bg-foreground/50" />
          </div>
        </Lane>
      )}
    </section>
  )
}
