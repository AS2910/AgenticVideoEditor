import type { Voice } from '../types'
import { byAccent } from '../lib/voices'

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
    <label className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">Default voice</span>
      <select
        className="h-8 max-w-52 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:h-11 dark:bg-input/30 dark:[&>option]:bg-popover"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-describedby={current?.description ? 'voice-about' : undefined}
      >
        {byAccent(voices).length > 1
          ? byAccent(voices).map(([accent, group]) => (
            <optgroup key={accent} label={accent}>
              {group.map((v) => <option key={v.voice_id} value={v.voice_id}>{label(v)}</option>)}
            </optgroup>
          ))
          : voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{label(v)}</option>)}
      </select>
      {current?.description && <span id="voice-about" className="basis-full text-xs text-muted-foreground">{current.description}</span>}
    </label>
  )
}
