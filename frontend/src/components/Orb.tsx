import styles from './Orb.module.css'

/** Voltage's presence: a teal glow that breathes slowly, and faster while working. */
export function Orb({ size = 26, working = false, idle = false }: { size?: number; working?: boolean; idle?: boolean }) {
  return (
    <span
      className={styles.orb}
      data-working={working || undefined}
      data-idle={idle || undefined}
      aria-hidden="true"
      style={{ width: size, height: size }}
    />
  )
}
