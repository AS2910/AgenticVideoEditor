import { useEffect, useRef, useState } from 'react'
import type { Statement } from '../types'
import styles from './TranscriptPanel.module.css'

interface TranscriptPanelProps {
  statements: Statement[]
  /** Where playback is, on the source's clock — the statement there is lit. */
  currentTime: number
  disabled?: boolean
  onSeek: (statement: Statement) => void
  onEdit: (statement: Statement, text: string) => void
}

const clock = (t: number) => {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

/** The transcript as statements. Click a time to jump there; click the text
 *  to rewrite it and preview the change. */
export function TranscriptPanel({ statements, currentTime, disabled, onSeek, onEdit }: TranscriptPanelProps) {
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { box.current?.focus() }, [editing])

  if (statements.length === 0) return null

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
    <div className={styles.panel} aria-label="Transcript">
      {statements.map((s, i) => {
        const current = currentTime >= s.start && currentTime < s.end
        return (
          <div key={`${s.start}-${i}`} className={current ? styles.rowCurrent : styles.row}>
            <button className={styles.time} onClick={() => onSeek(s)} aria-label={`Go to ${clock(s.start)}`}>
              {clock(s.start)}
            </button>
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
              <button className={styles.text} onClick={() => start(i)} title="Click to rewrite this line">
                {s.text}
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
