import { useState } from 'react'
import type { Candidate, ContinuityReport } from '../types'
import { artifactUrl } from '../api'
import { Avatar } from './Avatar'
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
  onApprove: () => void | Promise<unknown>
  /** Approve despite failed continuity — offered only when it failed. */
  onApproveAnyway?: () => void | Promise<unknown>
  onTryAgain: () => void
  projectId: string
  /** Which change this is a take of, e.g. "The change at 0:07". */
  label?: string
  /** Who says it. */
  speaker?: { name: string; slot: string } | null
  /** How the line was placed, e.g. "Ran 0.4 s into the pause after it". */
  note?: string | null
}

/** A take: the new line, playable, and how well it sits. */
export function CandidateCard({
  candidate, onApprove, onApproveAnyway, onTryAgain, projectId, label, speaker, note,
}: CandidateCardProps) {
  const c = candidate.continuity
  const [pending, setPending] = useState(false)
  const run = async (fn: () => void | Promise<unknown>) => {
    setPending(true)
    try { await fn() } finally { setPending(false) }
  }
  return (
    <div className={styles.card} aria-busy={pending || undefined}>
      {(label || speaker || note) && (
        <div className={styles.meta}>
          {speaker && <Avatar name={speaker.name} slot={speaker.slot} size={18} />}
          {label && <span>{label}</span>}
          <span className={styles.spacer} />
          {note && <span data-testid="placement">{note}</span>}
        </div>
      )}
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
        <div className={styles.badge}>Continuity checked</div>
      ) : (
        <div className={styles.badgeFail} role="status">Continuity below threshold</div>
      )}

      <div className={styles.metrics}>
        {METRICS.map(({ key, label: name }) => {
          const value = c[key] as number | null
          if (value === null) {
            return (
              <div key={key} className={styles.metric}>
                <span className={styles.metricLabel}>{name}</span>
                <span className={styles.unmeasured}>not measured yet</span>
              </div>
            )
          }
          const ok = value >= THRESHOLD
          const simulated = !c.measured.includes(key)
          return (
            <div key={key} className={styles.metric}>
              <span className={styles.metricLabel}>
                {name}
                {simulated && <span className={styles.simulated}> · simulated</span>}
              </span>
              <div className={styles.barTrack}>
                <div
                  data-testid="metric-bar"
                  data-ok={ok}
                  className={ok ? styles.barFillOk : styles.barFillWarn}
                  style={{ transform: `scaleX(${Math.min(1, Math.max(0, value))})` }}
                />
              </div>
              <span className={styles.metricValue}>{value.toFixed(2)}</span>
              {!ok && <span className="srOnly">, below {THRESHOLD.toFixed(2)}</span>}
            </div>
          )
        })}
      </div>

      {c.warnings.length > 0 && (
        <ul className={styles.warnings}>
          {c.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}

      {!c.passed && (
        <div className={styles.media}>
          {onApproveAnyway
            ? 'Below the threshold. Approve anyway keeps it for a trial; Try again makes another take.'
            : "Below the threshold, so it can't be approved as it is. Try again for another take."}
        </div>
      )}
      <div className={styles.actions}>
        <button className={styles.tryAgain} onClick={onTryAgain}>Try again</button>
        {c.passed || !onApproveAnyway ? (
          <button className={styles.approve} onClick={() => void run(onApprove)} disabled={!c.passed || pending} aria-busy={pending || undefined}>
            {pending ? 'Approving…' : 'Approve'}
          </button>
        ) : (
          <button className={styles.approveAnyway} onClick={() => void run(onApproveAnyway)} disabled={pending} aria-busy={pending || undefined}>
            {pending ? 'Approving…' : 'Approve anyway'}
          </button>
        )}
      </div>
    </div>
  )
}
