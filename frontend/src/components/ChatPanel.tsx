import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { ChatMessage } from '../types'
import styles from './ChatPanel.module.css'

interface ChatPanelProps {
  messages: ChatMessage[]
  canSubmit: boolean
  onSubmit: (prompt: string) => void
  children?: ReactNode
  /** Controls shown beside the composer, e.g. the voice picker. */
  toolbar?: ReactNode
  /** The panel's header: who this is, and what it is doing. */
  header?: ReactNode
  placeholder?: string
  /** A line under the composer, when there is something to say. */
  hint?: string
}

// The panel shows the latest exchange; earlier messages open on request.
const RECENT = 6

/** The conversation with Voltage: what you ask for, and what comes back — a
 *  reply, a question, a take. */
export function ChatPanel({
  messages, canSubmit, onSubmit, children, toolbar, header, hint,
  placeholder = 'Ask for a change, e.g. say "30% off" instead',
}: ChatPanelProps) {
  const [prompt, setPrompt] = useState('')
  const [showAll, setShowAll] = useState(false)
  const list = useRef<HTMLDivElement>(null)
  const disabled = !canSubmit || prompt.trim() === ''

  // Keep the latest exchange in view by scrolling the list itself — never the
  // page, which on a narrow window would carry the header away.
  useEffect(() => {
    const el = list.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages.length, children])

  const submit = () => {
    if (disabled) return
    onSubmit(prompt.trim())
    setPrompt('')
  }

  const hidden = showAll ? 0 : Math.max(0, messages.length - RECENT)
  return (
    <div className={styles.panel}>
      {header}
      <div ref={list} className={styles.messages}>
        {hidden > 0 && (
          <button className={styles.earlier} onClick={() => setShowAll(true)}>
            Show {hidden} earlier {hidden === 1 ? 'message' : 'messages'}
          </button>
        )}
        {messages.slice(hidden).map((m, i) => (
          <div key={hidden + i} className={m.role === 'user' ? styles.message : styles.reply}>{m.text}</div>
        ))}
        {children}
      </div>
      <div className={styles.foot}>
        <div className={styles.composer}>
          <input
            className={styles.input}
            type="text"
            aria-label="Describe a change"
            placeholder={placeholder}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
          />
          <button className={styles.send} onClick={submit} disabled={disabled} aria-label="Preview" title="Preview">
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        <div className={styles.under}>
          {toolbar}
          {!canSubmit ? (
            <span className={styles.hint}>Pick a line in the transcript, or words on the timeline, then describe the change.</span>
          ) : hint ? (
            <span className={styles.hint}>{hint}</span>
          ) : null}
        </div>
      </div>
    </div>
  )
}
