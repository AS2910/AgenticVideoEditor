import type { Candidate, ContinuityReport } from '../types'
import { artifactUrl } from '../api'
import styles from './CandidateCard.module.css'

// Fixed order, mirroring the backend's continuity engine.
const METRICS: { key: keyof ContinuityReport; label: string }[] = [
  { key: 'voice_match', label: 'Voice identity' },
  { key: 'prosody', label: 'Prosody & energy' },
  { key: 'audio_integration', label: 'Audio integration' },
  { key: 'lip_sync', label: 'Lip-sync' },
]

const THRESHOLD = 0.8

interface CandidateCardProps {
  candidate: Candidate
  onApprove: () => void
  onTryAgain: () => void
  projectId: string
}

export function CandidateCard({ candidate, onApprove, onTryAgain, projectId }: CandidateCardProps) {
  const c = candidate.continuity
  return (
    <div className={styles.card}>
      <div className={styles.newText}>{candidate.plan.new_text}</div>

      {/* The generated line, playable. The frames stay unplayed until lip-sync
          is real (Phase 5): today they are a flat colour. */}
      <audio
        data-testid="candidate-audio"
        className={styles.audio}
        controls
        preload="auto"
        src={artifactUrl(projectId, candidate.audio.sha256)}
      />

      <div className={styles.media} data-testid="candidate-media">
        {candidate.frames.duration.toFixed(2)}s generated ·{' '}
        {candidate.audio.container.toUpperCase()} + {candidate.frames.container.toUpperCase()}
      </div>

      {c.passed ? (
        <div className={styles.badge}>✓ Continuity checked</div>
      ) : (
        <div className={styles.badgeFail}>Continuity below threshold</div>
      )}

      <div className={styles.metrics}>
        {METRICS.map(({ key, label }) => {
          const value = c[key] as number | null
          if (value === null) {
            return (
              <div key={key} className={styles.metric}>
                <span className={styles.metricLabel}>{label}</span>
                <span className={styles.unmeasured}>not measured yet</span>
              </div>
            )
          }
          const ok = value >= THRESHOLD
          const simulated = !c.measured.includes(key)
          return (
            <div key={key} className={styles.metric}>
              <span className={styles.metricLabel}>
                {label}
                {simulated && <span className={styles.simulated}> · simulated</span>}
              </span>
              <div className={styles.barTrack}>
                <div
                  data-testid="metric-bar"
                  data-ok={ok}
                  className={ok ? styles.barFillOk : styles.barFillWarn}
                  style={{ width: `${value * 100}%` }}
                />
              </div>
              <span className={styles.metricValue}>{value.toFixed(2)}</span>
            </div>
          )
        })}
      </div>

      {c.warnings.length > 0 && (
        <ul className={styles.warnings}>
          {c.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}

      <div className={styles.actions}>
        <button className={styles.approve} onClick={onApprove} disabled={!c.passed}>
          Approve
        </button>
        <button className={styles.tryAgain} onClick={onTryAgain}>Try again</button>
      </div>
    </div>
  )
}
