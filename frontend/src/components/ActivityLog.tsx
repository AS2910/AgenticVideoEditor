import type { Plan } from '../types'
import styles from './ActivityLog.module.css'

/** Seconds since the plan was made, as m:ss. */
const since = (iso: string, from: string) => {
  const s = Math.max(0, Math.round((new Date(iso).getTime() - new Date(from).getTime()) / 1000))
  return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`
}

/** What Voltage did: the plan's log, oldest first. */
export function ActivityLog({ plan }: { plan: Plan }) {
  if (plan.log.length === 0) return null
  return (
    <div className={styles.log} data-testid="activity">
      <span className={styles.title}>What Voltage did</span>
      {plan.log.map((e, i) => (
        <div key={i} className={styles.entry}>
          <span className={styles.at}>{since(e.at, plan.created_at)}</span>
          <span className={styles.text}>{e.text}</span>
          <span className={styles.detail}>{e.detail}</span>
        </div>
      ))}
    </div>
  )
}
