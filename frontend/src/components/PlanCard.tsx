import { useState } from 'react'
import type { Plan, PlanItem, Speaker, Voice } from '../types'
import { artifactUrl } from '../api'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { soundsRight } from '../transcript/planText'
import { Avatar } from './Avatar'
import { CheckCircle2, Circle, CircleAlert, Lightbulb, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Markdown } from './Markdown'
import { byAccent } from '../lib/voices'

interface PlanCardProps {
  plan: Plan
  speakers: Speaker[]
  voices: Voice[]
  projectId: string
  /** A turn of Voltage is running: no second ask until it is done. */
  busy?: boolean
  /** "Adjust": say what to change in the composer. */
  onAdjust?: () => void
  /** Another take of a line, or a failed one again — asked of Voltage in words. */
  onRedo: (item: PlanItem) => void | Promise<unknown>
  /** 15e: pick the voice the plan speaks in (the lines not yet voiced). */
  onVoice?: (voiceId: string) => void | Promise<unknown>
}

const KIND: Record<string, string> = { replace: 'Replaces the line', concatenate: 'Added after the line, the picture makes room', over: 'Added after the line, over the picture', layer: 'Over the original sound', remove: 'Removes the line' }

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

/** The agent's plan: what it will change, or is changing, line by line. Every
 *  change to it is said to Voltage in words (20c); the card only shows where
 *  things stand, plays each take, and asks for another. */
export function PlanCard({ plan, speakers, voices, projectId, busy, onAdjust, onRedo, onVoice }: PlanCardProps) {
  const [pickingVoice, setPickingVoice] = useState(false)
  const planVoice = voices.find((v) => v.voice_id === plan.voice)
  // The item whose ask is on its way: its button waits, and says so.
  const [pending, setPending] = useState<string | null>(null)
  const run = async (id: string, fn: () => void | Promise<unknown>) => {
    setPending(id)
    try { await fn() } finally { setPending((p) => (p === id ? null : p)) }
  }
  const planned = plan.items.filter((i) => i.kind === 'planned' && i.enabled && i.status !== 'dismissed')
  const suggestions = plan.items.filter((i) => i.kind === 'suggestion' && i.status === 'suggested')
  const settled = planned.filter((i) => ['ready', 'approved', 'needs-you', 'failed'].includes(i.status))
  const proposed = plan.status === 'proposed' || plan.status === 'clarifying'
  const running = plan.status === 'running' || plan.status === 'stopping'
  const toVoice = planned.filter((i) => i.status === 'planned')
  const voiced = planned.filter((i) => i.status === 'ready' || i.status === 'approved')
  const who = (item: PlanItem) => speakers.find((s) => s.label === item.speaker)
  const name = (item: PlanItem) => who(item)?.name ?? (item.speaker ? `Speaker ${item.speaker}` : null)
  const voiceOf = (item: PlanItem) => voices.find((v) => v.voice_id === item.candidate?.plan.voice_profile_id)?.name
  const cast = new Set(planned.map((i) => i.speaker).filter(Boolean)).size

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
              : `${settled.length} of ${planned.length} done`}
          </span>
        </div>
        {(plan.voice_asked || plan.voice_note) && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 pb-2 text-sm" data-testid="plan-voice">
            <span className="text-muted-foreground">Voice</span>
            {pickingVoice && onVoice ? (
              <select
                className="h-8 max-w-52 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 pointer-coarse:h-11 dark:bg-input/30 dark:[&>option]:bg-popover"
                aria-label="The plan's voice"
                autoFocus
                value={plan.voice ?? ''}
                onChange={(e) => { setPickingVoice(false); void run('voice', () => onVoice(e.target.value)) }}
                onBlur={() => setPickingVoice(false)}
                onKeyDown={(e) => { if (e.key === 'Escape') setPickingVoice(false) }}
              >
                {byAccent(voices).map(([accent, group]) => (
                  <optgroup key={accent} label={accent}>
                    {group.map((v) => <option key={v.voice_id} value={v.voice_id}>{[v.name, [v.gender, v.accent].filter(Boolean).join(', ')].filter(Boolean).join(' · ')}</option>)}
                  </optgroup>
                ))}
              </select>
            ) : (
              <>
                <span className="font-medium">{planVoice ? planVoice.name : 'the default'}</span>
                {planVoice && (planVoice.gender || planVoice.accent) && <span className="text-muted-foreground">{[planVoice.gender, planVoice.accent].filter(Boolean).join(', ')}</span>}
                {onVoice && !running && <Button type="button" variant="link" className="h-auto px-1 py-0 text-sm text-primary underline-offset-4 hover:underline pointer-coarse:h-11" onClick={() => setPickingVoice(true)} disabled={pending === 'voice'}>Change</Button>}
              </>
            )}
            {plan.voice_note && <span className="basis-full text-muted-foreground"><Markdown as="span" text={plan.voice_note} />{voiced.length > 0 && toVoice.length === 0 && plan.voice_asked ? ' A line already voiced keeps its take until you redo it.' : ''}</span>}
          </div>
        )}

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
              <span className="flex flex-none pt-0.5"><Icon status={item.status} /></span>
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {label && <Avatar name={label} slot={speakerSlot(speakers, item.speaker)} size={18} />}
                  <span>{label ? `${label}, ${at}` : at}</span>
                  <span className="flex-1" />
                  <span>{KIND[item.mix]}</span>
                </div>
                {item.status === 'planned' && (
                  <>
                    <div className="text-sm leading-normal">{item.mix === 'concatenate' ? `Add “${item.new_text}” after ${at}` : item.mix === 'remove' ? `Remove the line at ${at}` : `Say “${item.new_text}” at ${at}`}</div>
                    {(item.note ?? item.reason) && <div className="text-sm leading-normal text-muted-foreground">{item.note ?? item.reason}</div>}
                  </>
                )}
                {item.status === 'working' && (
                  <>
                    <div className="text-sm leading-normal">{item.mix === 'concatenate' ? `Adding “${item.new_text}” after ${at}.` : `Voicing “${item.new_text}” at ${at}.`}</div>
                    <div className="text-sm leading-normal text-muted-foreground" data-testid="narration" role="status">{item.progress ?? 'Starting…'}</div>
                  </>
                )}
                {item.status === 'ready' && (
                  <>
                    <div className="text-sm leading-normal">{said(item, label, voiceOf(item))}</div>
                    {proposed
                      ? <div className="text-sm leading-normal text-muted-foreground">Already voiced; it keeps this take unless you change the words, the delivery or how it meets the picture.</div>
                      : item.note && <div className="text-sm leading-normal text-muted-foreground">{item.note}.</div>}
                    <Take item={item} projectId={projectId} voices={voices} />
                    <div>
                      <Button variant="outline" size="sm" onClick={() => void run(item.item_id, () => onRedo(item))} disabled={busy || pending === item.item_id} aria-busy={pending === item.item_id || undefined}>
                        {pending === item.item_id ? 'Asking…' : 'Another take'}
                      </Button>
                    </div>
                  </>
                )}
                {item.status === 'approved' && (
                  <div className="text-sm leading-normal">{said(item, label, voiceOf(item))} <span className="text-sm leading-normal text-muted-foreground">Approved.</span></div>
                )}
                {item.status === 'needs-you' && item.question && (
                  <div className="text-sm leading-normal" data-testid="needs-you" role="status">{item.question.question}</div>
                )}
                {item.status === 'failed' && (
                  <div className="flex items-center gap-2.5 text-sm text-destructive" role="alert">
                    <span>{item.error ?? 'This line could not be voiced.'}</span>
                    <Button variant="outline" onClick={() => void run(item.item_id, () => onRedo(item))} disabled={busy || pending === item.item_id} aria-busy={pending === item.item_id || undefined}>{pending === item.item_id ? 'Redoing…' : 'Redo'}</Button>
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {proposed && onAdjust && (
          <div className="flex items-center gap-2.5 border-t pt-3">
            <span className="flex-1" />
            <Button variant="outline" onClick={onAdjust}>Adjust</Button>
          </div>
        )}
      </div>

      {!proposed && suggestions.map((item) => (
        <div key={item.item_id} className="flex items-start gap-2.5 rounded-lg border border-dashed p-3" data-testid="suggestion">
          <Lightbulb aria-hidden="true" className="mt-0.5 size-4 flex-none text-muted-foreground" />
          <div className="min-w-0 flex-1 text-sm leading-normal">
            <strong>Noticed:</strong> at {clock(item.selection.start)} {name(item) ?? 'the line'} says “{item.old_text}”
            {item.reason ? `, ${item.reason.charAt(0).toLowerCase()}${item.reason.slice(1).replace(/\.$/, '')}` : ''}.
            {' '}Change it to “{item.new_text}”?
          </div>
        </div>
      ))}

      {/* What you do next — review and ship — is the panel's own last card (ShipCard, 15e). */}
    </div>
  )
}
