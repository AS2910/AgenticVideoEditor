import { Fragment, useRef, useState } from 'react'
import type { PlanItem } from '../types'
import { diffWords } from '../transcript/changes'
import { clock } from '../transcript/format'
import { Orb } from './Orb'
import { useModal } from './useModal'
import styles from './ShipSheet.module.css'

export interface Shipped {
  /** The lines that went into this render. */
  items: PlanItem[]
  /** Lines held back as drafts. */
  held: number
  /** Removed lines in force (hands-on), counted for the file's contents. */
  removed: number
  before: number
  after: number
  download: { url: string; filename: string }
  spendUsd: number
  /** Voice calls made for the plan: how many takes it took (the polish pass). */
  takesVoiced?: number
}

interface ShipSheetProps {
  shipped: Shipped
  onVariant: () => void
  /** Undo a line that just shipped: it goes back to a draft. */
  onUndo?: (item: PlanItem) => void
  onClose: () => void
  busy?: boolean
}

const after = (item: PlanItem) =>
  item.mix === 'concatenate' || item.mix === 'over' ? `${item.old_text} ${item.new_text}` : item.new_text

/** The receipt (UX-7d, from the ship sheet of UX-3): what is in the file as
 *  stat tiles and as the lines themselves, what was held, the stand-in voice
 *  said plainly, then Download, Copy link, Make a variant. */
export function ShipSheet({ shipped, onVariant, onUndo, onClose, busy }: ShipSheetProps) {
  const [copied, setCopied] = useState<boolean | 'failed'>(false)
  const sheet = useRef<HTMLDivElement>(null)
  useModal(sheet, onClose)
  const changed = shipped.items.filter((i) => i.mix === 'replace').length
  const added = shipped.items.filter((i) => i.mix !== 'replace' && i.mix !== 'remove').length
  const removed = shipped.items.filter((i) => i.mix === 'remove').length + shipped.removed
  const longer = shipped.after - shipped.before
  const length = Math.abs(longer) < 0.05
    ? `Same length as before, ${shipped.after.toFixed(1)} seconds.`
    : `${Math.abs(longer).toFixed(1)} s ${longer > 0 ? 'longer' : 'shorter'}: ${shipped.before.toFixed(1)} → ${shipped.after.toFixed(1)} seconds.`
  const link = new URL(shipped.download.url, window.location.origin).toString()
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
    } catch {
      setCopied('failed')
    }
  }
  const tiles: { n: string; label: string }[] = [
    { n: String(changed), label: changed === 1 ? 'line changed' : 'lines changed' },
    ...(added > 0 ? [{ n: String(added), label: added === 1 ? 'line added' : 'lines added' }] : []),
    ...(removed > 0 ? [{ n: String(removed), label: removed === 1 ? 'line removed' : 'lines removed' }] : []),
    { n: String(shipped.held), label: shipped.held === 1 ? 'held as a draft' : 'held as drafts' },
    ...(shipped.takesVoiced ? [{ n: String(shipped.takesVoiced), label: shipped.takesVoiced === 1 ? 'take voiced' : 'takes voiced' }] : []),
    { n: `$${shipped.spendUsd.toFixed(2)}`, label: 'for this plan' },
  ]
  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="ship-title">
      <div ref={sheet} className={styles.sheet} data-testid="ship-sheet">
        <div className={styles.head}>
          <Orb size={28} />
          <div>
            <h2 id="ship-title" className={styles.title}>It's shipped.</h2>
            <p className={styles.lead}>{length}</p>
          </div>
        </div>
        <dl className={styles.tiles} aria-label="What is in the file, counted">
          {tiles.map((t) => (
            <div key={t.label} className={styles.tile}><dd className={styles.tileN}>{t.n}</dd><dt className={styles.tileLabel}>{t.label}</dt></div>
          ))}
        </dl>
        <div className={styles.lines}>
          <h3 className={styles.sub}>What's in the file</h3>
          <ul className={styles.list} tabIndex={shipped.items.length > 4 ? 0 : undefined} aria-label="What was said">
            {shipped.items.map((i) => (
              <li key={i.item_id} className={styles.line}>
                <span className={styles.when}>{clock(i.selection.start)}</span>
                <span className={styles.words}>
                  <span className="srOnly">{i.mix === 'replace' ? 'Said ' : i.mix === 'remove' ? 'Removed ' : 'Added '}</span>
                  {i.mix === 'remove' ? <span className={styles.quiet}>Removed. The room's own quiet fills the gap.</span>
                    : diffWords(i.old_text, after(i)).filter((r) => r.kind !== 'del').map((run, k) => (
                      <Fragment key={k}>{k > 0 && ' '}{run.kind === 'ins' ? <ins className={styles.ins}>{run.text}</ins> : run.text}</Fragment>
                    ))}
                  {i.note && <span className={styles.quiet}> {i.note}{/[.!?]$/.test(i.note) ? '' : '.'}</span>}
                </span>
                {onUndo && i.edit_id && <button className={styles.undo} onClick={() => onUndo(i)} disabled={busy}>Undo</button>}
              </li>
            ))}
            {shipped.held > 0 && (
              <li className={styles.line}>
                <span className={styles.when} aria-hidden="true" />
                <span className={`${styles.words} ${styles.quiet}`}>{shipped.held === 1 ? 'One change held as a draft; that line is in as shot.' : `${shipped.held} changes held as drafts; those lines are in as shot.`}</span>
              </li>
            )}
          </ul>
        </div>
        <p className={styles.fine}>The new words are in a stand-in voice, and the mouth still moves to the old ones.</p>
        <div className={styles.actions}>
          <a className={styles.primary} href={shipped.download.url} download={shipped.download.filename}>Download MP4</a>
          <button className={styles.secondary} onClick={() => void copy()}>{copied === true ? 'Link copied' : 'Copy link'}</button>
          <span className="srOnly" role="status">{copied === true ? 'Link copied' : copied === 'failed' ? 'Could not copy the link; use Download instead.' : ''}</span>
          <button className={styles.secondary} onClick={onVariant} disabled={busy}>{busy ? 'Making a variant…' : 'Make a variant'}</button>
          <span className={styles.spacer} />
          <button className={styles.link} onClick={onClose}>Back to the transcript</button>
        </div>
        <p className={styles.fine}>A variant is this clip again with the plan as a draft, for another offer or another wording; nothing is voiced until you say so.</p>
      </div>
    </div>
  )
}
