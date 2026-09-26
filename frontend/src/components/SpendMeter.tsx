import type { Usage } from '../types'
import styles from './SpendMeter.module.css'

const VENDORS: Record<string, string> = {
  openai: 'Transcription', elevenlabs: 'Voice', anthropic: 'Reading requests',
}

/** The project's estimated spend against its limits. */
export function SpendMeter({ usage }: { usage: Usage | null }) {
  if (!usage) return null
  const near = usage.spent_usd >= usage.ceiling_usd * 0.8
  const detail = usage.lines
    .map((l) => `${VENDORS[l.vendor] ?? l.vendor}: $${l.usd.toFixed(3)} (${l.calls}×)`)
    .join(' · ')
  return (
    <div className={near ? styles.near : styles.meter} data-testid="spend" title={detail}>
      Spent ≈ ${usage.spent_usd.toFixed(2)} of ${usage.ceiling_usd.toFixed(2)} · voice{' '}
      {usage.voice_characters.toLocaleString()} / {usage.voice_characters_ceiling.toLocaleString()} characters
    </div>
  )
}
