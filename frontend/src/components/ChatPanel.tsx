import { useState } from 'react'
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

export function ChatPanel({ messages, canSubmit, onSubmit, children, toolbar }: ChatPanelProps) {
  const [prompt, setPrompt] = useState('')
  const disabled = !canSubmit || prompt.trim() === ''

  const submit = () => {
    if (disabled) return
    onSubmit(prompt.trim())
    setPrompt('')
  }

  return (
    <div className={styles.panel}>
      <div className={styles.messages}>
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? styles.message : styles.reply}>{m.text}</div>
        ))}
        {children}
      </div>
      {toolbar}
      <div className={styles.composer}>
        <input
          className={styles.input}
          type="text"
          placeholder='e.g. change "20% off" to "30% off", or add the line "Thirsty!"'
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
        />
        <button className={styles.preview} onClick={submit} disabled={disabled}>
          Preview
        </button>
      </div>
      {!canSubmit && (
        <div className={styles.hint}>Select a region on the timeline to describe a change.</div>
      )}
    </div>
  )
}
