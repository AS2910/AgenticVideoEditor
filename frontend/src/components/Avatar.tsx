import styles from './Avatar.module.css'

const initial = (name: string) => (name.replace(/^Speaker\s+/i, '').trim()[0] ?? '?').toUpperCase()

/** A speaker's mark: their initial in their colour. */
export function Avatar({ name, slot, size = 22 }: { name: string; slot: string; size?: number }) {
  return (
    <span
      className={styles.avatar}
      data-slot={slot}
      role="img"
      aria-label={name}
      title={name}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.5) }}
    >
      {initial(name)}
    </span>
  )
}
