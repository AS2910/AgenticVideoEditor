import { Fragment, useState } from 'react'
import type { Candidate, Plan, PlanItem, Speaker } from '../types'
import { diffWords } from '../transcript/changes'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { Avatar } from './Avatar'
import { soundsRight } from '../transcript/planText'
import styles from './ReviewPanel.module.css'

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

const PlayIcon = () => <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1l8 5-8 5z" fill="currentColor" /></svg>
const StopIcon = () => <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><rect x="1" y="1" width="8" height="8" rx="1.5" fill="currentColor" /></svg>

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
    <div className={styles.review} data-testid="review" onFocusCapture={() => setFocused(true)} onBlurCapture={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false) }}>
      <div className={styles.sub} role="status">{sub}</div>
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
            className={styles.row}
            data-testid="review-row"
            data-held={isHeldNow || undefined}
            data-playing={playing ? 'true' : undefined}
            aria-label={`Line ${lineNumber(item)} at ${clock(item.selection.start)}${label ? `, ${label}` : ''}${item.status === 'approved' ? ', shipped' : isHeldNow ? ', held' : ', kept'}`}
            onKeyDown={(e) => onRowKey(e, index)}
          >
            <span className={styles.when}>{clock(item.selection.start)}</span>
            <div className={styles.body}>
              <span className={styles.who}>
                {label && <Avatar name={label} slot={speakerSlot(speakers, item.speaker)} size={18} />}
                Line {lineNumber(item)}{label ? ` · ${label}` : ''}{removed ? ' · removed' : ''}
              </span>
              <span className={styles.words}><span className={styles.cap}>Before</span><span className={styles.before}>{item.old_text}</span></span>
              <span className={styles.words}>
                <span className={styles.cap}>After</span>
                <span className={styles.after}>
                  {removed ? <span className={styles.before}>(the room's own quiet)</span> : diffWords(item.old_text, after(item)).map((run, k) => (
                    <Fragment key={k}>
                      {k > 0 && ' '}
                      {run.kind === 'same' && <span>{run.text}</span>}
                      {run.kind === 'del' && <del className={styles.del}>{run.text}</del>}
                      {run.kind === 'ins' && <ins className={styles.ins}>{run.text}</ins>}
                    </Fragment>
                  ))}
                </span>
              </span>
              {item.mix === 'concatenate' && item.candidate && (
                <span className={styles.note}>Added after the line; the video holds the frame for {item.candidate.audio.duration.toFixed(1)} s.</span>
              )}
              {item.note && item.mix !== 'concatenate' && <span className={styles.note}>{item.note}{/[.!?]$/.test(item.note) ? '' : '.'}</span>}
              <div className={styles.verdictRow}>
                <button
                  className={styles.compare}
                  aria-pressed={playing !== null}
                  aria-label={playing ? `Stop the seam at ${clock(item.selection.start)}` : `Play the seam at ${clock(item.selection.start)}`}
                  onClick={() => toggleSeam(item)}
                >
                  {playing ? <StopIcon /> : <PlayIcon />}
                  {playing ? 'Stop' : 'Play the seam'}
                </button>
                {item.candidate && !removed && (
                  <button
                    className={styles.compare}
                    aria-pressed={hearing}
                    aria-label={hearing ? `Stop the take at ${clock(item.selection.start)}` : `Hear the take at ${clock(item.selection.start)} alone`}
                    onClick={() => onPlayTake(item.candidate!)}
                  >
                    {hearing ? <StopIcon /> : <PlayIcon />}
                    {hearing ? 'Stop' : 'Hear the take'}
                  </button>
                )}
                {item.status === 'ready' && (
                  score !== null ? (
                    <span className={styles.score}>sounds right <strong>{score.toFixed(2)}</strong></span>
                  ) : <span className={styles.score}>Not measured</span>
                )}
                {item.status === 'ready' && isHeldNow && (
                  <span className={styles.heldNote}>Held: the line ships as shot, and this change waits as a draft.</span>
                )}
              </div>
            </div>
            <div className={styles.state}>
              {item.status === 'approved' ? (
                <>
                  <span className={styles.shipped}>Shipped</span>
                  {onUndo && <button className={styles.quiet} onClick={() => onUndo(item)} disabled={busy}>Undo</button>}
                </>
              ) : (
                <>
                  <div className={styles.seg} role="group" aria-label={`Keep or hold the change at ${clock(item.selection.start)}`}>
                    <button className={isHeldNow ? styles.choice : styles.choiceOn} aria-pressed={!isHeldNow} onClick={() => onDecide(item, true)}>Keep</button>
                    <button className={isHeldNow ? styles.choiceOn : styles.choice} aria-pressed={isHeldNow} onClick={() => onDecide(item, false)}>Hold</button>
                  </div>
                  <button className={styles.quiet} onClick={() => onRedo(item)} disabled={busy}>Another take</button>
                </>
              )}
            </div>
            {playing && (
              <span className={styles.seamLine} aria-hidden="true" data-testid="seam-progress">
                <span className={styles.seamFill} style={{ transform: `scaleX(${progress})` }} />
              </span>
            )}
          </div>
        )
      })}
      </div>
      {items.length > 0 && (
        <div className={styles.foot}>
          <span className={styles.keys} data-testid="review-keys" hidden={!focused}>
            <kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Space</kbd> play the seam · <kbd>T</kbd> hear the take · <kbd>K</kbd> keep · <kbd>H</kbd> hold · <kbd>A</kbd> another take{shipped.length > 0 && <> · <kbd>U</kbd> undo</>}
          </span>
        </div>
      )}
    </div>
  )
}
