import type { Question, QuestionOption } from '../types'
import styles from './QuestionCard.module.css'

interface QuestionCardProps {
  question: Question
  onChoose: (option: QuestionOption) => void
}

/** The editor asking how to place a line, instead of refusing the edit. */
export function QuestionCard({ question, onChoose }: QuestionCardProps) {
  return (
    <div className={styles.card}>
      <div className={styles.line}>“{question.text}”</div>
      <div className={styles.options}>
        {question.options.map((o) => (
          <button key={o.label} className={styles.option} onClick={() => onChoose(o)}>
            <span>{o.label}</span>
            {o.warning && <span className={styles.warning}>{o.warning}</span>}
          </button>
        ))}
      </div>
    </div>
  )
}
