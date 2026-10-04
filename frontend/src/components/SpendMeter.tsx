import type { Usage } from '../types'
import styles from './SpendMeter.module.css'

const VENDORS: Record<string, string> = {
  openai: 'Transcription', elevenlabs: 'Voice', anthropic: 'Reading requests',
}

/** The project's spend against its cap, as a small meter (UX-3); the
 *  breakdown by vendor on hover. */
export function SpendMeter({ usage }: { usage: Usage | null }) {
  if (!usage) return null
  const share = usage.ceiling_usd > 0 ? Math.min(1, usage.spent_usd / usage.ceiling_usd) : 0
  const near = share >= 0.8
  const detail = [
    ...usage.lines.map((l) => `${VENDORS[l.vendor] ?? l.vendor}: $${l.usd.toFixed(3)} (${l.calls}×)`),
    `${usage.voice_characters.toLocaleString()} of ${usage.voice_characters_ceiling.toLocaleString()} voice characters`,
  ].join(' · ')
  return (
    <div className={near ? styles.near : styles.meter} data-testid="spend" title={detail}>
      <span className={styles.label}>${usage.spent_usd.toFixed(2)} of ${usage.ceiling_usd.toFixed(2)}</span>
      <span className={styles.track} aria-hidden="true"><span className={styles.fill} style={{ transform: `scaleX(${share})` }} /></span>
      {' '}
      <span className={styles.detail}>{usage.voice_characters.toLocaleString()} of {usage.voice_characters_ceiling.toLocaleString()} voice characters</span>
    </div>
  )
}
