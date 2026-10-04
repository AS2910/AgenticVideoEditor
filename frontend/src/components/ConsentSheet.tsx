import { useRef } from 'react'
import { useModal } from './useModal'
import styles from './ConsentSheet.module.css'

interface ConsentSheetProps {
  /** Who the voice belongs to, when known: "the Shopkeeper". */
  who?: string | null
  onConfirm: () => void
  onCancel: () => void
  busy?: boolean
}

/** Asked once per project, the first time a voice is about to be made
 *  (UX-3): one sentence on what is about to happen, and why we ask. */
export function ConsentSheet({ who, onConfirm, onCancel, busy }: ConsentSheetProps) {
  const sheet = useRef<HTMLDivElement>(null)
  useModal(sheet, onCancel)
  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="consent-title">
      <div ref={sheet} className={styles.sheet} aria-busy={busy || undefined}>
        <h2 id="consent-title" className={styles.title}>Before I make a voice</h2>
        <p className={styles.text}>
          I'll be creating speech in {who ? `${who}'s` : "this person's"} voice, and editing what they say on camera.
          Do you have their permission?
        </p>
        <p className={styles.fine}>Asked once for this project, and remembered. Deleting the project withdraws it.</p>
        <div className={styles.actions}>
          <button className={styles.secondary} onClick={onCancel} disabled={busy}>Not yet — keep it as a draft</button>
          <button className={styles.primary} onClick={onConfirm} disabled={busy}>{busy ? 'Saving…' : 'Yes, I have it'}</button>
        </div>
      </div>
    </div>
  )
}
