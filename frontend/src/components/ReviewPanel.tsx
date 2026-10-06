import { Fragment, useState } from 'react'
import type { Plan, PlanItem, Speaker } from '../types'
import { artifactUrl } from '../api'
import { diffWords } from '../transcript/changes'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { Avatar } from './Avatar'
import { soundsRight } from '../transcript/planText'
import styles from './ReviewPanel.module.css'

interface ReviewPanelProps {
  plan: Plan
  speakers: Speaker[]
  projectId: string
  busy?: boolean
  /** Play the edited video across the seam: a moment before the line to a
   *  moment after, where a pasted edit gives itself away. */
  onCompare: (item: PlanItem) => void
  onRedo: (item: PlanItem) => void
  /** Undo a shipped line: it goes back to a draft. */
  onUndo?: (item: PlanItem) => void
  /** Held back as a draft, by choice or because its sound check failed. */
  isHeld: (item: PlanItem) => boolean
  onDecide: (item: PlanItem, keep: boolean) => void
}

/** Every finished change, as the script filtered to what changed (UX-7d,
 *  from the review screen of UX-3): Before and After stacked, the seam to
 *  play, the verdict as a sentence with the score behind it, Keep or Hold.
 *  A shipped line keeps Undo. The Ship button in the bar counts the kept. */
export function ReviewPanel({ plan, speakers, projectId, busy, onCompare, onRedo, onUndo, isHeld, onDecide }: ReviewPanelProps) {
  const [open, setOpen] = useState<string | null>(null)
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

  const sub = ready.length === 0 ? (shipped.length > 0 ? 'Shipped. Undo any line to hold it back as a draft.' : 'Nothing to ship yet.')
    : held.length > 0 ? `${kept.length} kept, ${held.length} held as ${held.length === 1 ? 'a draft' : 'drafts'}.`
    : passed === ready.length ? `${ready.length === 1 ? 'It sounds' : 'All of them sound'} right. Play each seam, then ship.`
    : `${passed} of ${ready.length} sound right. Play each seam before you ship.`

  return (
    <div className={styles.review} data-testid="review">
      <div className={styles.sub} role="status">{sub}</div>
      {items.map((item) => {
        const score = soundsRight(item)
        const label = name(item)
        const isHeldNow = isHeld(item)
        const removed = item.mix === 'remove'
        return (
          <div key={item.item_id} className={styles.row} data-testid="review-row" data-held={isHeldNow || undefined}>
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
                  aria-pressed={open === item.item_id}
                  onClick={() => { setOpen(open === item.item_id ? null : item.item_id); onCompare(item) }}
                >
                  <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1l8 5-8 5z" fill="currentColor" /></svg>
                  Play the seam
                </button>
                {item.status === 'ready' && (
                  score !== null ? (
                    <span className={styles.score}>sounds right <strong>{score.toFixed(2)}</strong></span>
                  ) : <span className={styles.score}>Not measured</span>
                )}
                {item.status === 'ready' && isHeldNow && (
                  <span className={styles.heldNote}>Held: the line ships as shot, and this change waits as a draft.</span>
                )}
              </div>
              {open === item.item_id && item.candidate && (
                <audio controls autoPlay className={styles.audio} src={artifactUrl(projectId, item.candidate.audio.sha256)} aria-label="The take" />
              )}
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
          </div>
        )
      })}
    </div>
  )
}
