import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import type { ChatMessage, HelpRef, PlanQuestion, SpendSummary, Suggestion } from '../types'
import { spendLine } from '../lib/money'
import { optionsOf } from '../lib/options'
import { artifactUrl } from '../api'
import { ArrowUp, Check, Info, Loader2 } from 'lucide-react'
import type { Step } from '../jobs/model'
import { cn } from '@/lib/utils'
import { Markdown } from './Markdown'
import { Thumbs } from './Thumbs'
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

/** The trace: `time ├ sentence tool  cost`, mono, rising in; the last line closes with └.
 *  The latest turn's footer names every scope: "This turn $0.03 · video $0.61 · project $0.61". */
function Trace({ steps, open, onToggle, spend }: { steps: ChatMessage[]; open: boolean; onToggle: () => void; spend?: SpendSummary | null }) {
  const spent = steps.reduce((t, s) => t + (s.cost ?? 0), 0)
  const last = steps[steps.length - 1]
  const seconds = typeof last?.data?.t === 'number' ? last.data.t : null
  const shown = open || steps.length <= 5 ? steps : steps.slice(-5)
  return (
    <div className="flex flex-col gap-2.5 rounded-[10px] border border-pline px-3.5 py-3" data-testid="trace" data-tour="trace">
      <div className="flex items-center gap-2">
        <span className="tag pm">Trace · {steps.length} {steps.length === 1 ? 'step' : 'steps'}{seconds !== null ? ` · ${Math.round(seconds)} s` : ''}</span>
        <span className="flex-1" />
        {spent > 0 && !spend && <span className="tnum font-semibold text-volt" data-money-scope="turn"><span className="pm font-normal">This turn </span>{money(spent)}</span>}
      </div>
      <ol className="trace m-0 list-none p-0" role="list" aria-label="What Voltage did">
        {shown.map((s, k) => {
          const isLast = k === shown.length - 1
          const tool = typeof s.data?.tool === 'string' && s.data.tool !== 'thinking' ? s.data.tool : null
          const t = typeof s.data?.t === 'number' ? mmss(s.data.t) : ''
          return (
            <li key={s.seq ?? k} className="ln" role="listitem" data-money-scope="step">
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
      {spend && <span className="tnum border-t border-pline pt-2 text-xs pm" data-money-scope="turn" data-testid="trace-spend">{spendLine(spend)}</span>}
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

/** The model and effort behind Voltage ("Opus 5.5 · High"): a small info
 *  button at the right of the header; hover, focus or a tap shows it. */
function EngineInfo({ engine }: { engine: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <span className="group relative flex shrink-0" onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-pmuted hover:bg-psunk hover:text-ptext focus-visible:outline-2 focus-visible:outline-volt pointer-coarse:h-11 pointer-coarse:w-11"
        aria-label={`Model: ${engine}`}
        aria-describedby={id}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}
        data-testid="engine-info"
      >
        <Info size={16} aria-hidden="true" />
      </button>
      <span
        id={id}
        role="tooltip"
        className={cn('tag absolute top-full right-0 z-20 mt-1.5 whitespace-nowrap rounded-md border border-pline bg-psunk px-2.5 py-1.5 text-ptext',
          open ? 'block' : 'hidden group-hover:block group-focus-within:block')}
      >
        {engine}
      </span>
    </span>
  )
}

/** A question (One question) or a gate (Your go is needed): the options stacked,
 *  each wrapping its words; Voltage's pick first and tagged; a long option a
 *  short label with its sentence beneath; the money as one sentence. When the
 *  turn's cap caused it, the first option allows exactly what the step needs. */
function QuestionCard({ question, onAnswer, turnCap, picked }: { question: PlanQuestion; onAnswer?: (option: string, allowMore?: boolean) => void; turnCap?: number; picked?: string | null }) {
  const options = optionsOf(question)
  const cap = question.cap_usd ?? question.turn_cap?.cap_usd ?? turnCap ?? null
  // 2026-10-20: once an option is picked the card stays where it was, its options off and the pick marked.
  const done = question.resolved ?? (picked != null ? { why: '', by: 'chat' as const, at: '' } : null)
  const isPicked = (value: string) => picked != null && value.trim().toLowerCase() === picked.trim().toLowerCase()
  return (
    <div className={cn('min-w-0', done ? 'flex flex-col gap-3.5 rounded-xl border border-dashed border-pline p-4' : question.gate ? 'gate' : 'flex flex-col gap-3.5 rounded-xl border border-pline p-4', done && picked == null && 'opacity-80')} data-testid="clarify" data-resolved={done ? true : undefined} data-picked={picked ?? undefined} data-tour={question.gate ? 'gate' : 'question'} role="group" aria-label={question.gate ? 'Your go is needed' : 'One question'}>
      <span className={cn('tag', question.gate && !done ? 'text-volt' : 'pm')}>{picked != null ? 'Answered' : done ? 'Settled' : question.gate ? '⚡ Your go is needed' : 'One question'}</span>
      <p className="m-0 text-[15px] leading-relaxed" data-money-scope="step"><strong className="font-medium">{question.text}</strong></p>
      {!done && (question.cost_usd != null || question.left_usd != null) && (
        <p className="tnum m-0 text-[13px] leading-snug pm" data-testid="clarify-money">
          {question.cost_usd != null && <span data-money-scope="step">This step costs about {money(question.cost_usd)}. </span>}
          {question.left_usd != null && (
            <span data-money-scope="turn">This turn has {money(question.left_usd)} left{cap != null ? ` of its ${money(cap)} cap` : ''}.</span>
          )}
        </p>
      )}
      <div className="flex w-full min-w-0 flex-col items-start gap-2" data-testid="clarify-options">
        {options.map((o, k) => {
          const volt = !done && (question.gate ? k === 0 : o.way || (o.pick && !question.turn_cap))
          const mine = isPicked(o.value)
          return (
            <button
              key={o.value}
              type="button"
              className={cn('btn sm opt', volt ? 'volt' : 'ghost', volt && question.gate && 'shine', !volt && /^not yet$/i.test(o.value) && 'border-transparent pm', mine && 'opacity-100! border-volt text-volt', picked != null && !mine && 'opacity-50')}
              disabled={!!done}
              aria-pressed={picked != null ? mine : undefined}
              onClick={() => (o.way ? onAnswer?.(o.value, true) : onAnswer?.(o.value))}
              data-tour-action={k === 0 && question.gate ? 'gate' : undefined}
              data-option={o.way ? 'allow-more' : o.pick ? 'pick' : undefined}
              data-money-scope={o.way ? 'turn' : undefined}
            >
              {o.pick && !done && <span className="pick" data-testid="pick-tag">Voltage's pick</span>}
              {mine && <span className="pick" data-testid="your-pick"><Check size={11} aria-hidden="true" className="mr-1 inline" />Your pick</span>}
              <span className="max-w-full" data-testid="option-label">{o.label}</span>
              {o.detail && <span className="detail" data-testid="option-detail">{o.detail}</span>}
            </button>
          )
        })}
      </div>
      <span className="pm text-xs" role="status" data-testid="clarify-status">
        {picked != null ? `You picked “${picked}”.` : done ? `Answered in the editor: ${done.why}.` : question.gate ? 'Say go, or pick one.' : 'Pick one, or answer in your own words.'}
      </span>
    </div>
  )
}

/** The turn's steps (2026-10-20), one list updated in place from its jobs:
 *  [check] Plan ready · [spinner] Voicing line 2 of 5 · [ ] Fit check · [ ] Render preview. */
function StepList({ steps }: { steps: Step[] }) {
  return (
    <ol className="m-0 flex list-none flex-col gap-2 rounded-[10px] border border-pline px-3.5 py-3" aria-label="What Voltage is doing" data-testid="turn-steps">
      {steps.map((s) => (
        <li key={s.key} className="flex min-w-0 items-center gap-2.5 text-sm" data-state={s.state} data-testid="turn-step">
          <span className="inline-flex size-4 shrink-0 items-center justify-center" aria-hidden="true">
            {s.state === 'done' ? <Check size={15} className="text-volt" />
              : s.state === 'running' ? <Loader2 size={15} className="animate-spin text-volt motion-reduce:animate-none" />
              : s.state === 'failed' ? <span className="tag text-warn">!</span>
              : <span className="size-3 rounded-full border border-pline" />}
          </span>
          <span className={cn('min-w-0 truncate', s.state === 'todo' || s.state === 'skipped' ? 'pm' : s.state === 'failed' ? 'text-warn' : '')} title={s.label}>
            <span className="sr-only">{s.state === 'done' ? 'Done: ' : s.state === 'running' ? 'Now: ' : s.state === 'failed' ? 'Failed: ' : 'Next: '}</span>{s.label}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** What a turn closes with: one short sentence, then Hear changes and Undo all (it asks once before undoing). */
export interface TurnSummary { text: string; lines: number; onHear?: () => void; onUndo?: () => void | Promise<unknown> }
function Summary({ summary }: { summary: TurnSummary }) {
  const [asking, setAsking] = useState(false)
  const [undoing, setUndoing] = useState(false)
  const undo = async () => {
    setUndoing(true)
    try { await summary.onUndo?.() } finally { setUndoing(false); setAsking(false) }
  }
  return (
    <div className="flex flex-col gap-2.5 rounded-[10px] bg-psunk px-3.5 py-3" data-testid="turn-summary">
      <p className="m-0 text-[15px]">{summary.text}</p>
      {asking ? (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Undo all">
          <span className="text-sm pm">Undo all {summary.lines} {summary.lines === 1 ? 'line' : 'lines'} from this turn?</span>
          <button type="button" className="btn ghost sm" onClick={() => setAsking(false)} disabled={undoing}>Keep them</button>
          <button type="button" className="btn volt sm" onClick={() => void undo()} disabled={undoing} aria-busy={undoing || undefined}>{undoing ? 'Undoing…' : 'Yes, undo'}</button>
        </div>
      ) : (summary.onHear || summary.onUndo) && (
        <div className="flex flex-wrap items-center gap-2">
          {summary.onUndo && summary.lines > 0 && <button type="button" className="btn ghost sm" onClick={() => setAsking(true)}>Undo all</button>}
          {summary.onHear && <button type="button" className="btn volt sm" onClick={summary.onHear}>Hear changes</button>}
        </div>
      )}
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
  /** The model and effort, behind the info button at the right of the header ("Opus 5.5 · high"). */
  engine?: string
  /** Folders: what project context Voltage is reading ("Brief · Diwali 2026", "2 shared voices"). */
  chips?: string[]
  /** What one turn may spend, under the composer. */
  cap?: string
  /** Spend scopes: the summary after the latest turn, for its trace's footer. */
  spend?: SpendSummary | null
  question?: PlanQuestion | null
  /** An option picked; `allowMore` when it is the way through the turn's cap. */
  onAnswer?: (option: string, allowMore?: boolean) => void
  /** The turn's cap, for a question that does not carry its own. */
  turnCap?: number
  onSubmit: (text: string) => void
  placeholder?: string
  sendLabel?: string
  inputRef?: RefObject<HTMLTextAreaElement | null>
  seed?: { text: string; id: number } | null
  /** Short follow-ups offered under the thread (chips). */
  /** 2026-10-20: chips from this video; a click puts the chip's prompt in the box, Enter sends. */
  suggestions?: Suggestion[]
  /** What happened to a chip: shown, put in the box, sent (as it was, or edited first). */
  onChipEvent?: (event: 'shown' | 'clicked' | 'sent', chip: Suggestion, edited?: boolean) => void
  /** Content before the thread (the first read), and after it (the plan's record). */
  /** 2026-10-20: what Voltage sees in the video, at the top of the thread. */
  seeing?: ReactNode
  before?: ReactNode
  children?: ReactNode
  /** The turn is running: its latest step. */
  working?: string | null
  /** What stands when nothing has been said yet. */
  empty?: ReactNode
  /** Help (2026-10-19): "Show me" on an answer from Help starts that article's feature tour. */
  onShowMe?: (tour: string) => void
  /** 2026-10-20: the option just picked on a question: the card stays above your words, its options off, the pick marked. */
  picked?: { question: PlanQuestion; option: string } | null
  /** The latest turn's steps, bound to its jobs, under your words. */
  steps?: Step[]
  /** The latest turn's closing line, with Hear changes and Undo all. */
  summary?: TurnSummary | null
}

/** Voltage's pane (Volt, 2026-10-18): black in both themes. The avatar and the
 *  state word, the thread as turns — your bubble, the trace, Voltage's words,
 *  a question as a gate card — then the chips and the composer. */
export function VoltagePane({
  messages, projectId, state, busy, need, engine, chips = [], cap, spend, question, onAnswer, turnCap, onSubmit, placeholder = 'Say what to change…', sendLabel = 'Send',
  inputRef, seed, suggestions = [], onChipEvent, seeing, before, children, working, empty, onShowMe, picked, steps = [], summary,
}: VoltagePaneProps) {
  const [prompt, setPrompt] = useState('')
  const [openTrace, setOpenTrace] = useState<number | null>(null)
  const [contextOpen, setContextOpen] = useState(false)
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!seed) return
    setPrompt(seed.text)
    inputRef?.current?.focus()
  }, [seed, inputRef])
  // New content scrolls into view only when you are already near the bottom;
  // otherwise a "New from Voltage" pill waits until you come down to it.
  const nearBottom = useRef(true)
  const [unseen, setUnseen] = useState(false)
  const fresh = `${messages.length}|${question?.text ?? ''}|${working ?? ''}|${before ? 1 : 0}|${children ? 1 : 0}|${steps.map((s) => s.label + s.state).join()}|${summary?.text ?? ''}`
  useLayoutEffect(() => {
    const el = list.current
    if (!el) return
    if (nearBottom.current) el.scrollTop = el.scrollHeight
    else setUnseen(true)
  }, [fresh])
  const onScroll = () => {
    const el = list.current
    if (!el) return
    nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 72
    if (nearBottom.current) setUnseen(false)
  }
  const toBottom = () => {
    const el = list.current
    const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
    if (el) el.scrollTo?.({ top: el.scrollHeight, behavior: still ? 'auto' : 'smooth' })
    nearBottom.current = true
    setUnseen(false)
  }
  const turns = turnsOf(messages)
  // Earlier turns fold into one chip each; the latest is shown in full.
  const [showAll, setShowAll] = useState(false)
  const shown = showAll ? turns : turns.slice(-2)
  const hidden = turns.length - shown.length
  // The chip whose prompt is in the box: sent as it was, or edited first.
  const fromChip = useRef<Suggestion | null>(null)
  const ownBox = useRef<HTMLTextAreaElement | null>(null)
  const box = inputRef ?? ownBox
  const chipsShown = working || busy ? [] : suggestions.slice(0, 4)
  const counted = useRef(new Set<string>())
  useEffect(() => {
    for (const c of chipsShown) {
      const key = `${c.kind}|${c.label}`
      if (!counted.current.has(key)) { counted.current.add(key); onChipEvent?.('shown', c) }
    }
  })
  const takeChip = (c: Suggestion) => {
    fromChip.current = c
    setPrompt(c.prompt)
    onChipEvent?.('clicked', c)
    // In the box, editable, the cursor at the end: nothing is sent from a single click.
    cursorToEnd.current = true
  }
  // Placed as soon as the prompt is in the box, before anything else can be typed.
  const cursorToEnd = useRef(false)
  useLayoutEffect(() => {
    const el = box.current
    if (!cursorToEnd.current || !el) return
    cursorToEnd.current = false
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
  })
  const submit = () => {
    const text = prompt.trim()
    if (!text) return
    nearBottom.current = true           // what you said, and what follows it, comes into view
    if (fromChip.current) onChipEvent?.('sent', fromChip.current, text !== fromChip.current.prompt.trim())
    fromChip.current = null
    onSubmit(text)
    setPrompt('')
  }
  const disabled = prompt.trim() === ''
  return (
    <aside className="pane pane-root flex min-h-0 w-full min-w-0 flex-[1_1_390px] flex-col" aria-label="Voltage" aria-busy={busy || undefined} data-testid="voltage-pane">
      <div className="flex min-w-0 shrink-0 flex-nowrap items-center gap-2.5 border-b border-pline py-3.5 pr-3 pl-5.5 @max-[380px]:pl-4" data-testid="pane-header">
        <Wave busy={busy} need={need} className="shrink-0" />
        <h2 className="disp m-0 shrink-0 whitespace-nowrap text-lg font-bold tracking-[.01em]">Voltage</h2>
        <span className={cn('tag min-w-0 flex-1 truncate', need ? 'text-warn' : 'pm')} role="status" title={state} data-testid="pane-status">· {state}</span>
        {engine && <EngineInfo engine={engine} />}
      </div>
      {chips.length > 0 && (
        <div className="flex min-w-0 shrink-0 flex-wrap gap-1.5 border-b border-pline px-5.5 py-2.5 @max-[380px]:px-4" data-testid="context-chips">
          <button type="button" className="tag hidden items-center rounded-full border border-pline px-2 py-[3px] pm hover:text-ptext pointer-coarse:min-h-11 @max-[380px]:inline-flex" aria-expanded={contextOpen} onClick={() => setContextOpen((o) => !o)} data-testid="context-toggle">
            Context · {chips.length} {contextOpen ? '↑' : '↓'}
          </button>
          {chips.map((c, i) => (
            <span key={c} title={c} className={cn('tag max-w-full truncate rounded-full px-2 py-[3px]', i === 0 ? 'bg-volt text-ink' : 'border border-pline pm', !contextOpen && '@max-[380px]:hidden')} data-testid="context-chip">{c}</span>
          ))}
        </div>
      )}

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <div ref={list} onScroll={onScroll} onClick={(e) => {
          // "line 3" in Voltage's words shows that row of the transcript (2026-10-20).
          const ref = (e.target as HTMLElement).closest<HTMLElement>('[data-goto-line]')
          if (ref) window.dispatchEvent(new CustomEvent('voltage:goto-line', { detail: { line: Number(ref.dataset.gotoLine) } }))
        }} className="pane-thread slimbar flex min-h-0 min-w-0 flex-1 flex-col gap-4.5 overflow-y-auto px-5.5 py-6 @max-[380px]:px-4" role="log" aria-live="polite" aria-relevant="additions" aria-label="The conversation">
          {seeing}
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
                <button key={index} type="button" className="tag pm flex gap-2.5 rounded-lg bg-psunk px-3 py-2 text-left" onClick={() => setShowAll(true)} data-testid="earlier-turn" data-money-scope="turn">
                  <span className="flex-1 truncate">Turn {index + 1}{t.user ? ` · ${t.user.text}` : ''}</span>
                  {spent > 0 && <span className="tnum">{money(spent)}</span>}
                </button>
              )
            }
            return (
              <div key={index} className="flex flex-col gap-4.5" data-testid="turn">
                {isLatest && picked && <QuestionCard question={picked.question} picked={picked.option} turnCap={turnCap} />}
                {t.user && <div className="bubble text-sm"><span className="sr-only">You: </span>{t.user.text}</div>}
                {isLatest && steps.length > 0 && <StepList steps={steps} />}
                {t.steps.length > 0 && (isLatest && steps.length > 0 && openTrace !== index ? (
                  <button type="button" className="tag pm self-start bg-transparent p-0 text-left hover:text-ptext" onClick={() => setOpenTrace(index)} data-testid="trace-details">
                    Details · {t.steps.length} {t.steps.length === 1 ? 'step' : 'steps'} →
                  </button>
                ) : <Trace steps={t.steps} open={openTrace === index} onToggle={() => setOpenTrace((o) => (o === index ? null : index))} spend={isLatest && t.user ? spend : null} />)}
                {t.cards.map((c) => <Previews key={c.seq} projectId={projectId} m={c} />)}
                {t.said.length > 0 && (
                  <div className="flex flex-col gap-2.5 text-[15px] leading-relaxed [&_strong]:font-medium [&_strong]:text-volt">
                    {t.said.map((m, k) => <div key={m.seq ?? k}><span className="sr-only">Voltage: </span><Markdown text={m.text} /></div>)}
                    {/* G8: a thumb on Voltage's reply, once the turn has said its piece. */}
                    {t.user && !(isLatest && working) && t.said[t.said.length - 1].seq != null && <Thumbs target="turn" targetId={`m${t.said[t.said.length - 1].seq}`} dark />}
                  </div>
                )}
                {isLatest && summary && <Summary summary={summary} />}
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
          {working && steps.length === 0 && (
            <div className="trace" role="status" data-testid="turn-working">
              <div className="ln"><span className="ts" /><span className="g" aria-hidden="true">└</span><span className="c inline-flex items-center gap-2">{working}<span className="blinkdot inline-block h-3.5 w-[7px] bg-volt" aria-hidden="true" /></span><span /></div>
            </div>
          )}
          {question && <QuestionCard question={question} onAnswer={onAnswer} turnCap={turnCap} />}
          {children}
        </div>
        {unseen && (
          <button type="button" className="tag absolute bottom-3 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-full border-[1.5px] border-ink bg-volt px-3 py-1.5 text-ink pointer-coarse:py-3" onClick={toBottom} data-testid="new-from-voltage">
            New from Voltage ↓
          </button>
        )}
      </div>

      <div className="flex min-w-0 flex-none flex-col gap-3 px-5.5 pt-3.5 pb-5.5 @max-[380px]:px-4">
        {chipsShown.length > 0 && (
          <div className="flex min-w-0 flex-wrap gap-1.5" role="group" aria-label="Suggestions for this video" data-testid="chips">
            {chipsShown.map((c) => (
              <button key={`${c.kind}-${c.label}`} type="button" className="sugg max-w-full truncate" title={c.prompt} data-kind={c.kind} onClick={() => takeChip(c)}>{c.label}</button>
            ))}
          </div>
        )}
        <label htmlFor="ask-voltage" className="sr-only">Describe a change</label>
        <div className={cn('flex flex-col gap-2 rounded-xl border-[1.5px] bg-psunk py-3 pr-3 pl-3.5', turns.length === 0 ? 'border-volt' : 'border-pline')} data-tour="composer">
          <textarea
            id="ask-voltage"
            ref={box}
            rows={2}
            aria-label="Describe a change"
            placeholder={placeholder}
            className="m-0 w-full resize-none border-0 bg-transparent p-0 text-[15px] text-ptext outline-none placeholder:pm focus-visible:outline-none"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          />
          <div className="flex items-center gap-2">
            <span className="tag min-w-0 truncate pm" data-money-scope="turn" title={cap}>{cap ?? 'Nothing is spent until you say go'}</span>
            <span className="flex-1" />
            <span className="kbd pm hidden sm:inline" aria-hidden="true">/</span>
            <button type="button" className="btn volt sm w-[34px] shrink-0 p-0" onClick={submit} disabled={disabled} aria-label={sendLabel} title={sendLabel} data-tour-action="composer">
              <ArrowUp size={14} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}
