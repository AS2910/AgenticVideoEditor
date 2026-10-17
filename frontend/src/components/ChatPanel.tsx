import { useEffect, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import type { ChatMessage } from '../types'
import { ArrowUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { Markdown } from './Markdown'

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
  /** The composer's input, so "Adjust" can put the cursor there. */
  inputRef?: RefObject<HTMLInputElement | null>
  /** What the send button will do: Plan it, Change the plan, Answer… */
  sendLabel?: string
  /** Words put into the box from outside (an example picked), to send or change. */
  seed?: { text: string; id: number } | null
}

// The panel shows the latest exchange; earlier messages open on request.
const RECENT = 6

type Group = { kind: 'say'; m: ChatMessage } | { kind: 'step'; steps: ChatMessage[] }

/** Consecutive steps fold into one list, so a turn reads as: you, what
 *  Voltage did, what it says. */
function groups(messages: ChatMessage[]): Group[] {
  const out: Group[] = []
  for (const m of messages) {
    const last = out[out.length - 1]
    if (m.kind === 'step') {
      if (last && last.kind === 'step') last.steps.push(m)
      else out.push({ kind: 'step', steps: [m] })
    } else out.push({ kind: 'say', m })
  }
  return out
}

/** What Voltage did, one line each, money on the right (Phase 20). */
function Steps({ steps }: { steps: ChatMessage[] }) {
  const spent = steps.reduce((t, s) => t + (s.cost ?? 0), 0)
  return (
    <ol className="m-0 flex max-w-[92%] list-none flex-col gap-1 self-start p-0 text-sm text-muted-foreground" aria-label="What Voltage did">
      {steps.map((s, k) => (
        <li key={s.seq ?? k} className="flex items-baseline gap-3">
          <span className="w-1.5 shrink-0 text-center" aria-hidden="true">·</span>
          <span className="min-w-0 flex-1">{s.text}</span>
          {s.cost ? <span className="tnum shrink-0 text-xs">${s.cost.toFixed(2)}</span> : null}
        </li>
      ))}
      {spent > 0 && steps.length > 1 && <li className="flex items-baseline gap-3 text-xs"><span className="w-1.5" /><span className="flex-1" /><span className="tnum">${spent.toFixed(2)} this turn</span></li>}
    </ol>
  )
}

/** The conversation with Voltage: what you ask for, and what comes back — a
 *  reply, a question, a take. */
export function ChatPanel({
  messages, canSubmit, onSubmit, children, toolbar, header, hint, inputRef, sendLabel = 'Send', seed,
  placeholder = 'Ask for a change, e.g. say "30% off" instead',
}: ChatPanelProps) {
  const [prompt, setPrompt] = useState('')
  // An example picked lands in the box with the cursor after it.
  useEffect(() => {
    if (!seed) return
    setPrompt(seed.text)
    inputRef?.current?.focus()
  }, [seed, inputRef])
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

  // Steps fold into one group each, so a turn's step list counts once.
  const all = groups(messages)
  const hiddenGroups = showAll ? 0 : Math.max(0, all.length - RECENT)
  const hidden = all.slice(0, hiddenGroups).reduce((n, g) => n + (g.kind === 'step' ? g.steps.length : 1), 0)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {header}
      <div ref={list} className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto px-5 py-4" role="log" aria-live="polite" aria-relevant="additions" aria-label="The conversation">
        {hidden > 0 && (
          <Button variant="link" size="sm" className="self-center text-muted-foreground underline" onClick={() => setShowAll(true)}>
            Show {hidden} earlier {hidden === 1 ? 'message' : 'messages'}
          </Button>
        )}
        {all.slice(hiddenGroups).map((g, i) => g.kind === 'step' ? (
          <Steps key={hidden + i} steps={g.steps} />
        ) : (
          <div
            key={hidden + i}
            className={cn(
              'text-chat',
              g.m.role === 'user'
                ? 'max-w-[86%] self-end rounded-lg bg-secondary px-3.5 py-2 text-secondary-foreground'
                : 'max-w-[92%] self-start text-foreground',
            )}
          >
            <span className="sr-only">{g.m.role === 'user' ? 'You: ' : 'Voltage: '}</span>
            {g.m.role === 'user' ? <span>{g.m.text}</span> : <Markdown text={g.m.text} />}
          </div>
        ))}
        {children}
      </div>
      <div className="flex flex-none flex-col gap-2 border-t bg-background px-5 pt-3 pb-4">
        <div className="flex items-center gap-2">
          <Input
            ref={inputRef}
            type="text"
            aria-label="Describe a change"
            placeholder={placeholder}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
          />
          <Button size="icon" className="rounded-full" onClick={submit} disabled={disabled} aria-label={sendLabel} title={sendLabel}>
            <ArrowUp aria-hidden="true" />
          </Button>
        </div>
        <div className="flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1.5">
          {toolbar}
          {!canSubmit ? (
            <span className="text-sm text-muted-foreground">Pick a line in the transcript, or words on the timeline, then describe the change.</span>
          ) : hint ? (
            <span className="text-sm text-muted-foreground">{hint}</span>
          ) : null}
        </div>
      </div>
    </div>
  )
}
