import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import styles from './LoadScreen.module.css'
import { Orb } from './Orb'

interface LoadScreenProps {
  onLoad: (file: File) => void
  onLoadSample: () => void
  loading: boolean
  /** UX-6: how much of the upload has gone, 0..1; null while transcribing or unknown. */
  progress?: number | null
  error?: string | null
  /** Past projects, shown under the drop zone. */
  children?: ReactNode
  /** Phase 9c: who is signed in, with a way out. */
  who?: { name: string; picture?: string | null } | null
  onSignOut?: () => void
}

/** Your videos (UX-7f): a drop zone, the sample, and the projects as cards. */
export function LoadScreen({ onLoad, onLoadSample, loading, progress = null, error, children, who, onSignOut }: LoadScreenProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const dropped = (files: FileList | null) => {
    const file = files?.[0]
    if (file && !loading) onLoad(file)
  }

  return (
    <div className={styles.screen}>
      <header className={styles.header}>
        <span className={styles.brand}><Orb size={14} />Voltage</span>
        <span className={styles.spacer} />
        {who && (
          <span className={styles.who} data-testid="who">
            {who.picture ? <img className={styles.face} src={who.picture} alt="" referrerPolicy="no-referrer" /> : null}
            {who.name}
            {onSignOut && <button className={styles.signOut} onClick={onSignOut}>Sign out</button>}
          </span>
        )}
      </header>

      <main className={styles.main}>
        <h1 className={styles.title}>Your videos</h1>

        <section
          className={styles.drop}
          data-over={over || undefined}
          aria-label="Start a new video"
          aria-busy={loading || undefined}
          data-testid="drop-zone"
          onDragOver={(e) => { e.preventDefault(); if (!loading) setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); dropped(e.dataTransfer?.files ?? null) }}
        >
          <svg className={styles.dropIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M12 16V4m0 0 4 4m-4-4-4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg>
          <h2 className={styles.dropTitle}>Drop a video here</h2>
          <p className={styles.hint}>Up to three minutes. With speech, or without any at all.</p>
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
            <button className={styles.sample} onClick={onLoadSample} disabled={loading}>Try the sample ad</button>
          </div>
          {loading && (
            <div className={styles.progress} role="status">
              <span
                className={styles.progressTrack}
                role="progressbar"
                aria-label="Uploading"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progress !== null && progress < 1 ? Math.round(progress * 100) : undefined}
              >
                {progress !== null && progress < 1
                  ? <span className={styles.progressKnown} style={{ transform: `scaleX(${progress})` }} />
                  : <span className={styles.progressFill} />}
              </span>
              <span className={styles.hint}>
                {progress !== null && progress < 1
                  ? `Uploading, ${Math.round(progress * 100)}%.`
                  : 'Transcribing. This takes a little while for a long clip.'}
              </span>
            </div>
          )}
          {error && <div className={styles.error} role="alert">{error}</div>}
        </section>

        <div className={styles.recent}>{children}</div>
      </main>
    </div>
  )
}
