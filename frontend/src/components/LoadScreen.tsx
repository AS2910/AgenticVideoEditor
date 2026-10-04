import { useRef } from 'react'
import type { ReactNode } from 'react'
import styles from './LoadScreen.module.css'

interface LoadScreenProps {
  onLoad: (file: File) => void
  onLoadSample: () => void
  loading: boolean
  error?: string | null
  /** Past projects, shown under the upload. */
  children?: ReactNode
  /** Phase 9c: who is signed in, with a way out. */
  who?: { name: string; picture?: string | null } | null
  onSignOut?: () => void
}

/** The start: a video in, and what Voltage will do with it. */
export function LoadScreen({ onLoad, onLoadSample, loading, error, children, who, onSignOut }: LoadScreenProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div className={styles.screen}>
      <header className={styles.header}>
        <span className={styles.brand}>Voltage</span>
        {who && (
          <span className={styles.who} data-testid="who">
            {who.picture ? <img className={styles.face} src={who.picture} alt="" referrerPolicy="no-referrer" /> : null}
            {who.name}
            {onSignOut && <button className={styles.signOut} onClick={onSignOut}>Sign out</button>}
          </span>
        )}
      </header>

      <main className={styles.main}>
      <div className={styles.hero}>
        <h1 className={styles.title}>Change what's said in a video you've already shot.</h1>
        <p className={styles.tagline}>
          Upload a clip. Voltage transcribes it, finds who speaks, and lets you rewrite any line in a
          voice that fits — checking each one sounds right before anything is final.
        </p>

        <div className={styles.card} aria-busy={loading || undefined}>
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
          <div className={styles.actions}>
            <button className={styles.load} onClick={() => inputRef.current?.click()} disabled={loading}>
              {loading ? 'Uploading…' : 'Choose a video'}
            </button>
            <button className={styles.sample} onClick={onLoadSample} disabled={loading}>
              or use the sample ad
            </button>
          </div>
          <p className={styles.hint}>Up to 3 minutes, English, one speaker on camera.</p>
          {loading && <p className={styles.hint} role="status">Uploading and transcribing. This takes a little while for a long clip.</p>}
          {error && <div className={styles.error} role="alert">{error}</div>}
        </div>
      </div>

      <div className={styles.recent}>{children}</div>
      </main>
    </div>
  )
}
