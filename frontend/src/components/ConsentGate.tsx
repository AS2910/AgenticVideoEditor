import { useState } from 'react'
import styles from './ConsentGate.module.css'

export function ConsentGate({ onConfirm }: { onConfirm: () => void }) {
  const [checked, setChecked] = useState(false)
  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <h1 className={styles.title}>Before you edit</h1>
        <label className={styles.consent}>
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
          />
          <span>I confirm I have the right to edit and clone the speaker in this video.</span>
        </label>
        <button className={styles.continue} disabled={!checked} onClick={onConfirm}>
          Continue
        </button>
      </div>
    </div>
  )
}
