import { useState } from 'react'
import type { Plan, PlanItem, QuestionOption, Speaker, Voice } from '../types'
import { artifactUrl } from '../api'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { estimateText, soundsRight } from '../transcript/planText'
import { Avatar } from './Avatar'
import { CheckCircle2, Circle, CircleAlert, Lightbulb, Loader2 } from 'lucide-react'
import { Presence } from './Presence'
import { Button } from '@/components/ui/button'
import { Markdown } from './Markdown'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

interface PlanCardProps {
  plan: Plan
  speakers: Speaker[]
  voices: Voice[]
  projectId: string
  /** A job is voicing the plan: no second run until it is done. */
  busy?: boolean
  onToggle: (item: PlanItem, enabled: boolean) => void | Promise<unknown>
  onReword: (item: PlanItem, text: string) => void | Promise<unknown>
  onInclude: (item: PlanItem, include: boolean) => void | Promise<unknown>
  onRun: () => void | Promise<unknown>
  /** "Adjust": say what to change in the composer. */
  onAdjust?: () => void
  onAnswer: (item: PlanItem, option: QuestionOption) => void | Promise<unknown>
  onRedo: (item: PlanItem) => void | Promise<unknown>
  onApproveAll: () => void
  /** UX-2: how a line is said, and how an added line meets the picture. */
  onDelivery?: (item: PlanItem, delivery: string | null) => void | Promise<unknown>
  onMix?: (item: PlanItem, mix: 'over' | 'concatenate') => void | Promise<unknown>
  /** UX-2: stop a running plan after the line it is on. */
  onStop?: () => void | Promise<unknown>
}

const KIND: Record<string, string> = { replace: 'Replaces the line', concatenate: 'Added after the line, the picture makes room', over: 'Added after the line, over the picture', layer: 'Over the original sound' }
// Chips (pills) for a choice among a few; one is on. Links for the quiet extra.
const PILL = 'rounded-full text-xs'
const pill = (on: boolean) => cn(PILL, on && 'border-changed/40 bg-changed-soft text-changed hover:bg-changed-soft hover:text-changed dark:border-changed/40 dark:bg-changed-soft dark:hover:bg-changed-soft')
const DELIVERIES = ['warmer', 'more excited', 'calmer', 'slower', 'firmer']

/** The two controls a line has in its editor, for a plan item (UX-2). */
function ItemControls({ item, onDelivery, onMix, busy }: {
  item: PlanItem
  onDelivery?: (item: PlanItem, delivery: string | null) => void | Promise<unknown>
  onMix?: (item: PlanItem, mix: 'over' | 'concatenate') => void | Promise<unknown>
  busy?: boolean
}) {
  const at = clock(item.selection.start)
  const delivery = item.delivery ?? null
  const own = delivery !== null && !DELIVERIES.includes(delivery)
  const [ownWords, setOwnWords] = useState<string | null>(own ? delivery : null)
  const commitOwn = () => {
    const text = (ownWords ?? '').trim()
    if (text && text !== delivery && onDelivery) void onDelivery(item, text)
    if (!text) setOwnWords(null)
  }
  return (
    <div className="flex flex-col gap-2" aria-busy={busy || undefined}>
      {onDelivery && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" role="group" aria-label={`Delivery at ${at}`}>
          <span className="w-full shrink-0 sm:w-32">Delivery</span>
          <Button type="button" variant="outline" size="sm" className={pill(delivery === null && ownWords === null)} aria-pressed={delivery === null} disabled={busy} onClick={() => { setOwnWords(null); if (delivery !== null) void onDelivery(item, null) }}>As spoken</Button>
          {DELIVERIES.map((d) => (
            <Button key={d} type="button" variant="outline" size="sm" className={pill(delivery === d)} aria-pressed={delivery === d} disabled={busy} onClick={() => { setOwnWords(null); void onDelivery(item, d) }}>{d}</Button>
          ))}
          {ownWords === null
            ? <Button type="button" variant="link" className="h-auto px-1 py-0 text-xs text-primary underline-offset-4 hover:underline pointer-coarse:h-11" onClick={() => setOwnWords(own ? delivery : '')}>in your words…</Button>
            : <Input className="h-8 w-40 text-sm md:text-sm" aria-label={`Delivery at ${at}, in your words`} placeholder="e.g. like a secret" value={ownWords} onChange={(e) => setOwnWords(e.target.value)} onBlur={commitOwn} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />}
        </div>
      )}
      {onMix && item.mix !== 'replace' && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" role="group" aria-label={`Sound meets picture at ${at}`}>
          <span className="w-full shrink-0 sm:w-32">Sound meets picture</span>
          <Button type="button" variant="outline" size="sm" className={pill(item.mix === 'over')} aria-pressed={item.mix === 'over'} disabled={busy} onClick={() => void onMix(item, 'over')}>Over the picture</Button>
          <Button type="button" variant="outline" size="sm" className={pill(item.mix === 'concatenate')} aria-pressed={item.mix === 'concatenate'} disabled={busy} onClick={() => void onMix(item, 'concatenate')}>Hold the picture</Button>
        </div>
      )}
    </div>
  )
}

const Icon = ({ status }: { status: PlanItem['status'] }) => {
  if (status === 'ready' || status === 'approved') return <CheckCircle2 aria-hidden="true" className="size-4 text-ok" />
  if (status === 'working') return <Loader2 aria-hidden="true" className="size-4 animate-spin text-changed" />
  if (status === 'needs-you' || status === 'failed') return <CircleAlert aria-hidden="true" className="size-4 text-needs" />
  return <Circle aria-hidden="true" className="size-4 text-muted-foreground/50" />
}

/** One take, playable, with how it sounds. */
function Take({ item, projectId, voices }: { item: PlanItem; projectId: string; voices: Voice[] }) {
  const c = item.candidate
  if (!c) return null
  const voice = voices.find((v) => v.voice_id === c.plan.voice_profile_id)?.name
  const score = soundsRight(item)
  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-lg bg-muted px-3 py-2">
      <audio className="h-11 w-40 flex-none" controls preload="none" src={artifactUrl(projectId, c.audio.sha256)} aria-label="Play take" />
      <span className="whitespace-nowrap text-xs">Take{voice ? ` · ${voice}'s voice` : ''}{c.fit_notes?.length ? ` · ${c.fit_notes.join(', ')}` : ''}</span>
      <span className="flex-1" />
      {score !== null && (
        <span className="tnum whitespace-nowrap text-xs text-muted-foreground">sounds right <strong className="font-medium text-foreground">{score.toFixed(2)}</strong></span>
      )}
    </div>
  )
}

/** What a finished line reads as, in Voltage's words. */
const said = (item: PlanItem, who: string | null, voice?: string) => {
  const at = clock(item.selection.start)
  const by = who && voice ? `, in the ${who}'s own voice` : voice ? `, in ${voice}'s voice` : ''
  return item.mix === 'concatenate'
    ? `Added “${item.new_text}” after ${at}${by}.`
    : `Said “${item.new_text}” at ${at}${by}.`
}

/** The agent's plan: what it will change, or is changing, line by line. */
export function PlanCard({
  plan, speakers, voices, projectId, busy, onToggle, onReword, onInclude, onRun, onAdjust, onAnswer, onRedo, onApproveAll,
  onDelivery, onMix, onStop,
}: PlanCardProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  // The item whose change is on its way to the server: its controls wait, and say so.
  const [pending, setPending] = useState<string | null>(null)
  const run = async (id: string, fn: () => void | Promise<unknown>) => {
    setPending(id)
    try { await fn() } finally { setPending((p) => (p === id ? null : p)) }
  }
  const planned = plan.items.filter((i) => i.kind === 'planned' && i.status !== 'dismissed')
  const suggestions = plan.items.filter((i) => i.kind === 'suggestion' && i.status === 'suggested')
  const ticked = planned.filter((i) => i.enabled)
  const ready = planned.filter((i) => i.status === 'ready')
  const settled = planned.filter((i) => ['ready', 'approved', 'needs-you', 'failed'].includes(i.status))
  const proposed = plan.status === 'proposed' || plan.status === 'clarifying'
  const running = plan.status === 'running' || plan.status === 'stopping'
  // Ticked lines not yet voiced: what Go ahead will voice this time.
  const toVoice = ticked.filter((i) => i.status === 'planned')
  const voiced = planned.filter((i) => i.status === 'ready' || i.status === 'approved')
  const who = (item: PlanItem) => speakers.find((s) => s.label === item.speaker)
  const name = (item: PlanItem) => who(item)?.name ?? (item.speaker ? `Speaker ${item.speaker}` : null)
  const voiceOf = (item: PlanItem) => voices.find((v) => v.voice_id === item.candidate?.plan.voice_profile_id)?.name
  const cast = new Set(planned.map((i) => i.speaker).filter(Boolean)).size

  const commit = (item: PlanItem) => {
    const text = (drafts[item.item_id] ?? item.new_text).trim()
    if (text && text !== item.new_text) void run(item.item_id, () => onReword(item, text))
    setDrafts(({ [item.item_id]: _, ...rest }) => rest)
  }

  return (
    <div className="flex flex-col gap-3">
      {proposed && suggestions.length > 0 && (
        <div className="text-sm leading-normal text-muted-foreground">
          I also noticed {suggestions.map((s, k) => (
            <span key={s.item_id}>{k > 0 && ' and '}{s.old_text ? <>“{s.old_text}”</> : 'a moment'} at {clock(s.selection.start)}</span>
          ))}. I'll ask about {suggestions.length === 1 ? 'it' : 'those'} after {planned.length === 1 ? 'this one' : `these ${planned.length}`}, so you can see {planned.length === 1 ? 'it' : 'them'} first.
        </div>
      )}
      <div className="flex flex-col rounded-lg border bg-card px-4 pt-1 pb-4 text-card-foreground shadow-xs" data-testid="plan">
        <div className="flex items-center gap-2.5 pt-3 pb-2">
          <h2 className="m-0 text-sm font-semibold">The plan</h2>
          <span className="tnum whitespace-nowrap text-xs text-muted-foreground">
            {proposed
              ? `${planned.length} ${planned.length === 1 ? 'change' : 'changes'}${cast > 1 ? ` · ${cast} speakers` : ''}${voiced.length > 0 && toVoice.length > 0 ? ` · ${voiced.length} voiced` : ''}`
              : plan.status === 'stopping' ? 'Stopping after this line…'
              : `${settled.length} of ${ticked.length} done`}
          </span>
          {!proposed && (
            <>
              <span className="flex-1" />
              <Progress className="w-32 bg-muted" aria-label="Voicing the plan" value={Math.round(ticked.length ? (settled.length / ticked.length) * 100 : 0)} />
              {running && onStop && (
                <Button variant="outline" size="sm" className="hover:border-destructive/40 hover:text-destructive" onClick={() => void run('stop', onStop)} disabled={plan.status === 'stopping' || pending === 'stop'} aria-busy={pending === 'stop' || undefined}>
                  {plan.status === 'stopping' || pending === 'stop' ? 'Stopping…' : 'Stop'}
                </Button>
              )}
            </>
          )}
        </div>

        {proposed && planned.length === 0 && (
          <div className="border-t pt-3 pb-1 text-sm leading-normal text-muted-foreground" data-testid="plan-empty">
            Nothing to change for that. <Markdown as="span" text={plan.summary} /> Try saying what should be different, or click a line to change it yourself.
          </div>
        )}
        {planned.map((item) => {
          const at = clock(item.selection.start)
          const label = name(item)
          return (
            <div key={item.item_id} className="flex items-start gap-3 border-t py-3" data-status={item.status} aria-busy={pending === item.item_id || undefined}>
              {proposed ? (
                <label className="-mt-2.5 -ml-3 flex size-10 flex-none cursor-pointer items-center justify-center pointer-coarse:size-11">
                  <input
                    type="checkbox"
                    className="size-4 cursor-pointer accent-primary focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    checked={item.enabled}
                    disabled={pending === item.item_id}
                    aria-label={`Include the change at ${at}`}
                    onChange={(e) => void run(item.item_id, () => onToggle(item, e.target.checked))}
                  />
                </label>
              ) : (
                <span className="flex flex-none pt-0.5"><Icon status={item.status} /></span>
              )}
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                {proposed ? (
                  <>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {label && <Avatar name={label} slot={speakerSlot(speakers, item.speaker)} size={18} />}
                      <span>{label ? `${label}, ${at}` : at}</span>
                      <span className="flex-1" />
                      <span>{KIND[item.mix]}</span>
                    </div>
                    <Input
                      className="text-sm md:text-sm"
                      aria-label={`New wording at ${at}`}
                      value={drafts[item.item_id] ?? item.new_text}
                      onChange={(e) => setDrafts((d) => ({ ...d, [item.item_id]: e.target.value }))}
                      onBlur={() => commit(item)}
                      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
                    />
                    {(item.note ?? item.reason) && <div className="text-sm leading-normal text-muted-foreground">{item.note ?? item.reason}</div>}
                    {(onDelivery || onMix) && <ItemControls item={item} onDelivery={(i, d) => run(i.item_id, () => onDelivery!(i, d))} onMix={onMix ? (i, m) => run(i.item_id, () => onMix(i, m)) : undefined} busy={pending === item.item_id} />}
                    {(item.status === 'ready' || item.status === 'approved') && item.candidate && (
                      <>
                        <div className="text-sm leading-normal text-muted-foreground">Already voiced; it keeps this take unless you change the words, the delivery or how it meets the picture.</div>
                        <Take item={item} projectId={projectId} voices={voices} />
                      </>
                    )}
                  </>
                ) : (
                  <>
                    {item.status === 'ready' && (
                      <>
                        <div className="text-sm leading-normal">{said(item, label, voiceOf(item))}</div>
                        {item.note && <div className="text-sm leading-normal text-muted-foreground">{item.note}.</div>}
                        <Take item={item} projectId={projectId} voices={voices} />
                      </>
                    )}
                    {item.status === 'approved' && (
                      <div className="text-sm leading-normal">{said(item, label, voiceOf(item))} <span className="text-sm leading-normal text-muted-foreground">Approved.</span></div>
                    )}
                    {item.status === 'planned' && (
                      <div className="text-sm text-muted-foreground">{item.mix === 'concatenate' ? `Add “${item.new_text}” after ${at}` : `Say “${item.new_text}” at ${at}`}</div>
                    )}
                    {item.status === 'working' && (
                      <>
                        <div className="text-sm leading-normal">{item.mix === 'concatenate' ? `Adding “${item.new_text}” after ${at}.` : `Voicing “${item.new_text}” at ${at}.`}</div>
                        <div className="text-sm leading-normal text-muted-foreground" data-testid="narration" role="status">{item.progress ?? 'Starting…'}</div>
                      </>
                    )}
                    {item.status === 'needs-you' && item.question && (
                      <>
                        <div className="text-sm leading-normal">{item.question.question}</div>
                        <div className="flex flex-col gap-2.5 rounded-lg border border-needs/30 bg-needs-soft p-3" data-testid="needs-you" role="status">
                          <div className="flex items-center gap-2 text-xs text-muted-foreground"><Presence size={14} /><span>Voltage recommends</span></div>
                          {item.question.options.map((o, k) => k === 0 ? (
                            <Button key={k} className="h-auto w-full flex-col items-start gap-0.5 py-2 text-left whitespace-normal sm:w-auto" onClick={() => void run(item.item_id, () => onAnswer(item, o))} disabled={busy || pending === item.item_id} aria-busy={pending === item.item_id || undefined}>
                              <span className="text-sm font-semibold">{o.label}</span>
                              <span className="text-xs font-normal opacity-80">
                                {o.text ? 'Keeps the meaning, fits the gap, nothing else changes.' : o.warning ?? 'The simplest change.'}
                              </span>
                            </Button>
                          ) : null)}
                          <div className="flex flex-wrap gap-2">
                            {item.question.options.slice(1).map((o, k) => (
                              <Button key={k} variant="outline" onClick={() => void run(item.item_id, () => onAnswer(item, o))} disabled={busy || pending === item.item_id}>
                                {o.label}{o.warning && <span className="font-normal text-destructive"> {o.warning}</span>}
                              </Button>
                            ))}
                          </div>
                        </div>
                      </>
                    )}
                    {item.status === 'failed' && (
                      <div className="flex items-center gap-2.5 text-sm text-destructive" role="alert">
                        <span>{item.error ?? 'This line could not be voiced.'}</span>
                        <Button variant="outline" onClick={() => void run(item.item_id, () => onRedo(item))} disabled={busy || pending === item.item_id} aria-busy={pending === item.item_id || undefined}>{pending === item.item_id ? 'Redoing…' : 'Redo'}</Button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )
        })}

        {proposed && (
          <div className="flex items-center gap-2.5 border-t pt-3">
            <span className="text-sm leading-snug text-muted-foreground">{estimateText(plan.estimate)}</span>
            <span className="flex-1" />
            {onAdjust && <Button variant="outline" onClick={onAdjust}>Adjust</Button>}
            <Button onClick={() => void run('run', onRun)} disabled={busy || pending === 'run' || toVoice.length === 0 || plan.status === 'clarifying'} aria-busy={pending === 'run' || undefined}>
              {pending === 'run' ? 'Starting…' : voiced.length > 0 && toVoice.length > 0 ? `Voice ${toVoice.length === 1 ? 'the change' : `these ${toVoice.length}`}` : 'Go ahead'}
            </Button>
          </div>
        )}
      </div>

      {!proposed && suggestions.map((item) => (
        <div key={item.item_id} className="flex items-start gap-2.5 rounded-lg border border-dashed p-3" data-testid="suggestion">
          <Lightbulb aria-hidden="true" className="mt-0.5 size-4 flex-none text-muted-foreground" />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="text-sm leading-normal">
              <strong>Noticed:</strong> at {clock(item.selection.start)} {name(item) ?? 'the line'} says “{item.old_text}”
              {item.reason ? `, ${item.reason.charAt(0).toLowerCase()}${item.reason.slice(1).replace(/\.$/, '')}` : ''}.
              {' '}Change it to “{item.new_text}”?
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void run(item.item_id, () => onInclude(item, true))} disabled={pending === item.item_id}>Add to plan</Button>
              <Button variant="outline" onClick={() => void run(item.item_id, () => onInclude(item, false))} disabled={pending === item.item_id}>Leave it</Button>
            </div>
          </div>
        </div>
      ))}

      {/* The last thing in the panel is what you do next. */}
      {!proposed && ready.length > 0 && !busy && (
        <div className="flex items-center gap-3 rounded-lg border bg-card p-3 text-card-foreground shadow-xs" data-testid="next-action">
          <span className="flex-1 text-sm">
            {ready.length === 1 ? 'One change is' : `${ready.length} changes are`} ready to hear and ship.
          </span>
          <Button onClick={onApproveAll}>Review and ship</Button>
        </div>
      )}
    </div>
  )
}
