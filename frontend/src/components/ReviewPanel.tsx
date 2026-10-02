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
  /** Jump the player to the line, so Compare has the original a click away. */
  onCompare: (item: PlanItem) => void
  onRedo: (item: PlanItem) => void
  onApproveAll: () => void
  onBack: () => void
}

/** Screen C: every finished change, before and after, with its take; one
 *  button approves them all and exports. */
export function ReviewPanel({ plan, speakers, projectId, busy, onCompare, onRedo, onApproveAll, onBack }: ReviewPanelProps) {
  const [open, setOpen] = useState<string | null>(null)
  const items = plan.items.filter((i) => i.kind === 'planned' && (i.status === 'ready' || i.status === 'approved'))
  const ready = items.filter((i) => i.status === 'ready')
  const passed = ready.filter((i) => i.candidate?.continuity.passed).length
  const name = (item: PlanItem) => speakers.find((s) => s.label === item.speaker)?.name ?? (item.speaker ? `Speaker ${item.speaker}` : null)
  const after = (item: PlanItem) =>
    item.mix === 'concatenate' ? `${item.old_text} ${item.new_text}` : item.new_text

  return (
    <section className={styles.review} aria-label="Review">
      <div className={styles.head}>
        <h1 className={styles.title}>
          {ready.length > 0
            ? `${ready.length} ${ready.length === 1 ? 'change is' : 'changes are'} ready`
            : `${items.length} ${items.length === 1 ? 'change' : 'changes'} approved`}
        </h1>
        <span className={styles.sub}>
          {ready.length === 0 ? 'Export when you are happy with it.'
            : passed === ready.length ? 'All passed the sound check. Listen to any of them, then approve.'
            : `${passed} of ${ready.length} passed the sound check. Listen before you approve.`}
        </span>
        <span className={styles.spacer} />
        <button className={styles.back} onClick={onBack}>Back to the transcript</button>
        {ready.length > 0 && (
          <button className={styles.approve} onClick={onApproveAll} disabled={busy}>
            Approve all {ready.length} and export
          </button>
        )}
      </div>

      {items.map((item) => {
        const score = soundsRight(item)
        const label = name(item)
        return (
          <div key={item.item_id} className={styles.row} data-testid="review-row">
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
              {item.note && item.mix !== 'concatenate' && <span className={styles.note}>{item.note}.</span>}
            </div>
            <div className={styles.actions}>
              <div className={styles.buttons}>
                <button
                  className={styles.compare}
                  aria-pressed={open === item.item_id}
                  onClick={() => { setOpen(open === item.item_id ? null : item.item_id); onCompare(item) }}
                >
                  <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1l8 5-8 5z" fill="currentColor" /></svg>
                  Compare
                </button>
                {item.status === 'ready' && (
                  <button className={styles.redo} onClick={() => onRedo(item)} disabled={busy}>Redo</button>
                )}
              </div>
              {open === item.item_id && item.candidate && (
                <audio controls autoPlay className={styles.audio} src={artifactUrl(projectId, item.candidate.audio.sha256)} aria-label="The take" />
              )}
              <span className={styles.score}>
                {item.status === 'approved' ? 'Approved' : score !== null ? <>Sounds right <strong>{score.toFixed(2)}</strong></> : 'Not measured'}
              </span>
            </div>
          </div>
        )
      })}
    </section>
  )
}
