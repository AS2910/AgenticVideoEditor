import { useRef } from 'react'
import type { ReactNode } from 'react'
import styles from './LoadScreen.module.css'

interface LoadScreenProps {
  onLoad: (file: File) => void
  onLoadSample: () => void
  loading: boolean
  error?: string | null
  /** Past projects, shown under the upload actions. */
  children?: ReactNode
}

export function LoadScreen({ onLoad, onLoadSample, loading, error, children }: LoadScreenProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div className={styles.screen}>
      <div className={styles.brand}>Voltage</div>
      <p className={styles.tagline}>Edit what was already shot — seamlessly.</p>

      <input
        ref={inputRef}
        className={styles.fileInput}
        type="file"
        accept="video/*"
        aria-label="Choose a video"
        disabled={loading}
        onChange={(e) => {
          const file = e.target.files?.[0]
          // Reset so re-picking the same file fires onChange again.
          e.target.value = ''
          if (file) onLoad(file)
        }}
      />
      <button
        className={styles.load}
        onClick={() => inputRef.current?.click()}
        disabled={loading}
      >
        {loading ? 'Uploading…' : 'Choose a video'}
      </button>

      <button className={styles.sample} onClick={onLoadSample} disabled={loading}>
        or use the sample ad
      </button>

      <p className={styles.hint}>Up to 3 minutes, English, one speaker on camera.</p>
      {error && <div className={styles.error}>{error}</div>}
      {children}
    </div>
  )
}
