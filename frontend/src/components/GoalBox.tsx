import { useState } from 'react'
import styles from './GoalBox.module.css'

const EXAMPLES = [
  "Change the offer everywhere it's mentioned",
  'Fix how the brand name is said',
  'Make the shopkeeper sound more excited',
  'Add a closing line after the last shot',
]

interface GoalBoxProps {
  onPlan: (goal: string) => void
  busy?: boolean
  /** What the video is, for the caption. */
  caption?: string
}

/** Screen A: a goal in your own words, and Voltage plans the edits. */
export function GoalBox({ onPlan, busy, caption }: GoalBoxProps) {
  const [goal, setGoal] = useState('')
  const submit = () => {
    const text = goal.trim()
    if (text && !busy) onPlan(text)
  }
  return (
    <div className={styles.box} data-testid="goal">
      <h2 className={styles.title}>What should your video say?</h2>
      <p className={styles.lead}>
        Describe the change in your own words. Voltage finds every line it touches, re-voices them,
        checks each one sounds right, and shows you before anything is final.
      </p>
      <div className={styles.card}>
        <textarea
          className={styles.input}
          rows={3}
          aria-label="Your goal"
          placeholder="Turn this into our Diwali ad: everything's 30% off, and say the brand name as Bhaji Cam."
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
        />
        <div className={styles.row}>
          {caption && <span className={styles.caption}>{caption}</span>}
          <span className={styles.spacer} />
          <button className={styles.plan} onClick={submit} disabled={busy || !goal.trim()}>
            {busy ? 'Planning…' : 'Plan the edits'}
          </button>
        </div>
      </div>
      <div className={styles.examples}>
        {EXAMPLES.map((e) => (
          <button key={e} className={styles.example} onClick={() => setGoal(e)}>{e}</button>
        ))}
      </div>
    </div>
  )
}
