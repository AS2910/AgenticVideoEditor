import styles from './LoadScreen.module.css'

export function LoadScreen({ onLoad, loading }: { onLoad: () => void; loading: boolean }) {
  return (
    <div className={styles.screen}>
      <div className={styles.brand}>Voltage</div>
      <p className={styles.tagline}>Edit what was already shot — seamlessly.</p>
      <button className={styles.load} onClick={onLoad} disabled={loading}>
        {loading ? 'Loading…' : 'Load sample ad'}
      </button>
    </div>
  )
}
