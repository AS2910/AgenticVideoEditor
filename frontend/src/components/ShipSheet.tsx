import { useState } from 'react'
import type { PlanItem } from '../types'
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
}

interface ShipSheetProps {
  shipped: Shipped
  onVariant: () => void
  onClose: () => void
  busy?: boolean
}

const secs = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`

/** What is in the file, once it is shipped (UX-3): the changes, the length,
 *  a download, a link, and a way to start the next version from this one. */
export function ShipSheet({ shipped, onVariant, onClose, busy }: ShipSheetProps) {
  const [copied, setCopied] = useState(false)
  const changed = shipped.items.filter((i) => i.mix === 'replace').length
  const added = shipped.items.length - changed
  const parts = [
    changed > 0 && `${changed} ${changed === 1 ? 'line' : 'lines'} changed`,
    added > 0 && `${added} added`,
    shipped.removed > 0 && `${shipped.removed} removed`,
  ].filter(Boolean)
  const longer = shipped.after - shipped.before
  const link = new URL(shipped.download.url, window.location.origin).toString()
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="ship-title">
      <div className={styles.sheet} data-testid="ship-sheet">
        <h2 id="ship-title" className={styles.title}>Shipped</h2>
        <p className={styles.lead}>
          {parts.length > 0 ? parts.join(', ') : 'Nothing changed'}
          {shipped.held > 0 && `; ${shipped.held} held as ${shipped.held === 1 ? 'a draft' : 'drafts'}`}.
          {' '}{secs(shipped.before)} → {secs(shipped.after)}{Math.abs(longer) >= 0.05 ? ` (${longer > 0 ? '+' : '−'}${Math.abs(longer).toFixed(1)} s)` : ', the same length'}.
          {shipped.spendUsd > 0 && ` $${shipped.spendUsd.toFixed(2)} for this plan.`}
        </p>
        <ul className={styles.lines}>
          {shipped.items.map((i) => (
            <li key={i.item_id}>
              <span className={styles.quiet}>{i.mix === 'replace' ? 'Said' : 'Added'}</span> “{i.new_text}”
            </li>
          ))}
        </ul>
        <div className={styles.actions}>
          <a className={styles.primary} href={shipped.download.url} download={shipped.download.filename}>Download MP4</a>
          <button className={styles.secondary} onClick={() => void copy()}>{copied ? 'Link copied' : 'Copy link'}</button>
          <button className={styles.secondary} onClick={onVariant} disabled={busy}>{busy ? 'Making a variant…' : 'Make a variant'}</button>
          <span className={styles.spacer} />
          <button className={styles.link} onClick={onClose}>Back to the transcript</button>
        </div>
        <p className={styles.fine}>A variant is this clip again with the plan as a draft, for another offer or another wording; nothing is voiced until you say so.</p>
      </div>
    </div>
  )
}
