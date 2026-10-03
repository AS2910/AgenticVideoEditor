import type { Autonomy } from '../types'
import styles from './AutonomySwitch.module.css'

const MODES: { value: Autonomy; label: string }[] = [
  { value: 'ask', label: 'Check with me' },
  { value: 'draft', label: 'Just do it' },
]

/** How much Voltage does on its own. "Check with me" is the default: every
 *  plan waits for you to say go. */
export function AutonomySwitch({ value, onChange }: { value: Autonomy; onChange: (v: Autonomy) => void }) {
  return (
    <div className={styles.switch} role="group" aria-label="How much Voltage does on its own">
      {MODES.map((m) => (
        <button
          key={m.value}
          className={value === m.value ? styles.on : styles.off}
          aria-pressed={value === m.value}
          onClick={() => onChange(m.value)}
        >
          {m.label}
        </button>
      ))}
    </div>
  )
}
