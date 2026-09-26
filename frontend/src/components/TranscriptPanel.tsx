import { useEffect, useRef, useState } from 'react'
import type { Revision, Selection, Statement } from '../types'
import styles from './TranscriptPanel.module.css'

interface TranscriptPanelProps {
  statements: Statement[]
  /** Where playback is, on the source's clock — the statement there is marked. */
  currentTime: number
  disabled?: boolean
  onSeek: (statement: Statement) => void
  onEdit: (statement: Statement, text: string) => void
  /** Display names by speaker label, when speakers are known. */
  speakerNames?: Record<string, string>
  /** Approved edits, set under the lines they change, like script revisions. */
  revisions?: Revision[]
  /** What the direction dock is talking about. */
  selection?: Selection | null
}

const clock = (t: number) => {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

const overlaps = (a: { start: number; end: number }, b: { start: number; end: number }) =>
  a.start < b.end && b.start < a.end

const REVISION_NOTE: Record<Revision['mix'], string | null> = {
  replace: null,
  layer: 'over the original sound',
  concatenate: 'added after this line',
}

/** The transcript set as a script. Click a time to go there and select the
 *  line; click the words to rewrite them. Approved edits appear as revisions:
 *  the new words on a tinted line, an asterisk in the margin. */
export function TranscriptPanel({
  statements, currentTime, disabled, onSeek, onEdit, speakerNames = {}, revisions = [], selection,
}: TranscriptPanelProps) {
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { box.current?.focus() }, [editing])

  if (statements.length === 0) {
    return <p className={styles.empty}>No lines to show. This video has no transcribed speech.</p>
  }

  const start = (i: number) => {
    setEditing(i)
    setDraft(statements[i].text)
  }
  const submit = (s: Statement) => {
    const text = draft.trim()
    if (text && text !== s.text) onEdit(s, text)
    setEditing(null)
  }

  return (
    <div className={styles.page} aria-label="Transcript">
      {statements.map((s, i) => {
        const current = currentTime >= s.start && currentTime < s.end
        const selected = !!selection && overlaps(selection, s)
        const revised = revisions.filter((r) => overlaps(r, s))
        const name = s.speaker ? speakerNames[s.speaker] : undefined
        const newSpeaker = !!name && s.speaker !== statements[i - 1]?.speaker
        return (
          <div
            key={`${s.start}-${i}`}
            className={styles.row}
            data-current={current}
            data-selected={selected}
          >
            <button className={styles.time} onClick={() => onSeek(s)} aria-label={`Go to ${clock(s.start)}`}>
              {clock(s.start)}
            </button>

            <div className={styles.body}>
              {newSpeaker && (
                <div className={styles.who} data-speaker={s.speaker}>{name}</div>
              )}
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
                  <div className={styles.actions}>
                    <button
                      className={styles.preview}
                      disabled={disabled || !draft.trim() || draft.trim() === s.text}
                      onClick={() => submit(s)}
                    >
                      Preview change
                    </button>
                    <button className={styles.cancel} onClick={() => setEditing(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <button className={styles.line} onClick={() => start(i)} title="Rewrite this line">
                  {s.text}
                </button>
              )}
              {revised.map((r, j) => (
                <div key={j} className={styles.revision} data-testid="revision">
                  {r.text}
                  {REVISION_NOTE[r.mix] && <span className={styles.note}> ({REVISION_NOTE[r.mix]})</span>}
                </div>
              ))}
            </div>

            <span className={styles.mark} aria-label={revised.length ? 'Revised' : undefined}>
              {revised.length ? '*' : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}
