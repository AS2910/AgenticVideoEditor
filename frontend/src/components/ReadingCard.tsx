import { useRef, useState } from 'react'
import type { Project, Reading, Speaker } from '../types'
import { speakerSlot } from '../transcript/speakers'
import { Avatar } from './Avatar'
import styles from './ReadingCard.module.css'

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
    <div className={styles.card} data-testid="reading" role="status" aria-busy={reading === null || undefined}>
      <p className={styles.opening}>
        {silent ? <>I've looked at <strong>{project.filename}</strong>.</> : <>I've read all {lines} {lines === 1 ? 'line' : 'lines'} of <strong>{project.filename}</strong>.</>}{' '}
        {reading === null ? <span className={styles.dim}>Taking it in…</span> : opening}
      </p>
      {!silent && speakers.length > 0 && (
        <div className={styles.cast} data-testid="cast">
          {speakers.map((s) => {
            const g = guess(s.label)
            const guessed = unnamed(s.name, s.label) && g
            return (
              <div key={s.label} className={styles.member}>
                <Avatar name={shown(s.label)} slot={speakerSlot(speakers, s.label)} size={22} />
                {renaming === s.label ? (
                  <input
                    className={styles.rename}
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
                    <span className={styles.memberName}>
                      {guessed ? 'the ' : ''}{shown(s.label)}
                      {guessed && <span className={styles.guess}> · my guess{g.why ? `: ${g.why}` : ''}</span>}
                    </span>
                    {onName && (
                      <button
                        className={styles.link}
                        onClick={() => { setDraft(guessed ? g.role : unnamed(s.name, s.label) ? '' : s.name); setRenaming(s.label) }}
                      >
                        Rename
                      </button>
                    )}
                  </>
                )}
              </div>
            )
          })}
          {unconfirmed.length > 0 && onName && (
            <button className={styles.confirm} onClick={() => unconfirmed.forEach((s) => onName(s.label, guess(s.label)!.role))}>
              Looks right
            </button>
          )}
        </div>
      )}
      {silent && sight && (
        <div className={styles.noticed} data-testid="noticed">
          <span className={styles.label}>I noticed</span>
          <ul className={styles.noticedList}>
            {noticed.map((d) => <li key={d} className={styles.noticedItem}>{d}</li>)}
          </ul>
          {(sight.place_guess || sight.place_confirmed) && (
            <div className={styles.place} role="group" aria-label="Where this is">
              {placing ? (
                <>
                  <input
                    className={styles.rename}
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
                  <button type="button" className={styles.confirm} disabled={!placeDraft.trim()} onClick={() => { onPlace?.(placeDraft.trim()); setPlacing(false) }}>Use this</button>
                  <button type="button" className={styles.link} onClick={() => setPlacing(false)}>Cancel</button>
                </>
              ) : sight.place_confirmed ? (
                <>
                  <span>{sight.place_confirmed}<span className={styles.guess}> · you confirmed</span></span>
                  {onPlace && <button type="button" className={styles.link} onClick={() => { setPlaceDraft(sight.place_confirmed ?? ''); setPlacing(true) }}>Change</button>}
                </>
              ) : (
                <>
                  <span>{sight.place_guess}<span className={styles.guess}> · my guess{sight.confidence ? `, ${sight.confidence} confidence` : ''}</span></span>
                  {onPlace && <button type="button" className={styles.confirm} onClick={() => onPlace(sight.place_guess)}>Looks right</button>}
                  {onPlace && <button type="button" className={styles.link} onClick={() => { setPlaceDraft(''); setPlacing(true) }}>Somewhere else…</button>}
                </>
              )}
            </div>
          )}
        </div>
      )}
      <p className={styles.lead}>
        {silent
          ? 'Tell me what it should say: words in quotes to use them as they are, a brief for me to write it, or ask me to look at it and help. Or place a voice-over yourself on the left.'
          : "Tell me what this video should say and I'll plan it across every line it touches, in the right person's voice, and show you each one before anything is final. Or click any line to change it yourself."}
      </p>
      <div className={styles.examples}>
        <span className={styles.label}>Or try</span>
        {(silent ? SILENT_EXAMPLES : EXAMPLES).map((e) => (
          <button key={e} className={styles.example} onClick={() => onExample(e)}>{e}</button>
        ))}
      </div>
    </div>
  )
}
