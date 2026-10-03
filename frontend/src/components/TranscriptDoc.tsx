import { Fragment, useEffect, useRef, useState } from 'react'
import type {
  ItemStatus, LineStatus, LongLines, Mix, Revision, Selection, Speaker, Statement, Voice, Word,
} from '../types'
import { trackedChanges } from '../transcript/changes'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { Avatar } from './Avatar'
import styles from './TranscriptDoc.module.css'

/** What the inline editor hands back for a line. */
export interface LineChange { text: string; voiceId: string | null; onLong: LongLines }

/** A line the editor or the agent is working on: where it stands, and the
 *  new words so far, shown as tracked changes before anything is approved. */
export interface PendingLine { selection: Selection; status: LineStatus | ItemStatus | 'reading'; text?: string; mix?: Mix }

/** How the last take of a line was made to fit, for the readout under the editor. */
export interface FitReadout { selection: Selection; tags: string[] }

interface TranscriptDocProps {
  statements: Statement[]
  /** The timed words, so a revision over part of a line keeps the rest. */
  words?: Word[]
  speakers?: Speaker[]
  voices?: Voice[]
  /** Approved edits still in force, shown as inline tracked changes. */
  revisions?: Revision[]
  /** What the chat is talking about. */
  selection?: Selection | null
  /** Where playback is, on the source's clock — the line there is marked. */
  currentTime: number
  /** Lines being worked on — by you or the agent — and how far each has got. */
  pendingLines?: PendingLine[]
  /** The project's answer to a line that runs long; the editor's default. */
  longLines?: LongLines
  disabled?: boolean
  onSeek: (statement: Statement) => void
  onEdit: (statement: Statement, change: LineChange) => void
  onRevert?: (editId: string) => void
  /** Asks for tighter wordings; resolves to the suggestions (none when offline). */
  onReword?: (statement: Statement, draft: string) => Promise<string[]>
  /** Which line is open for editing, so the panel can stand by. */
  onEditingChange?: (statement: Statement | null) => void
  /** How the last take on a line was fitted, shown under the editor. */
  readouts?: FitReadout[]
  /** The "if it runs long" choice is remembered for the project. */
  onLongLinesChange?: (value: LongLines) => void
}

const overlaps = (a: { start: number; end: number }, b: { start: number; end: number }) =>
  a.start < b.end && b.start < a.end

const STATUS: Record<string, string> = {
  reading: 'Reading', planned: 'Planned', working: 'Working', ready: 'Ready', 'needs-you': 'Needs you', failed: 'Failed',
}

const LONG_OPTIONS: { value: LongLines; label: string }[] = [
  { value: 'pause', label: 'Let Voltage fit it' },
  { value: 'shorten', label: 'Prefer a shorter wording' },
  { value: 'stretch', label: 'Speed it up' },
  { value: 'ask', label: 'Ask me' },
]

const MIX_NOTE: Record<Revision['mix'], string | null> = {
  replace: null,
  layer: 'over the original sound',
  concatenate: 'added after this line',
}

const voiceLabel = (v: Voice) => (v.gender ? `${v.name} (${v.gender})` : v.name)

/** The transcript as a document. Each line has its time, its speaker and its
 *  words; an approved change shows inline as tracked changes with Revert
 *  beside it; a line being worked on carries a status. Click a line to edit
 *  it yourself: wording, voice, what to do if it runs long, or ask Voltage for
 *  wording. */
export function TranscriptDoc({
  statements, words = [], speakers = [], voices = [], revisions = [], selection, currentTime,
  pendingLines = [], longLines = 'pause', disabled, onSeek, onEdit, onRevert, onReword, onLongLinesChange,
  onEditingChange, readouts = [],
}: TranscriptDocProps) {
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [onLong, setOnLong] = useState<LongLines>(longLines)
  const [asking, setAsking] = useState(false)
  const [offers, setOffers] = useState<string[]>([])
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { box.current?.focus() }, [editing])
  useEffect(() => { onEditingChange?.(editing === null ? null : statements[editing]) }, [editing, statements, onEditingChange])

  if (statements.length === 0) {
    return <p className={styles.empty}>No lines to show. This video has no transcribed speech.</p>
  }

  const start = (i: number) => {
    const s = statements[i]
    setEditing(i)
    setDraft(s.text)
    setOffers([])
    setVoiceId(speakers.find((sp) => sp.label === s.speaker)?.voice_id ?? '')
    setOnLong(longLines)
  }
  const submit = (s: Statement) => {
    const text = draft.trim()
    if (text && text !== s.text) onEdit(s, { text, voiceId: voiceId || null, onLong })
    setEditing(null)
  }
  const ask = async (s: Statement) => {
    if (!onReword) return
    setAsking(true)
    try {
      const texts = await onReword(s, draft.trim())
      if (texts.length === 1) setDraft(texts[0])
      else setOffers(texts)
    } finally {
      setAsking(false)
    }
  }
  const chooseLong = (value: LongLines) => {
    setOnLong(value)
    onLongLinesChange?.(value)
  }

  return (
    <section className={styles.doc} aria-label="Transcript">
      <div className={styles.heading}>
        <span className={styles.title}>Transcript</span>
        <span className={styles.hint}>
          {editing !== null ? `Editing ${clock(statements[editing].start)}. Enter to preview, Esc to cancel.`
            : pendingLines.some((p) => p.status === 'reading') ? "Voltage is reading. The line it's on is lit."
            : pendingLines.some((p) => p.status === 'working') ? 'Voltage is working. Lines light up as they finish.'
            : `${pendingLines.some((p) => p.status === 'planned') ? 'Planned changes' : 'Changes'} show inline. Click any line to edit it yourself.`}
        </span>
      </div>

      {statements.map((s, i) => {
        const current = currentTime >= s.start && currentTime < s.end
        const selected = !!selection && overlaps(selection, s)
        const pending = pendingLines.find((p) => overlaps(p.selection, s) && STATUS[p.status])
        const status = pending?.status ?? null
        const live = revisions.filter((r) => overlaps(r, s))
        // A line being worked on shows its new words ahead of approval.
        const revision: Revision | null = pending?.text
          ? { start: pending.selection.start, end: pending.selection.end, text: pending.text, mix: pending.mix ?? 'replace' }
          : live.length ? live[live.length - 1] : null
        const speaker = speakers.find((sp) => sp.label === s.speaker)
        const name = speaker?.name ?? (s.speaker ? `Speaker ${s.speaker}` : null)
        const newSpeaker = !!name && s.speaker !== statements[i - 1]?.speaker
        return (
          <div
            key={`${s.start}-${i}`}
            className={styles.row}
            data-current={current}
            data-selected={selected}
            data-revised={revision !== null}
            data-status={status ?? undefined}
          >
            <button className={styles.time} onClick={() => onSeek(s)} aria-label={`Go to ${clock(s.start)}`}>
              {clock(s.start)}
            </button>
            <span className={styles.who}>
              {newSpeaker && name && <Avatar name={name} slot={speakerSlot(speakers, s.speaker)} />}
            </span>

            <div className={styles.body}>
              {editing === i ? (
                <div className={styles.editor}>
                  <textarea
                    ref={box}
                    className={styles.box}
                    value={draft}
                    rows={2}
                    aria-label="New wording"
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(s) }
                      if (e.key === 'Escape') setEditing(null)
                    }}
                  />
                  <div className={styles.controls}>
                    {voices.length > 0 && (
                      <label className={styles.control}>
                        Voice
                        <select aria-label="Voice" value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
                          <option value="">Default voice</option>
                          {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{voiceLabel(v)}</option>)}
                        </select>
                      </label>
                    )}
                    <label className={styles.control}>
                      If it runs long
                      <select aria-label="If it runs long" value={onLong} onChange={(e) => chooseLong(e.target.value as LongLines)}>
                        {LONG_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </label>
                    <span className={styles.spacer} />
                    {onReword && (
                      <button type="button" className={styles.ask} disabled={asking} onClick={() => void ask(s)}>
                        {asking ? 'Asking Voltage…' : 'Ask Voltage for wording'}
                      </button>
                    )}
                    <button type="button" className={styles.cancel} onClick={() => setEditing(null)}>Cancel</button>
                    <button
                      type="button"
                      className={styles.preview}
                      aria-label="Preview change"
                      disabled={disabled || !draft.trim() || draft.trim() === s.text}
                      onClick={() => submit(s)}
                    >
                      Preview
                    </button>
                  </div>
                  {offers.length > 0 && (
                    <div className={styles.offers} data-testid="offers">
                      <span className={styles.offersCaption}>Tighter wordings that fit the gap as it is</span>
                      {offers.map((o) => (
                        <button key={o} type="button" className={styles.offer} onClick={() => { setDraft(o); setOffers([]) }}>{o}</button>
                      ))}
                    </div>
                  )}
                  {(() => {
                    const r = readouts.find((x) => overlaps(x.selection, s))
                    return r && r.tags.length > 0 ? (
                      <div className={styles.readout} data-testid="readout">
                        <span>Last take fit by:</span>
                        {r.tags.map((t) => <span key={t} className={styles.fitTag}>{t}</span>)}
                      </div>
                    ) : null
                  })()}
                </div>
              ) : (
                <button
                  className={styles.line}
                  onClick={() => start(i)}
                  title="Edit this line"
                  data-testid={revision ? 'revision' : undefined}
                >
                  {revision
                    ? trackedChanges(s, revision, words).map((run, k) => (
                        <Fragment key={k}>
                          {k > 0 && ' '}
                          {run.kind === 'same' && <span>{run.text}</span>}
                          {run.kind === 'del' && <del className={styles.del}>{run.text}</del>}
                          {run.kind === 'ins' && <ins className={styles.ins}>{run.text}</ins>}
                        </Fragment>
                      ))
                    : s.text}
                  {revision && MIX_NOTE[revision.mix] && (
                    <span className={styles.note}> ({MIX_NOTE[revision.mix]})</span>
                  )}
                </button>
              )}
            </div>

            <span className={styles.side}>
              {status && <span className={styles.chip} data-status={status}>{STATUS[status]}</span>}
              {!status && revision?.edit_id && onRevert && editing !== i && (
                <button className={styles.revert} onClick={() => onRevert(revision.edit_id!)}>Revert</button>
              )}
            </span>
          </div>
        )
      })}
    </section>
  )
}
