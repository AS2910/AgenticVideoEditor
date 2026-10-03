import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Project } from '../types'
import { Orb } from './Orb'
import styles from './GoalStage.module.css'

const EXAMPLES = [
  "Change the offer wherever it's said",
  'Fix how the brand name is said',
  'Make the shopkeeper warmer',
  'Add a closing line',
]

interface GoalStageProps {
  project: Project
  onPlan: (goal: string) => void
  onHandsOn: () => void
  busy?: boolean
  /** Recent projects, under the composer. */
  children?: ReactNode
}

/** Screen W1: Voltage has read the clip; say what it should say. */
export function GoalStage({ project, onPlan, onHandsOn, busy, children }: GoalStageProps) {
  const [goal, setGoal] = useState('')
  const lines = project.statements?.length ?? 0
  const speakers = project.speakers ?? []
  const cast = speakers.length === 2
    ? `Two people speak: the ${speakers[0].name} and the ${speakers[1].name}.`
    : speakers.length > 2 ? `${speakers.length} people speak.`
    : speakers.length === 1 ? `One person speaks: ${speakers[0].name}.` : ''
  const submit = () => {
    const text = goal.trim()
    if (text && !busy) onPlan(text)
  }
  return (
    <div className={styles.stage}>
      <header className={styles.header}>
        <span className={styles.brand}>Voltage</span>
      </header>
      <div className={styles.hero}>
        <div className={styles.read}>
          <Orb size={32} working={busy} />
          <span>
            I've read all {lines} {lines === 1 ? 'line' : 'lines'} of <strong>{project.filename}</strong>.{cast ? ` ${cast}` : ''}
          </span>
        </div>
        <h1 className={styles.title}>What should this video say?</h1>
        <p className={styles.lead}>
          Tell me in your own words. I'll find every line it touches, write the change, voice it in the
          right person's voice, and show you each one before anything is final.
        </p>
        <div className={styles.card}>
          <textarea
            className={styles.input}
            rows={3}
            aria-label="What the video should say"
            placeholder="Turn this into our Diwali ad: everything's 30% off, and say the brand name as Bhaji Cam."
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
          {EXAMPLES.map((e) => (
            <button key={e} className={styles.example} onClick={() => setGoal(e)}>{e}</button>
          ))}
          <span className={styles.spacer} />
          <button className={styles.link} onClick={onHandsOn}>Edit a line yourself instead</button>
        </div>
      </div>
      <div className={styles.recent}>{children}</div>
    </div>
  )
}
