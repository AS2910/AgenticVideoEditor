import { useRef, useState } from 'react'
import type { Reading, Speaker, Statement } from '../types'

/** Is this speaker still called by their label ("Speaker A")? */
const unnamed = (name: string, label: string) => name === `Speaker ${label}` || name === ''

/** "Who's speaking" (Volt, the first read): Voltage's guess at each speaker's
 *  role, how many lines and seconds they have, Rename, and one "Looks right"
 *  that names them all. */
export function WhoSpeaks({ speakers, statements, reading, onName }: {
  speakers: Speaker[]
  statements: Statement[]
  reading: Reading | null | undefined
  onName?: (label: string, name: string) => void
}) {
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const cancelled = useRef(false)
  if (speakers.length === 0) return null
  const guess = (label: string) => reading?.roles.find((r) => r.label === label)
  const shown = (s: Speaker) => (unnamed(s.name, s.label) ? (guess(s.label)?.role ?? `Speaker ${speakers.indexOf(s) + 1}`) : s.name)
  const unconfirmed = speakers.filter((s) => unnamed(s.name, s.label) && guess(s.label))
  const lines = (label: string) => statements.filter((st) => st.speaker === label)
  const secs = (label: string) => Math.round(lines(label).reduce((t, st) => t + (st.end - st.start), 0))
  const commit = (label: string) => {
    if (cancelled.current) { cancelled.current = false; setRenaming(null); return }
    const name = draft.trim()
    if (name && onName) onName(label, name)
    setRenaming(null)
  }
  return (
    <section className="flex flex-col gap-3.5 rounded-xl border-[1.5px] border-foreground bg-card p-4.5" aria-label="Who's speaking" data-testid="cast">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="disp text-xl font-bold">Who's speaking</span>
        <span className="tag text-faint" role="status">{unconfirmed.length > 0 ? 'My guess, from what they say' : reading ? 'Confirmed' : 'As labelled'}</span>
        <span className="flex-1" />
        {unconfirmed.length > 0 && onName && (
          <button type="button" className="btn volt sm shine" onClick={() => unconfirmed.forEach((s) => onName(s.label, guess(s.label)!.role))}>✓ Looks right</button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {speakers.map((s, i) => {
          const g = guess(s.label)
          const guessed = unnamed(s.name, s.label) && !!g
          return (
            <div key={s.label} className="flex items-center gap-3 rounded-[10px] bg-sunk p-3">
              <span aria-hidden="true" className={`disp grid size-9 place-items-center rounded-full border-[1.5px] border-ink text-sm font-bold ${i % 2 === 0 ? 'bg-volt text-ink' : 'bg-ink text-volt'}`}>{i + 1}</span>
              <div className="flex min-w-0 flex-1 flex-col">
                {renaming === s.label ? (
                  <input
                    className="h-8 w-full rounded-md border-[1.5px] border-foreground bg-card px-2 text-base outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    aria-label={`Name for speaker ${s.label}`}
                    value={draft}
                    autoFocus
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => commit(s.label)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commit(s.label)
                      if (e.key === 'Escape') { cancelled.current = true; setRenaming(null) }
                    }}
                  />
                ) : (
                  <span className="disp truncate text-base font-semibold">{guessed ? 'the ' : ''}{shown(s)}</span>
                )}
                <span className="tag text-faint">Speaker {i + 1} · {lines(s.label).length} {lines(s.label).length === 1 ? 'line' : 'lines'} · {secs(s.label)} s{guessed && g?.why ? ` · ${g.why}` : ''}</span>
              </div>
              {onName && renaming !== s.label && (
                <button type="button" className="act" onClick={() => { setDraft(guessed ? g!.role : unnamed(s.name, s.label) ? '' : s.name); setRenaming(s.label) }}>Rename</button>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
