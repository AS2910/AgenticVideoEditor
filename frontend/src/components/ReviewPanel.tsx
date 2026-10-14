import { Fragment, useState } from 'react'
import type { Candidate, Plan, PlanItem, Speaker } from '../types'
import { diffWords } from '../transcript/changes'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { Avatar } from './Avatar'
import { soundsRight } from '../transcript/planText'
import { Play, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** The seam that is playing in the monitor: which row's, and how far along. */
export interface SeamPlaying { itemId: string; from: number; until: number; now: number }

interface ReviewPanelProps {
  plan: Plan
  speakers: Speaker[]
  busy?: boolean
  /** Play the edited video across the seam: a moment before the line to a
   *  moment after, where a pasted edit gives itself away. */
  onCompare: (item: PlanItem) => void
  /** Stop the seam that is playing. */
  onStop: () => void
  seam: SeamPlaying | null
  /** Hear the take alone, in place over the muted original; the id of the one playing. */
  onPlayTake: (c: Candidate) => void
  playingTake: string | null
  onRedo: (item: PlanItem) => void
  /** Undo a shipped line: it goes back to a draft. */
  onUndo?: (item: PlanItem) => void
  /** Held back as a draft, by choice or because its sound check failed. */
  isHeld: (item: PlanItem) => boolean
  onDecide: (item: PlanItem, keep: boolean) => void
}

const PlayIcon = () => <Play fill="currentColor" aria-hidden="true" />
const StopIcon = () => <Square fill="currentColor" aria-hidden="true" />

/** Every finished change, as the script filtered to what changed (UX-7d,
 *  from the review screen of UX-3): Before and After stacked, the seam to
 *  play, the verdict as a sentence with the score behind it, Keep or Hold.
 *  A shipped line keeps Undo. The Ship button in the bar counts the kept.
 *
 *  The polish pass gave each row a player and keys: *Play the seam* says Stop
 *  while its seam plays, with a thin line along the row's foot showing how
 *  far along it is; *Hear the take* plays the take alone, in place; a focused
 *  row answers ↑ ↓ Space T K H A U, like the transcript's rows do. */
export function ReviewPanel({
  plan, speakers, busy, onCompare, onStop, seam, onPlayTake, playingTake, onRedo, onUndo, isHeld, onDecide,
}: ReviewPanelProps) {
  const [focused, setFocused] = useState(false)
  const items = plan.items.filter((i) => i.kind === 'planned' && (i.status === 'ready' || i.status === 'approved'))
  const ready = items.filter((i) => i.status === 'ready')
  const shipped = items.filter((i) => i.status === 'approved')
  const held = ready.filter(isHeld)
  const kept = ready.filter((i) => !isHeld(i))
  const passed = ready.filter((i) => i.candidate?.continuity.passed).length
  const name = (item: PlanItem) => speakers.find((s) => s.label === item.speaker)?.name ?? (item.speaker ? `Speaker ${item.speaker}` : null)
  const after = (item: PlanItem) =>
    item.mix === 'concatenate' || item.mix === 'over' ? `${item.old_text} ${item.new_text}` : item.new_text
  const lineNumber = (item: PlanItem) => {
    const planned = plan.items.filter((i) => i.kind === 'planned').sort((a, b) => a.selection.start - b.selection.start)
    return planned.findIndex((i) => i.item_id === item.item_id) + 1
  }
  const seamOf = (item: PlanItem) => (seam?.itemId === item.item_id ? seam : null)
  const toggleSeam = (item: PlanItem) => { if (seamOf(item)) onStop(); else onCompare(item) }

  const sub = ready.length === 0 ? (shipped.length > 0 ? 'Shipped. Undo any line to hold it back as a draft.' : 'Nothing to ship yet.')
    : held.length > 0 ? `${kept.length} kept, ${held.length} held as ${held.length === 1 ? 'a draft' : 'drafts'}.`
    : passed === ready.length ? `${ready.length === 1 ? 'It sounds' : 'All of them sound'} right. Play each seam, then ship.`
    : `${passed} of ${ready.length} sound right. Play each seam before you ship.`

  /** Keys on a focused row: only when the row itself has focus, never a control in it. */
  const onRowKey = (e: React.KeyboardEvent<HTMLDivElement>, index: number) => {
    if (e.target !== e.currentTarget) return
    const item = items[index]
    const move = (to: number) => {
      const row = document.getElementById(`review-${items[Math.max(0, Math.min(items.length - 1, to))].item_id}`)
      row?.focus()
      row?.scrollIntoView?.({ block: 'nearest' })
    }
    switch (e.key) {
      case 'ArrowDown': case 'j': e.preventDefault(); move(index + 1); break
      case 'ArrowUp': e.preventDefault(); move(index - 1); break
      case ' ': case 'Enter': e.preventDefault(); toggleSeam(item); break
      case 't': case 'T': if (item.candidate) { e.preventDefault(); onPlayTake(item.candidate) } break
      case 'k': case 'K': if (item.status === 'ready') { e.preventDefault(); onDecide(item, true) } break
      case 'h': case 'H': if (item.status === 'ready') { e.preventDefault(); onDecide(item, false) } break
      case 'a': case 'A': if (item.status === 'ready' && !busy) { e.preventDefault(); onRedo(item) } break
      case 'u': case 'U': if (item.status === 'approved' && onUndo && !busy) { e.preventDefault(); onUndo(item) } break
    }
  }

  return (
    <div className="flex flex-col" data-testid="review" onFocusCapture={() => setFocused(true)} onBlurCapture={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false) }}>
      <div className="px-2.5 pb-2.5 text-sm text-muted-foreground" role="status">{sub}</div>
      <div role="list" aria-label="The changes">
      {items.map((item, index) => {
        const score = soundsRight(item)
        const label = name(item)
        const isHeldNow = isHeld(item)
        const removed = item.mix === 'remove'
        const playing = seamOf(item)
        const progress = playing ? Math.min(1, Math.max(0, (playing.now - playing.from) / Math.max(0.01, playing.until - playing.from))) : 0
        const hearing = item.candidate != null && playingTake === item.candidate.candidate_id
        return (
          <div
            key={item.item_id}
            id={`review-${item.item_id}`}
            role="listitem"
            tabIndex={0}
            className={cn(
              'relative grid grid-cols-[44px_minmax(0,1fr)_auto] items-start gap-x-3.5 gap-y-2 rounded-lg border-t px-2.5 py-3.5 outline-none first:border-t-0 focus-visible:ring-[3px] focus-visible:ring-ring/50 max-[960px]:grid-cols-[44px_minmax(0,1fr)]',
              (playing || isHeldNow) && 'bg-muted/50',
            )}
            data-testid="review-row"
            data-held={isHeldNow || undefined}
            data-playing={playing ? 'true' : undefined}
            aria-label={`Line ${lineNumber(item)} at ${clock(item.selection.start)}${label ? `, ${label}` : ''}${item.status === 'approved' ? ', shipped' : isHeldNow ? ', held' : ', kept'}`}
            onKeyDown={(e) => onRowKey(e, index)}
          >
            <span className="tnum pt-1 text-sm text-muted-foreground">{clock(item.selection.start)}</span>
            <div className="flex min-w-0 flex-col gap-1.5">
              <span className="flex items-center gap-2 text-sm whitespace-nowrap text-muted-foreground">
                {label && <Avatar name={label} slot={speakerSlot(speakers, item.speaker)} size={18} />}
                Line {lineNumber(item)}{label ? ` · ${label}` : ''}{removed ? ' · removed' : ''}
              </span>
              <span className="flex items-baseline gap-2 text-base"><span className="w-13 flex-none text-sm text-muted-foreground">Before</span><span className="text-muted-foreground">{item.old_text}</span></span>
              <span className="flex items-baseline gap-2 text-base">
                <span className="w-13 flex-none text-sm text-muted-foreground">After</span>
                <span className="min-w-0">
                  {removed ? <span className="text-muted-foreground">(the room's own quiet)</span> : diffWords(item.old_text, after(item)).map((run, k) => (
                    <Fragment key={k}>
                      {k > 0 && ' '}
                      {run.kind === 'same' && <span>{run.text}</span>}
                      {run.kind === 'del' && <del className="text-muted-foreground decoration-destructive decoration-[1.5px]">{run.text}</del>}
                      {run.kind === 'ins' && <ins className="rounded-sm bg-changed-soft px-1 text-changed no-underline">{run.text}</ins>}
                    </Fragment>
                  ))}
                </span>
              </span>
              {item.mix === 'concatenate' && item.candidate && (
                <span className="text-sm text-muted-foreground">Added after the line; the picture makes {item.candidate.audio.duration.toFixed(1)} s of room.</span>
              )}
              {item.note && item.mix !== 'concatenate' && <span className="text-sm text-muted-foreground">{item.note}{/[.!?]$/.test(item.note) ? '' : '.'}</span>}
              <div className="mt-1 flex flex-wrap items-center gap-2.5">
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(playing && 'border-changed bg-changed-soft text-changed hover:bg-changed-soft')}
                  aria-pressed={playing !== null}
                  aria-label={playing ? `Stop the seam at ${clock(item.selection.start)}` : `Play the seam at ${clock(item.selection.start)}`}
                  onClick={() => toggleSeam(item)}
                >
                  {playing ? <StopIcon /> : <PlayIcon />}
                  {playing ? 'Stop' : 'Play the seam'}
                </Button>
                {item.candidate && !removed && (
                  <Button
                    variant="outline"
                    size="sm"
                    className={cn(hearing && 'border-changed bg-changed-soft text-changed hover:bg-changed-soft')}
                    aria-pressed={hearing}
                    aria-label={hearing ? `Stop the take at ${clock(item.selection.start)}` : `Hear the take at ${clock(item.selection.start)} alone`}
                    onClick={() => onPlayTake(item.candidate!)}
                  >
                    {hearing ? <StopIcon /> : <PlayIcon />}
                    {hearing ? 'Stop' : 'Hear the take'}
                  </Button>
                )}
                {item.status === 'ready' && (
                  score !== null ? (
                    <span className="tnum text-sm text-muted-foreground">sounds right <strong className="font-medium text-foreground">{score.toFixed(2)}</strong></span>
                  ) : <span className="text-sm text-muted-foreground">Not measured</span>
                )}
                {item.status === 'ready' && isHeldNow && (
                  <span className="text-sm text-needs">Held: the line ships as shot, and this change waits as a draft.</span>
                )}
              </div>
            </div>
            <div className="flex flex-col items-end gap-2 whitespace-nowrap max-[960px]:col-start-2 max-[960px]:flex-row max-[960px]:flex-wrap max-[960px]:items-center max-[960px]:justify-start">
              {item.status === 'approved' ? (
                <>
                  <span className="pt-2 text-sm font-medium text-ok">Shipped</span>
                  {onUndo && <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => onUndo(item)} disabled={busy}>Undo</Button>}
                </>
              ) : (
                <>
                  <div className="inline-flex gap-0.5 rounded-lg border bg-muted p-0.5" role="group" aria-label={`Keep or hold the change at ${clock(item.selection.start)}`}>
                    <Button variant={isHeldNow ? 'ghost' : 'default'} size="sm" aria-pressed={!isHeldNow} onClick={() => onDecide(item, true)}>Keep</Button>
                    <Button variant={isHeldNow ? 'default' : 'ghost'} size="sm" aria-pressed={isHeldNow} onClick={() => onDecide(item, false)}>Hold</Button>
                  </div>
                  <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => onRedo(item)} disabled={busy}>Another take</Button>
                </>
              )}
            </div>
            {playing && (
              <span className="absolute inset-x-2.5 bottom-0 h-0.5 overflow-hidden rounded-full bg-muted" aria-hidden="true" data-testid="seam-progress">
                <span className="block h-full w-full origin-left bg-primary transition-transform duration-100 ease-linear" style={{ transform: `scaleX(${progress})` }} />
              </span>
            )}
          </div>
        )
      })}
      </div>
      {items.length > 0 && (
        <div className="min-h-9 px-2.5 pt-2.5 pb-0.5 text-sm text-muted-foreground">
          <span className="whitespace-nowrap max-[960px]:hidden [&_kbd]:mx-px [&_kbd]:inline-block [&_kbd]:min-w-[18px] [&_kbd]:rounded-sm [&_kbd]:border [&_kbd]:border-b-2 [&_kbd]:bg-muted [&_kbd]:px-1 [&_kbd]:text-center [&_kbd]:font-sans [&_kbd]:text-xs" data-testid="review-keys" hidden={!focused}>
            <kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Space</kbd> play the seam · <kbd>T</kbd> hear the take · <kbd>K</kbd> keep · <kbd>H</kbd> hold · <kbd>A</kbd> another take{shipped.length > 0 && <> · <kbd>U</kbd> undo</>}
          </span>
        </div>
      )}
    </div>
  )
}
