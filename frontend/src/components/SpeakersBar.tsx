import { useState } from 'react'
import type { Speaker, Voice } from '../types'
import styles from './SpeakersBar.module.css'

interface SpeakersBarProps {
  speakers: Speaker[]
  voices: Voice[]
  /** Whether the transcript has words — detection needs speech to label. */
  hasSpeech: boolean
  detecting: boolean
  onDetect: () => void
  onRename: (label: string, name: string) => void
  onVoice: (label: string, voiceId: string | null) => void
}

// The chat's voice, for a speaker without one of their own.
const CHAT_VOICE = ''

/** Who speaks in the video, what to call them, and each one's voice. */
export function SpeakersBar({
  speakers, voices, hasSpeech, detecting, onDetect, onRename, onVoice,
}: SpeakersBarProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  if (speakers.length === 0) {
    if (!hasSpeech) return null
    return (
      <div className={styles.bar}>
        <span className={styles.caption}>Speakers not detected yet.</span>
        <button className={styles.detect} onClick={onDetect} disabled={detecting}>
          {detecting ? 'Detecting…' : 'Detect speakers'}
        </button>
      </div>
    )
  }

  return (
    <div className={styles.bar} aria-label="Speakers">
      {speakers.map((s) => {
        const draft = drafts[s.label] ?? s.name
        const commit = () => {
          const name = draft.trim()
          if (name && name !== s.name) onRename(s.label, name)
          setDrafts(({ [s.label]: _, ...rest }) => rest)
        }
        return (
          <div key={s.label} className={styles.speaker} data-speaker={s.label}>
            <span className={styles.dot} data-speaker={s.label} />
            <input
              className={styles.name}
              value={draft}
              aria-label={`Name for speaker ${s.label}`}
              onChange={(e) => setDrafts((d) => ({ ...d, [s.label]: e.target.value }))}
              onBlur={commit}
              onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
            />
            <select
              className={styles.voice}
              aria-label={`Voice for ${s.name}`}
              value={s.voice_id ?? CHAT_VOICE}
              onChange={(e) => onVoice(s.label, e.target.value === CHAT_VOICE ? null : e.target.value)}
            >
              <option value={CHAT_VOICE}>Chat's voice</option>
              {voices.map((v) => (
                <option key={v.voice_id} value={v.voice_id}>
                  {v.name}{v.gender ? ` (${v.gender})` : ''}
                </option>
              ))}
            </select>
          </div>
        )
      })}
    </div>
  )
}
