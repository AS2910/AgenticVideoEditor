import { useRef, useState } from 'react'
import type { Project, Reading, Speaker } from '../types'
import { speakerSlot } from '../transcript/speakers'
import { Avatar } from './Avatar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Markdown } from './Markdown'

// Small text-link and pill buttons, shared by the rows below.
const LINK = 'h-auto px-1 py-0 text-sm text-primary underline-offset-4 hover:underline pointer-coarse:h-11'
const CHIP = 'rounded-full'

const EXAMPLES = [
  "Change the offer wherever it's said",
  'Fix how the brand name is said',
  'Make the shopkeeper warmer',
  'Add a closing line',
]
// UX-5: a clip with no speech gets a voice-over instead.
const SILENT_EXAMPLES = [
  'Introduce the place',
  'Write a line for this',
  'Look at it and help me decide',
  'Say "Welcome to Goa" at the start',
]

interface ReadingCardProps {
  project: Project
  /** Voltage's first look: the opening line and each speaker's role. Null while it reads. */
  reading?: Reading | null
  speakers: Speaker[]
  /** Name a speaker: confirming Voltage's guess, or your own name for them. */
  onName?: (label: string, name: string) => void
  /** UX-5: confirm the place Voltage guessed, or name the real one. */
  onPlace?: (place: string) => void
  /** An example picked: it goes into the composer to send or change. */
  onExample: (text: string) => void
}

/** Is this speaker still called by their label ("Speaker A")? */
const unnamed = (name: string, label: string) => name === `Speaker ${label}`

/** Voltage's first message in the thread (UX-7c, from the goal stage of
 *  UX-2 and UX-5): it has read the clip — the opening line, who speaks by
 *  role, or what the picture shows — and offers a few things to ask for. */
export function ReadingCard({ project, reading, speakers, onName, onPlace, onExample }: ReadingCardProps) {
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  // Escape cancels a rename; the blur that follows must not commit the draft.
  const cancelled = useRef(false)
  const [placing, setPlacing] = useState(false)
  const [placeDraft, setPlaceDraft] = useState('')
  const lines = project.statements?.length ?? 0
  const silent = lines === 0
  const sight = reading?.sight ?? null
  // What Voltage noticed, as short lines: its details, or the setting cut into phrases.
  const noticed = sight ? (sight.details?.length ? sight.details : sight.setting.split(/[;.]\s+/).map((t) => t.trim()).filter(Boolean).slice(0, 4)) : []
  const guess = (label: string) => reading?.roles.find((r) => r.label === label)
  const shown = (label: string) => {
    const s = speakers.find((x) => x.label === label)
    if (!s) return label
    return unnamed(s.name, label) ? (guess(label)?.role ?? s.name) : s.name
  }
  const unconfirmed = speakers.filter((s) => unnamed(s.name, s.label) && guess(s.label))
  const opening = reading?.opening
    ?? (silent ? 'No one speaks.'
      : speakers.length === 2 ? `Two people speak, ${lines} ${lines === 1 ? 'line' : 'lines'}.`
      : speakers.length > 2 ? `${speakers.length} people speak, ${lines} lines.`
      : `${lines} ${lines === 1 ? 'line' : 'lines'}.`)
  const commitName = (label: string) => {
    if (cancelled.current) { cancelled.current = false; setRenaming(null); return }
    const name = draft.trim()
    if (name && onName) onName(label, name)
    setRenaming(null)
  }
  return (
    <div className="flex flex-col gap-3" data-testid="reading" role="status" aria-busy={reading === null || undefined}>
      <p className="m-0 text-chat">
        {silent ? <>I've looked at <span className="font-medium break-all">{project.filename}</span>.</> : <>I've read all {lines} {lines === 1 ? 'line' : 'lines'} of <span className="font-medium break-all">{project.filename}</span>.</>}{' '}
        {reading === null ? <span className="text-muted-foreground">Taking it in…</span> : <Markdown as="span" text={opening} />}
      </p>
      {!silent && speakers.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2 text-sm" data-testid="cast">
          {speakers.map((s) => {
            const g = guess(s.label)
            const guessed = unnamed(s.name, s.label) && g
            return (
              <div key={s.label} className="flex items-center gap-2">
                <Avatar name={shown(s.label)} slot={speakerSlot(speakers, s.label)} size={22} />
                {renaming === s.label ? (
                  <Input
                    className="h-8 w-36 text-sm md:text-sm"
                    aria-label={`Name for speaker ${s.label}`}
                    value={draft}
                    autoFocus
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => commitName(s.label)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitName(s.label)
                      if (e.key === 'Escape') { cancelled.current = true; setRenaming(null) }
                    }}
                  />
                ) : (
                  <>
                    <span className="font-medium">
                      {guessed ? 'the ' : ''}{shown(s.label)}
                      {guessed && <span className="font-normal text-muted-foreground"> · my guess{g.why ? `: ${g.why}` : ''}</span>}
                    </span>
                    {onName && (
                      <Button
                        variant="link"
                        className={LINK}
                        onClick={() => { setDraft(guessed ? g.role : unnamed(s.name, s.label) ? '' : s.name); setRenaming(s.label) }}
                      >
                        Rename
                      </Button>
                    )}
                  </>
                )}
              </div>
            )
          })}
          {unconfirmed.length > 0 && onName && (
            <Button variant="outline" size="sm" className={`${CHIP} ml-auto`} onClick={() => unconfirmed.forEach((s) => onName(s.label, guess(s.label)!.role))}>
              Looks right
            </Button>
          )}
        </div>
      )}
      {silent && sight && (
        <div className="flex flex-col gap-2" data-testid="noticed">
          <span className="whitespace-nowrap text-sm text-muted-foreground">I noticed</span>
          <ul className="m-0 flex list-none flex-wrap gap-x-2 gap-y-1.5 p-0">
            {noticed.map((d) => <li key={d} className="whitespace-nowrap rounded-full bg-secondary px-2.5 py-0.5 text-sm text-secondary-foreground">{d}</li>)}
          </ul>
          {(sight.place_guess || sight.place_confirmed) && (
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 text-sm" role="group" aria-label="Where this is">
              {placing ? (
                <>
                  <Input
                    className="h-8 w-36 text-sm md:text-sm"
                    aria-label="Where is this?"
                    placeholder="e.g. Morjim, Goa"
                    value={placeDraft}
                    autoFocus
                    onChange={(e) => setPlaceDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && placeDraft.trim()) { onPlace?.(placeDraft.trim()); setPlacing(false) }
                      if (e.key === 'Escape') setPlacing(false)
                    }}
                  />
                  <Button type="button" variant="outline" size="sm" className={CHIP} disabled={!placeDraft.trim()} onClick={() => { onPlace?.(placeDraft.trim()); setPlacing(false) }}>Use this</Button>
                  <Button type="button" variant="link" className={LINK} onClick={() => setPlacing(false)}>Cancel</Button>
                </>
              ) : sight.place_confirmed ? (
                <>
                  <span>{sight.place_confirmed}<span className="font-normal text-muted-foreground"> · you confirmed</span></span>
                  {onPlace && <Button type="button" variant="link" className={LINK} onClick={() => { setPlaceDraft(sight.place_confirmed ?? ''); setPlacing(true) }}>Change</Button>}
                </>
              ) : (
                <>
                  <span>{sight.place_guess}<span className="font-normal text-muted-foreground"> · my guess{sight.confidence ? `, ${sight.confidence} confidence` : ''}</span></span>
                  {onPlace && <Button type="button" variant="outline" size="sm" className={CHIP} onClick={() => onPlace(sight.place_guess)}>Looks right</Button>}
                  {onPlace && <Button type="button" variant="link" className={LINK} onClick={() => { setPlaceDraft(''); setPlacing(true) }}>Somewhere else…</Button>}
                </>
              )}
            </div>
          )}
        </div>
      )}
      <p className="m-0 text-sm leading-normal text-muted-foreground">
        {silent
          ? 'Tell me what it should say: words in quotes to use them as they are, a brief for me to write it, or ask me to look at it and help. Or place a voice-over yourself on the left.'
          : "Tell me what this video should say and I'll plan it across every line it touches, in the right person's voice, and show you each one before anything is final. Or click any line to change it yourself."}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="whitespace-nowrap text-sm text-muted-foreground">Or try</span>
        {(silent ? SILENT_EXAMPLES : EXAMPLES).map((e) => (
          <Button key={e} variant="outline" size="sm" className={`${CHIP} h-auto min-h-8 py-1 text-left whitespace-normal`} onClick={() => onExample(e)}>{e}</Button>
        ))}
      </div>
    </div>
  )
}
