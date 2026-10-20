import { cn } from '@/lib/utils'

export type VoiceChoice = 'copy' | 'keep'

/** The one question a project's own voices raise when something leaves the
 *  project with them (a video moving out, or a template saved from it):
 *  copy the voice along, or keep it in your voices for any project. Shared
 *  by the Move dialog and Save as template (D1). */
export function VoiceQuestion({ lead, copyLabel, note, value, onChange }: {
  /** The question's first sentence, naming the voices and their project. */
  lead: string
  /** "Copy the voice into this video", "Copy the voice into the template". */
  copyLabel: string
  note: string
  value: VoiceChoice
  onChange: (v: VoiceChoice) => void
}) {
  return (
    <div className="grow flex flex-col gap-2.5 rounded-[10px] border-[1.5px] border-foreground bg-sunk p-3.5" role="radiogroup" aria-label="The project's voice" data-testid="voice-question">
      <span className="font-semibold">{lead}</span>
      <span className="text-[13px] text-muted-foreground">{note}</span>
      {([['copy', copyLabel], ['keep', 'Keep it in my voices, for any project']] as const).map(([k, text]) => (
        <button key={k} type="button" role="radio" aria-checked={value === k} className={cn('flex w-full items-center gap-3 rounded-[10px] border-[1.5px] px-3 py-2.5 text-left', value === k ? 'border-ink bg-volt text-ink' : 'border-line2 bg-card hover:border-foreground')} onClick={() => onChange(k)}>
          <span aria-hidden="true" className="grid size-[18px] flex-none place-items-center rounded-full border-[1.5px] border-current">{value === k && <span className="size-2 rounded-full bg-current" />}</span>
          <span className="flex-1">{text}</span>
        </button>
      ))}
    </div>
  )
}
