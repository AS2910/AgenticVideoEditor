import { useState } from 'react'
import type { ReactNode } from 'react'
import styles from './ChatPanel.module.css'

interface ChatPanelProps {
  messages: string[]
  canSubmit: boolean
  onSubmit: (prompt: string) => void
  children?: ReactNode
}

export function ChatPanel({ messages, canSubmit, onSubmit, children }: ChatPanelProps) {
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
          <div key={i} className={styles.message}>{m}</div>
        ))}
        {children}
      </div>
      <div className={styles.composer}>
        <input
          className={styles.input}
          type="text"
          placeholder='e.g. change "20% off" to "30% off"'
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
