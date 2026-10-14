import type { Question, QuestionOption } from '../types'
import { Button } from '@/components/ui/button'

interface QuestionCardProps {
  question: Question
  onChoose: (option: QuestionOption) => void
}

/** The editor asking how to place a line, instead of refusing the edit. */
export function QuestionCard({ question, onChoose }: QuestionCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-3 text-card-foreground shadow-xs">
      <div className="text-base">“{question.text}”</div>
      <div className="flex flex-wrap gap-2">
        {question.options.map((o, k) => (
          <Button
            key={o.label}
            variant={k === 0 ? 'default' : 'outline'}
            className="h-auto flex-col items-start gap-0.5 py-2 text-left whitespace-normal"
            onClick={() => onChoose(o)}
          >
            <span>{o.label}</span>
            {o.warning && <span className={k === 0 ? 'text-xs font-normal opacity-80' : 'text-xs font-normal text-destructive'}>{o.warning}</span>}
          </Button>
        ))}
      </div>
    </div>
  )
}
