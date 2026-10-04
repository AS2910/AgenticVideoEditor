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
  /** Ship the lines kept; the rest stay as drafts (UX-3). */
  onShip: (itemIds: string[]) => void
  /** Undo a shipped line: it goes back to a draft. */
  onUndo?: (item: PlanItem) => void
  onBack: () => void
}

const WORDS: Record<number, string> = { 1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six' }
const count = (n: number, word: string) => `${WORDS[n] ?? n} ${n === 1 ? word : `${word}s`}`

/** Screen W5 (UX-3): every finished change, before and after, with its take
 *  and a verdict; Keep or Hold each; Ship sends the kept ones and holds the
 *  rest as drafts. A shipped line keeps Undo. */
export function ReviewPanel({ plan, speakers, projectId, busy, onCompare, onRedo, onShip, onUndo, onBack }: ReviewPanelProps) {
  const [open, setOpen] = useState<string | null>(null)
  const items = plan.items.filter((i) => i.kind === 'planned' && (i.status === 'ready' || i.status === 'approved'))
  const ready = items.filter((i) => i.status === 'ready')
  const shipped = items.filter((i) => i.status === 'approved')
  // Held by choice; a take that failed the sound check starts held.
  const [held, setHeld] = useState<Set<string>>(() => new Set(ready.filter((i) => i.candidate && !i.candidate.continuity.passed).map((i) => i.item_id)))
  const kept = ready.filter((i) => !held.has(i.item_id))
  const passed = ready.filter((i) => i.candidate?.continuity.passed).length
  const name = (item: PlanItem) => speakers.find((s) => s.label === item.speaker)?.name ?? (item.speaker ? `Speaker ${item.speaker}` : null)
  const after = (item: PlanItem) =>
    item.mix === 'concatenate' || item.mix === 'over' ? `${item.old_text} ${item.new_text}` : item.new_text
  const toggle = (item: PlanItem, keep: boolean) =>
    setHeld((h) => { const next = new Set(h); if (keep) next.delete(item.item_id); else next.add(item.item_id); return next })

  const title = ready.length > 0
    ? `${count(ready.length, 'change')}, ready to ship`
    : `${count(shipped.length, 'change')} shipped`
  const sub = ready.length === 0 ? (shipped.length > 0 ? 'Undo any line to hold it back as a draft.' : 'Nothing to ship yet.')
    : held.size > 0 ? `${kept.length} kept, ${held.size} held as ${held.size === 1 ? 'a draft' : 'drafts'}.`
    : passed === ready.length ? `${ready.length === 1 ? 'It sounds' : 'All of them sound'} right. Hear each seam, then ship.`
    : `${passed} of ${ready.length} sound right. Hear each seam before you ship.`

  return (
    <section className={styles.review} aria-label="Review">
      <div className={styles.head}>
        <h1 className={styles.title}>{title}</h1>
        <span className={styles.sub}>{sub}</span>
        <span className={styles.spacer} />
        <button className={styles.back} onClick={onBack}>Back to the transcript</button>
        {ready.length > 0 && (
          <button className={styles.approve} onClick={() => onShip(kept.map((i) => i.item_id))} disabled={busy || kept.length === 0}>
            {kept.length === ready.length ? 'Ship it' : `Ship ${kept.length} of ${ready.length}`}
          </button>
        )}
      </div>

      {items.map((item) => {
        const score = soundsRight(item)
        const label = name(item)
        const isHeld = held.has(item.item_id)
        return (
          <div key={item.item_id} className={styles.row} data-testid="review-row" data-held={isHeld || undefined}>
            <div className={styles.when}>
              <span>{clock(item.selection.start)}</span>
              {label && <Avatar name={label} slot={speakerSlot(speakers, item.speaker)} />}
            </div>
            <div className={styles.col}>
              <span className={styles.caption}>Before</span>
              <span className={styles.before}>{item.old_text}</span>
            </div>
            <div className={styles.col}>
              <span className={styles.caption}>After{label ? `, ${label}` : ''}</span>
              <span className={styles.after}>
                {diffWords(item.old_text, after(item)).map((run, k) => (
                  <Fragment key={k}>
                    {k > 0 && ' '}
                    {run.kind === 'same' && <span>{run.text}</span>}
                    {run.kind === 'del' && <del className={styles.del}>{run.text}</del>}
                    {run.kind === 'ins' && <ins className={styles.ins}>{run.text}</ins>}
                  </Fragment>
                ))}
              </span>
              {item.mix === 'concatenate' && item.candidate && (
                <span className={styles.note}>Added after the line; the video holds the frame for {item.candidate.audio.duration.toFixed(1)} s.</span>
              )}
              {item.note && item.mix !== 'concatenate' && <span className={styles.note}>{item.note}{/[.!?]$/.test(item.note) ? '' : '.'}</span>}
            </div>
            <div className={styles.actions}>
              <div className={styles.buttons}>
                <button
                  className={styles.compare}
                  aria-pressed={open === item.item_id}
                  onClick={() => { setOpen(open === item.item_id ? null : item.item_id); onCompare(item) }}
                >
                  <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1l8 5-8 5z" fill="currentColor" /></svg>
                  Hear the seam
                </button>
                {item.status === 'ready' && (
                  <button className={styles.redo} onClick={() => onRedo(item)} disabled={busy}>Redo</button>
                )}
              </div>
              {open === item.item_id && item.candidate && (
                <audio controls autoPlay className={styles.audio} src={artifactUrl(projectId, item.candidate.audio.sha256)} aria-label="The take" />
              )}
              {item.status === 'approved' ? (
                <div className={styles.decision}>
                  <span className={styles.shipped}>Shipped</span>
                  {onUndo && <button className={styles.undo} onClick={() => onUndo(item)} disabled={busy}>Undo</button>}
                </div>
              ) : (
                <div className={styles.decision} role="group" aria-label={`Keep or hold the change at ${clock(item.selection.start)}`}>
                  <button className={isHeld ? styles.choice : styles.choiceOn} aria-pressed={!isHeld} onClick={() => toggle(item, true)}>Keep</button>
                  <button className={isHeld ? styles.choiceOn : styles.choice} aria-pressed={isHeld} onClick={() => toggle(item, false)}>Hold</button>
                  {score !== null ? (
                    <span className={styles.score}>sounds right <strong>{score.toFixed(2)}</strong></span>
                  ) : <span className={styles.score}>Not measured</span>}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </section>
  )
}
