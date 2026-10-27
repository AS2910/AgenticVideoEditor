import { Check } from 'lucide-react'
import type { PlanQuestion } from '../types'
import { optionsOf } from '../lib/options'
import { cn } from '@/lib/utils'

const money = (n: number) => `$${n.toFixed(2)}`

/** The card's looks in one place, so a restyle touches this map and not the logic. */
export const questionCardStyles = {
  open: 'flex flex-col gap-3.5 rounded-xl border border-pline p-4',
  gate: 'gate',
  settled: 'flex flex-col gap-3.5 rounded-xl border border-dashed border-pline p-4',
  tag: 'tag',
  text: 'm-0 text-[15px] leading-relaxed',
  money: 'tnum m-0 text-[13px] leading-snug pm',
  options: 'flex w-full min-w-0 flex-col items-start gap-2',
  option: 'btn sm opt',
  primary: 'volt',
  secondary: 'ghost',
  status: 'pm text-xs',
} as const

/** The primary button's words: when a pick leads straight to a paid step (the
 *  question carries its cost), the price rides on Voltage's pick, so choosing
 *  it is the approval ("Voice it here · $0.04"). A label that names a price already is left alone. */
export function withPrice(label: string, question: PlanQuestion, primary: boolean): string {
  if (!primary || question.gate || question.cost_usd == null || question.cost_usd <= 0 || label.includes('$')) return label
  return `${label} · ${money(question.cost_usd)}`
}

/** One card per question (Run 5 item 2): a question about meaning (which line,
 *  which voice, where) or a gate (a step over the user's limit, or a change to
 *  the video), never both in a row. One primary button: under a gate the yes,
 *  named for what it does with its price ("Voice it · $0.30"); otherwise
 *  Voltage's pick, carrying the price when a pick leads to a paid step. The
 *  options are stacked, each wrapping its words; a long option a short label
 *  with its sentence beneath; the money as one sentence. When the turn's cap
 *  caused it, the first option allows exactly what the step needs. */
export function QuestionCard({ question, onAnswer, turnCap, picked }: { question: PlanQuestion; onAnswer?: (option: string, allowMore?: boolean) => void; turnCap?: number; picked?: string | null }) {
  const options = optionsOf(question)
  const cap = question.cap_usd ?? question.turn_cap?.cap_usd ?? turnCap ?? null
  // 2026-10-20: once an option is picked the card stays where it was, its options off and the pick marked.
  const done = question.resolved ?? (picked != null ? { why: '', by: 'chat' as const, at: '' } : null)
  const isPicked = (value: string) => picked != null && value.trim().toLowerCase() === picked.trim().toLowerCase()
  const st = questionCardStyles
  return (
    <div className={cn('min-w-0', done ? st.settled : question.gate ? st.gate : st.open, done && picked == null && 'opacity-80')} data-testid="clarify" data-resolved={done ? true : undefined} data-picked={picked ?? undefined} data-tour={question.gate ? 'gate' : 'question'} role="group" aria-label={question.gate ? 'Your go is needed' : 'One question'}>
      <span className={cn(st.tag, question.gate && !done ? 'text-volt' : 'pm')}>{picked != null ? 'Answered' : done ? 'Settled' : question.gate ? '⚡ Your go is needed' : 'One question'}</span>
      <p className={st.text} data-money-scope="step"><strong className="font-medium">{question.text}</strong></p>
      {!done && (question.cost_usd != null || question.left_usd != null) && (
        <p className={st.money} data-testid="clarify-money">
          {question.cost_usd != null && <span data-money-scope="step">This step costs about {money(question.cost_usd)}. </span>}
          {question.left_usd != null && (
            <span data-money-scope="turn">This turn has {money(question.left_usd)} left{cap != null ? ` of its ${money(cap)} cap` : ''}.</span>
          )}
        </p>
      )}
      <div className={st.options} data-testid="clarify-options">
        {options.map((o, k) => {
          const primary = !done && (question.gate ? k === 0 : o.way || (o.pick && !question.turn_cap))
          const mine = isPicked(o.value)
          return (
            <button
              key={o.value}
              type="button"
              className={cn(st.option, primary ? st.primary : st.secondary, primary && question.gate && 'shine', !primary && /^not yet$/i.test(o.value) && 'border-transparent pm', mine && 'opacity-100! border-volt text-volt', picked != null && !mine && 'opacity-50')}
              disabled={!!done}
              aria-pressed={picked != null ? mine : undefined}
              onClick={() => (o.way ? onAnswer?.(o.value, true) : onAnswer?.(o.value))}
              data-tour-action={k === 0 && question.gate ? 'gate' : undefined}
              data-option={o.way ? 'allow-more' : o.pick ? 'pick' : undefined}
              data-primary={primary || undefined}
              data-money-scope={o.way ? 'turn' : undefined}
            >
              {o.pick && !done && <span className="pick" data-testid="pick-tag">Voltage's pick</span>}
              {mine && <span className="pick" data-testid="your-pick"><Check size={11} aria-hidden="true" className="mr-1 inline" />Your pick</span>}
              <span className="max-w-full" data-testid="option-label">{withPrice(o.label, question, primary && !o.way)}</span>
              {o.detail && <span className="detail" data-testid="option-detail">{o.detail}</span>}
            </button>
          )
        })}
      </div>
      <span className={st.status} role="status" data-testid="clarify-status">
        {picked != null ? `You picked “${picked}”.` : done ? `Answered in the editor: ${done.why}.` : question.gate ? 'Say go, or pick one.' : question.cost_usd != null ? 'Your pick is your go.' : 'Pick one, or answer in your own words.'}
      </span>
    </div>
  )
}
