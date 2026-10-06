import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { Project, Reading } from '../types'
import { artifactUrl, frameUrl } from '../api'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { Avatar } from './Avatar'
import { Orb } from './Orb'
import styles from './GoalStage.module.css'

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

interface GoalStageProps {
  project: Project
  /** Voltage's first look: the opening line and each speaker's role. Null while it reads. */
  reading?: Reading | null
  onPlan: (goal: string) => void
  onHandsOn: () => void
  /** Name a speaker: confirming Voltage's guess, or your own name for them. */
  onName?: (label: string, name: string) => void
  /** UX-5: confirm the place Voltage guessed, or name the real one. */
  onPlace?: (place: string) => void
  busy?: boolean
  /** Recent projects, under the composer. */
  children?: ReactNode
}

/** Is this speaker still called by their label ("Speaker A")? */
const unnamed = (name: string, label: string) => name === `Speaker ${label}`

/** Screen W1 (UX-2): Voltage has read the clip and shows it — the lines, who
 *  speaks them by role — then asks what it should say. */
export function GoalStage({ project, reading, onPlan, onHandsOn, onName, onPlace, busy, children }: GoalStageProps) {
  const [goal, setGoal] = useState('')
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  // Escape cancels a rename; the blur that follows must not commit the draft.
  const cancelled = useRef(false)
  // UX-5: the clip itself, and the moment a frame was picked.
  const video = useRef<HTMLVideoElement>(null)
  const [picked, setPicked] = useState<number | null>(null)
  const [placing, setPlacing] = useState(false)
  const [placeDraft, setPlaceDraft] = useState('')
  const sight = reading?.sight ?? null
  // What Voltage noticed, as short lines: its details, or the setting cut into phrases.
  const noticed = sight ? (sight.details?.length ? sight.details : sight.setting.split(/[;.]\s+/).map((t) => t.trim()).filter(Boolean).slice(0, 4)) : []
  const jump = (at: number) => { setPicked(at); const v = video.current; if (v) { v.currentTime = at; v.pause() } }
  const statements = project.statements ?? []
  const lines = statements.length
  const silent = lines === 0
  const frames = project.frames ?? []
  const speakers = project.speakers ?? []
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
  const submit = () => {
    const text = goal.trim()
    if (text && !busy) onPlan(text)
  }
  const commitName = (label: string) => {
    if (cancelled.current) { cancelled.current = false; setRenaming(null); return }
    const name = draft.trim()
    if (name && onName) onName(label, name)
    setRenaming(null)
  }
  return (
    <div className={styles.stage}>
      <header className={styles.header}>
        <span className={styles.brand}>Voltage</span>
      </header>
      <main className={styles.main}>
      <div className={styles.hero}>
        <div className={styles.read} role="status" aria-busy={reading === null || undefined}>
          <Orb size={32} working={busy || reading === null} />
          <span>
            {silent ? <>I've looked at <strong>{project.filename}</strong>.</> : <>I've read all {lines} {lines === 1 ? 'line' : 'lines'} of <strong>{project.filename}</strong>.</>}{' '}
            {reading === null ? <span className={styles.dim}>Taking it in…</span> : opening}
          </span>
        </div>
        <h1 className={styles.title}>What should this video say?</h1>
        <div className={styles.columns}>
          {silent ? (
          <section className={styles.script} aria-label="The clip" tabIndex={0} aria-busy={reading === null || undefined}>
            <video
              ref={video}
              className={styles.clipVideo}
              src={artifactUrl(project.project_id, project.media.sha256)}
              controls
              playsInline
              preload="metadata"
              aria-label={`${project.filename}, ${project.duration.toFixed(1)} seconds`}
            />
            <ul className={styles.strip} data-testid="frames" aria-label="Moments in the clip">
              {(frames.length ? frames : [0, 1, 2].map((i) => ({ index: i, at: NaN }))).map((f) => (
                <li key={f.index} className={styles.frameSlot}>
                  {Number.isNaN(f.at) ? <span className={styles.frameEmpty} aria-hidden="true" /> : (
                    <button
                      type="button"
                      className={styles.frameButton}
                      aria-label={`Jump to ${clock(f.at)}`}
                      aria-pressed={picked === f.at}
                      onClick={() => jump(f.at)}
                    >
                      <img className={styles.frameImg} src={frameUrl(project.project_id, f.index)} alt="" width={160} height={90} loading="lazy" />
                      <span className={styles.frameTime}>{clock(f.at)}</span>
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {sight && (
              <div className={styles.noticed} data-testid="noticed">
                <span className={styles.noticedLabel}>I noticed</span>
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
                        <span className={styles.placeText}>{sight.place_confirmed}<span className={styles.guess}> · you confirmed</span></span>
                        {onPlace && <button type="button" className={styles.link} onClick={() => { setPlaceDraft(sight.place_confirmed ?? ''); setPlacing(true) }}>Change</button>}
                      </>
                    ) : (
                      <>
                        <span className={styles.placeText}>{sight.place_guess}<span className={styles.guess}> · my guess{sight.confidence ? `, ${sight.confidence} confidence` : ''}</span></span>
                        {onPlace && <button type="button" className={styles.confirm} onClick={() => onPlace(sight.place_guess)}>Looks right</button>}
                        {onPlace && <button type="button" className={styles.link} onClick={() => { setPlaceDraft(''); setPlacing(true) }}>Somewhere else…</button>}
                      </>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
          ) : (
          <section className={styles.script} aria-label="What is said" tabIndex={0}>
            {speakers.length > 0 && (
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
                  <button
                    className={styles.confirm}
                    onClick={() => unconfirmed.forEach((s) => onName(s.label, guess(s.label)!.role))}
                  >
                    Looks right
                  </button>
                )}
              </div>
            )}
            <ol className={styles.lines}>
              {statements.map((st, i) => (
                <li key={i} className={styles.lineRow}>
                  <span className={styles.time}>{clock(st.start)}</span>
                  {st.speaker && <span className={styles.who} data-slot={speakerSlot(speakers, st.speaker)}>{shown(st.speaker)}</span>}
                  <span className={styles.words}>{st.text}</span>
                </li>
              ))}
            </ol>
          </section>
          )}
          <div className={styles.ask}>
            <p className={styles.lead}>
              {silent
                ? "No one speaks, so tell me what it should say: words in quotes to use them as they are, a brief for me to write it, or ask me to look at it and help."
                : "Tell me in your own words. I'll find every line it touches, write the change, voice it in the right person's voice, and show you each one before anything is final."}
            </p>
            <div className={styles.card}>
              <textarea
                className={styles.input}
                rows={3}
                aria-label="What the video should say"
                placeholder={silent ? 'e.g. Add an audio introducing the place: "Welcome to Goa"' : "e.g. Turn this into our Diwali ad: everything's 30% off, and say the brand name as Bhaji Cam."}
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
              />
              <div className={styles.row}>
                <span className={styles.clip}><span className={styles.thumb} />{project.filename}<span className={styles.dim}>{project.duration.toFixed(1)} s</span></span>
                <span className={styles.note}>Nothing is voiced until you've seen the plan.</span>
                <span className={styles.spacer} />
                <button className={styles.plan} onClick={submit} disabled={busy || !goal.trim()}>
                  {busy ? 'Reading…' : 'Plan it with me'}
                </button>
              </div>
            </div>
            <div className={styles.examples}>
              <span className={styles.or}>Or try</span>
              {(silent ? SILENT_EXAMPLES : EXAMPLES).map((e) => (
                <button key={e} className={styles.example} onClick={() => setGoal(e)}>{e}</button>
              ))}
              {silent && picked !== null && (
                <button className={styles.example} onClick={() => setGoal((g) => (g.trim() ? `${g.trim()} — from ${clock(picked)}` : `Say it from ${clock(picked)}: `))}>Say it from {clock(picked)}</button>
              )}
              <span className={styles.spacer} />
              <button className={styles.link} onClick={onHandsOn}>{silent ? 'Place a voice-over yourself instead' : 'Edit a line yourself instead'}</button>
            </div>
          </div>
        </div>
      </div>
      <div className={styles.recent}>{children}</div>
      </main>
    </div>
  )
}
