import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { ChatMessage } from '../types'
import styles from './ChatPanel.module.css'

interface ChatPanelProps {
  messages: ChatMessage[]
  canSubmit: boolean
  onSubmit: (prompt: string) => void
  children?: ReactNode
  /** Controls shown above the composer, e.g. the voice picker. */
  toolbar?: ReactNode
}

// The dock shows the latest exchange; earlier messages open on request.
const RECENT = 4

/** Direction: what you ask for, and what comes back — a question, a take. */
export function ChatPanel({ messages, canSubmit, onSubmit, children, toolbar }: ChatPanelProps) {
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
      {toolbar}
      <div className={styles.composer}>
        <input
          className={styles.input}
          type="text"
          aria-label="Describe a change"
          placeholder='Ask for a change, e.g. say "30% off" instead'
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
        />
        <button className={styles.preview} onClick={submit} disabled={disabled}>
          Preview
        </button>
      </div>
      {!canSubmit && (
        <div className={styles.hint}>Pick a line in the script, or words on the timeline, then describe the change.</div>
      )}
    </div>
  )
}
