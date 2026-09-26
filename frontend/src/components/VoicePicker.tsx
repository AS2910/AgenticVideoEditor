import type { Voice } from '../types'
import styles from './VoicePicker.module.css'

interface VoicePickerProps {
  voices: Voice[]
  value: string
  onChange: (voiceId: string) => void
}

const label = (v: Voice) => {
  const traits = [v.gender, v.accent].filter(Boolean).join(', ')
  return traits ? `${v.name} (${traits})` : v.name
}

/** Which voice new lines are spoken in. One voice per edit today; a voice
 *  per speaker comes with multi-voice. */
export function VoicePicker({ voices, value, onChange }: VoicePickerProps) {
  if (voices.length === 0) return null
  const current = voices.find((v) => v.voice_id === value)
  return (
    <label className={styles.picker}>
      <span className={styles.caption}>Voice</span>
      <select
        className={styles.select}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        title={current?.description}
      >
        {voices.map((v) => (
          <option key={v.voice_id} value={v.voice_id}>{label(v)}</option>
        ))}
      </select>
    </label>
  )
}
