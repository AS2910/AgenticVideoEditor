import { useState } from 'react'
import type { Speaker, Voice } from '../types'
import { speakerSlot } from '../transcript/speakers'
import { Avatar } from './Avatar'
import { Button } from '@/components/ui/button'

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

// The default voice (the chat's picker), for a speaker without one of their own.
const CHAT_VOICE = ''

/** Who speaks in the video, what to call them, and each one's voice. */
export function SpeakersBar({
  speakers, voices, hasSpeech, detecting, onDetect, onRename, onVoice,
}: SpeakersBarProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  if (speakers.length === 0) {
    if (!hasSpeech) return null
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 text-sm">
        <span className="text-muted-foreground">Who speaks each line isn't known yet.</span>
        <Button variant="outline" size="sm" onClick={onDetect} disabled={detecting}>
          {detecting ? 'Detecting…' : 'Detect speakers'}
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 text-sm" role="group" aria-label="Speakers">
      <span className="font-semibold">Cast</span>
      {speakers.map((s) => {
        const draft = drafts[s.label] ?? s.name
        const commit = () => {
          const name = draft.trim()
          if (name && name !== s.name) onRename(s.label, name)
          setDrafts(({ [s.label]: _, ...rest }) => rest)
        }
        return (
          <div key={s.label} className="flex items-center gap-2 rounded-full border bg-card py-0.5 pr-1.5 pl-1">
            <Avatar name={s.name} slot={speakerSlot(speakers, s.label)} size={20} />
            <input
              className="h-7 min-w-[11ch] rounded-md border border-transparent bg-transparent px-1.5 text-sm font-medium outline-none [field-sizing:content] hover:border-input focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:h-11"
              value={draft}
              aria-label={`Name for speaker ${s.label}`}
              onChange={(e) => setDrafts((d) => ({ ...d, [s.label]: e.target.value }))}
              onBlur={commit}
              onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
            />
            <select
              className="h-7 max-w-40 rounded-md border border-input bg-transparent px-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:h-11 dark:bg-input/30 dark:[&>option]:bg-popover"
              aria-label={`Voice for ${s.name}`}
              value={s.voice_id ?? CHAT_VOICE}
              onChange={(e) => onVoice(s.label, e.target.value === CHAT_VOICE ? null : e.target.value)}
            >
              <option value={CHAT_VOICE}>Default voice</option>
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
