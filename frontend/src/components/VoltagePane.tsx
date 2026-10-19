import { useEffect, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import type { ChatMessage, HelpRef, PlanQuestion } from '../types'
import { artifactUrl } from '../api'
import { ArrowUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Markdown } from './Markdown'
import { Wave } from './Wordmark'

/** One turn of the thread, as the pane reads it: what you said, the trace, what Voltage said. */
interface Turn { user: ChatMessage | null; steps: ChatMessage[]; said: ChatMessage[]; cards: ChatMessage[] }

function turnsOf(messages: ChatMessage[]): Turn[] {
  const turns: Turn[] = []
  for (const m of messages) {
    if (m.role === 'user') { turns.push({ user: m, steps: [], said: [], cards: [] }); continue }
    if (turns.length === 0) turns.push({ user: null, steps: [], said: [], cards: [] })
    const t = turns[turns.length - 1]
    if (m.kind === 'step') t.steps.push(m)
    else if (m.kind === 'previews' && m.data) t.cards.push(m)
    else t.said.push(m)
  }
  return turns
}

/** The articles a turn's search_help steps used, once each; shown after Voltage's answer. */
function helpOf(t: Turn): HelpRef[] {
  const seen = new Map<string, HelpRef>()
  for (const s of t.steps) for (const h of s.data?.help ?? []) if (!seen.has(h.slug)) seen.set(h.slug, h)
  return [...seen.values()].slice(0, 1)
}

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const money = (n: number) => `$${n.toFixed(2)}`

/** The trace: `time ├ sentence tool  cost`, mono, rising in; the last line closes with └. */
function Trace({ steps, open, onToggle }: { steps: ChatMessage[]; open: boolean; onToggle: () => void }) {
  const spent = steps.reduce((t, s) => t + (s.cost ?? 0), 0)
  const last = steps[steps.length - 1]
  const seconds = typeof last?.data?.t === 'number' ? last.data.t : null
  const shown = open || steps.length <= 5 ? steps : steps.slice(-5)
  return (
    <div className="flex flex-col gap-2.5 rounded-[10px] border border-pline px-3.5 py-3" data-testid="trace" data-tour="trace">
      <div className="flex items-center gap-2">
        <span className="tag pm">Trace · {steps.length} {steps.length === 1 ? 'step' : 'steps'}{seconds !== null ? ` · ${Math.round(seconds)} s` : ''}</span>
        <span className="flex-1" />
        {spent > 0 && <span className="tnum font-semibold text-volt">{money(spent)}</span>}
      </div>
      <ol className="trace m-0 list-none p-0" role="list" aria-label="What Voltage did">
        {shown.map((s, k) => {
          const isLast = k === shown.length - 1
          const tool = typeof s.data?.tool === 'string' && s.data.tool !== 'thinking' ? s.data.tool : null
          const t = typeof s.data?.t === 'number' ? mmss(s.data.t) : ''
          return (
            <li key={s.seq ?? k} className="ln" role="listitem">
              <span className="ts">{t}</span>
              <span className="g" aria-hidden="true">{isLast ? '└' : '├'}</span>
              <span className="c">{s.text}{tool && <span className="tool"> {tool}</span>}</span>
              <span className={cn('tnum', s.cost ? 'c' : 'ts')}>{s.cost ? money(s.cost) : 'free'}</span>
            </li>
          )
        })}
      </ol>
      {steps.length > 5 && (
        <button type="button" className="tag pm self-start bg-transparent p-0 text-left hover:text-ptext" onClick={onToggle}>
          {open ? 'Show less ↑' : `Show all ${steps.length} →`}
        </button>
      )}
    </div>
  )
}

/** Voices Voltage designed from words (20b): one player per preview, click to play. */
function Previews({ projectId, m }: { projectId?: string; m: ChatMessage }) {
  const previews = m.data?.previews ?? []
  return (
    <div className="flex flex-col gap-2" role="group" aria-label={m.text} data-testid="voice-previews">
      <span className="tag pm">{previews.length === 1 ? 'One preview' : `${previews.length} previews`} · you choose</span>
      {previews.map((p) => (
        <div key={p.generated_voice_id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-[10px] bg-psunk px-3 py-2.5">
          <span className="tnum text-xs">Preview {p.n} <span className="pm">· {Math.round(p.duration)} s</span></span>
          {projectId ? (
            <audio className="h-9 min-w-0" controls preload="none" src={artifactUrl(projectId, p.sha256)} aria-label={`Play preview ${p.n}`} />
          ) : <span />}
          <span />
        </div>
      ))}
      <p className="m-0 text-sm pm">{m.text}</p>
    </div>
  )
}

interface VoltagePaneProps {
  messages: ChatMessage[]
  projectId?: string
  /** The state word beside the name ("ready", "working", "needs your go") and whether the avatar is busy or needs you. */
  state: string
  busy?: boolean
  need?: boolean
  /** The model and effort tag on the right of the header ("Opus 5.5 · high"). */
  engine?: string
  /** Folders: what project context Voltage is reading ("Brief · Diwali 2026", "2 shared voices"). */
  chips?: string[]
  /** What one turn may spend, under the composer. */
  cap?: string
  question?: PlanQuestion | null
  onAnswer?: (option: string) => void
  onSubmit: (text: string) => void
  placeholder?: string
  sendLabel?: string
  inputRef?: RefObject<HTMLTextAreaElement | null>
  seed?: { text: string; id: number } | null
  /** Short follow-ups offered under the thread (chips). */
  suggestions?: string[]
  /** Content before the thread (the first read), and after it (the plan's record). */
  before?: ReactNode
  children?: ReactNode
  /** The turn is running: its latest step. */
  working?: string | null
  /** What stands when nothing has been said yet. */
  empty?: ReactNode
  /** Help (2026-10-19): "Show me" on an answer from Help starts that article's feature tour. */
  onShowMe?: (tour: string) => void
}

/** Voltage's pane (Volt, 2026-10-18): black in both themes. The avatar and the
 *  state word, the thread as turns — your bubble, the trace, Voltage's words,
 *  a question as a gate card — then the chips and the composer. */
export function VoltagePane({
  messages, projectId, state, busy, need, engine, chips = [], cap, question, onAnswer, onSubmit, placeholder = 'Say what to change…', sendLabel = 'Send',
  inputRef, seed, suggestions = [], before, children, working, empty, onShowMe,
}: VoltagePaneProps) {
  const [prompt, setPrompt] = useState('')
  const [openTrace, setOpenTrace] = useState<number | null>(null)
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!seed) return
    setPrompt(seed.text)
    inputRef?.current?.focus()
  }, [seed, inputRef])
  useEffect(() => {
    const el = list.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages.length, children, question])
  const turns = turnsOf(messages)
  // Earlier turns fold into one chip each; the latest is shown in full.
  const [showAll, setShowAll] = useState(false)
  const shown = showAll ? turns : turns.slice(-2)
  const hidden = turns.length - shown.length
  const submit = () => {
    const text = prompt.trim()
    if (!text) return
    onSubmit(text)
    setPrompt('')
  }
  const disabled = prompt.trim() === ''
  return (
    <aside className="pane flex min-h-0 flex-[1_1_390px] flex-col" aria-label="Voltage" aria-busy={busy || undefined}>
      <div className="flex items-center gap-3 border-b border-pline px-5.5 py-4">
        <Wave busy={busy} need={need} />
        <h2 className="disp m-0 text-lg font-bold tracking-[.01em]">Voltage</h2>
        <span className={cn('tag', need ? 'text-warn' : 'pm')} role="status">· {state}</span>
        <span className="flex-1" />
        {engine && <span className="tag pm">{engine}</span>}
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-b border-pline px-5.5 py-2.5" data-testid="context-chips">
          {chips.map((c, i) => <span key={c} className={cn('tag rounded-full px-2 py-[3px]', i === 0 ? 'bg-volt text-ink' : 'border border-pline pm')}>{c}</span>)}
        </div>
      )}

      <div ref={list} className="flex min-h-0 flex-1 flex-col gap-4.5 overflow-y-auto px-5.5 py-6" role="log" aria-live="polite" aria-relevant="additions" aria-label="The conversation">
        {before}
        {turns.length === 0 && !before && empty}
        {hidden > 0 && (
          <button type="button" className="tag pm flex gap-2.5 rounded-lg bg-psunk px-3 py-2 text-left" onClick={() => setShowAll(true)}>
            <span className="flex-1">{hidden} earlier {hidden === 1 ? 'turn' : 'turns'}</span><span className="tnum">show</span>
          </button>
        )}
        {shown.map((t, i) => {
          const index = turns.length - shown.length + i
          const spent = t.steps.reduce((s, m) => s + (m.cost ?? 0), 0)
          const isLatest = index === turns.length - 1
          if (!isLatest && !showAll && turns.length > 1) {
            return (
              <button key={index} type="button" className="tag pm flex gap-2.5 rounded-lg bg-psunk px-3 py-2 text-left" onClick={() => setShowAll(true)} data-testid="earlier-turn">
                <span className="flex-1 truncate">Turn {index + 1}{t.user ? ` · ${t.user.text}` : ''}</span>
                {spent > 0 && <span className="tnum">{money(spent)}</span>}
              </button>
            )
          }
          return (
            <div key={index} className="flex flex-col gap-4.5" data-testid="turn">
              {t.user && <div className="bubble text-sm"><span className="sr-only">You: </span>{t.user.text}</div>}
              {t.steps.length > 0 && <Trace steps={t.steps} open={openTrace === index} onToggle={() => setOpenTrace((o) => (o === index ? null : index))} />}
              {t.cards.map((c) => <Previews key={c.seq} projectId={projectId} m={c} />)}
              {t.said.length > 0 && (
                <div className="flex flex-col gap-2.5 text-[15px] leading-relaxed [&_strong]:font-medium [&_strong]:text-volt">
                  {t.said.map((m, k) => <div key={m.seq ?? k}><span className="sr-only">Voltage: </span><Markdown text={m.text} /></div>)}
                </div>
              )}
              {helpOf(t).map((h) => (
                <div key={h.slug} className="rise flex flex-col gap-2.5 rounded-xl border-[1.5px] border-volt p-3.5" data-testid="from-help">
                  <span className="tag pm">From Help · {h.section}</span>
                  <span className="disp text-lg font-semibold">{h.title}</span>
                  <div className="flex flex-wrap gap-2">
                    {h.tour && onShowMe && <button type="button" className="btn volt sm" onClick={() => onShowMe(h.tour!)}>⚡ Show me</button>}
                    <a className="btn ghost sm" href={`#help/${h.slug}`}>Read more</a>
                  </div>
                </div>
              ))}
            </div>
          )
        })}
        {working && (
          <div className="trace" role="status" data-testid="turn-working">
            <div className="ln"><span className="ts" /><span className="g" aria-hidden="true">└</span><span className="c inline-flex items-center gap-2">{working}<span className="blinkdot inline-block h-3.5 w-[7px] bg-volt" aria-hidden="true" /></span><span /></div>
          </div>
        )}
        {question && (
          <div className={cn(question.gate ? 'gate' : 'flex flex-col gap-3.5 rounded-xl border border-pline p-4')} data-testid="clarify" data-tour={question.gate ? 'gate' : 'question'} role="group" aria-label={question.gate ? 'Your go is needed' : 'One question'}>
            <span className={cn('tag', question.gate ? 'text-volt' : 'pm')}>{question.gate ? '⚡ Your go is needed' : 'One question'}</span>
            <p className="m-0 text-[15px] leading-relaxed"><strong className="font-medium">{question.text}</strong></p>
            {(question.cost_usd != null || question.left_usd != null) && (
              <div className="tnum grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
                {question.cost_usd != null && <div className="rounded-lg bg-psunk px-2.5 py-2"><div className="pm">THIS STEP</div><div className="text-[15px]">~{money(question.cost_usd)}</div></div>}
                {question.left_usd != null && <div className="rounded-lg bg-psunk px-2.5 py-2"><div className="pm">LEFT IN TURN</div><div className="text-[15px] text-volt">{money(question.left_usd)}</div></div>}
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {question.options.map((o, k) => (
                <button key={o} type="button" className={cn('btn sm', k === 0 && question.gate ? 'volt shine' : o === question.guess && !question.gate ? 'volt' : 'ghost', /^not yet$/i.test(o) && 'border-transparent pm')} onClick={() => onAnswer?.(o)} data-tour-action={k === 0 && question.gate ? 'gate' : undefined}>{o}</button>
              ))}
            </div>
            <span className="pm text-xs" role="status">{question.gate ? 'Say go, or pick one.' : `${question.guess ? `My guess is ${question.guess}. ` : ''}Pick one, or answer in your own words.`}</span>
          </div>
        )}
        {children}
      </div>

      <div className="flex flex-none flex-col gap-3 px-5.5 pt-3.5 pb-5.5">
        {suggestions.length > 0 && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Try one">
            {suggestions.map((s) => <button key={s} type="button" className="sugg" onClick={() => onSubmit(s)}>{s}</button>)}
          </div>
        )}
        <label htmlFor="ask-voltage" className="sr-only">Describe a change</label>
        <div className={cn('flex flex-col gap-2 rounded-xl border-[1.5px] bg-psunk py-3 pr-3 pl-3.5', turns.length === 0 ? 'border-volt' : 'border-pline')} data-tour="composer">
          <textarea
            id="ask-voltage"
            ref={inputRef}
            rows={2}
            aria-label="Describe a change"
            placeholder={placeholder}
            className="m-0 w-full resize-none border-0 bg-transparent p-0 text-[15px] text-ptext outline-none placeholder:pm focus-visible:outline-none"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          />
          <div className="flex items-center gap-2">
            <span className="tag pm">{cap ?? 'Nothing is spent until you say go'}</span>
            <span className="flex-1" />
            <span className="kbd pm hidden sm:inline" aria-hidden="true">/</span>
            <button type="button" className="btn volt sm w-[34px] p-0" onClick={submit} disabled={disabled} aria-label={sendLabel} title={sendLabel} data-tour-action="composer">
              <ArrowUp size={14} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}
