import { useState } from 'react'
import type { Plan, PlanItem, QuestionOption, Speaker, Voice } from '../types'
import { artifactUrl } from '../api'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { estimateText, soundsRight } from '../transcript/planText'
import { Avatar } from './Avatar'
import { Orb } from './Orb'
import styles from './PlanCard.module.css'

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

const KIND: Record<string, string> = { replace: 'Replaces the line', concatenate: 'Added after the line, the picture holds', over: 'Added after the line, over the picture', layer: 'Over the original sound' }
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
    <div className={styles.controls} aria-busy={busy || undefined}>
      {onDelivery && (
        <div className={styles.control} role="group" aria-label={`Delivery at ${at}`}>
          <span className={styles.controlLabel}>Delivery</span>
          <button type="button" className={delivery === null && ownWords === null ? styles.pillOn : styles.pill} aria-pressed={delivery === null} disabled={busy} onClick={() => { setOwnWords(null); if (delivery !== null) void onDelivery(item, null) }}>As spoken</button>
          {DELIVERIES.map((d) => (
            <button key={d} type="button" className={delivery === d ? styles.pillOn : styles.pill} aria-pressed={delivery === d} disabled={busy} onClick={() => { setOwnWords(null); void onDelivery(item, d) }}>{d}</button>
          ))}
          {ownWords === null
            ? <button type="button" className={styles.link} onClick={() => setOwnWords(own ? delivery : '')}>in your words…</button>
            : <input className={styles.ownWords} aria-label={`Delivery at ${at}, in your words`} placeholder="e.g. like a secret" value={ownWords} onChange={(e) => setOwnWords(e.target.value)} onBlur={commitOwn} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />}
        </div>
      )}
      {onMix && item.mix !== 'replace' && (
        <div className={styles.control} role="group" aria-label={`Sound meets picture at ${at}`}>
          <span className={styles.controlLabel}>Sound meets picture</span>
          <button type="button" className={item.mix === 'over' ? styles.pillOn : styles.pill} aria-pressed={item.mix === 'over'} disabled={busy} onClick={() => void onMix(item, 'over')}>Over the picture</button>
          <button type="button" className={item.mix === 'concatenate' ? styles.pillOn : styles.pill} aria-pressed={item.mix === 'concatenate'} disabled={busy} onClick={() => void onMix(item, 'concatenate')}>Hold the picture</button>
        </div>
      )}
    </div>
  )
}

const Icon = ({ status }: { status: PlanItem['status'] }) => {
  if (status === 'ready' || status === 'approved') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7.25" fill="none" stroke="var(--ok)" strokeWidth="1.5" />
        <path d="M5 8.2l2 2 4-4.4" fill="none" stroke="var(--ok)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (status === 'working') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className={styles.spin}>
        <circle cx="8" cy="8" r="7.25" fill="none" stroke="var(--line)" strokeWidth="1.5" />
        <path d="M8 0.75a7.25 7.25 0 0 1 7.25 7.25" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }
  if (status === 'needs-you' || status === 'failed') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7.25" fill="none" stroke="var(--amber)" strokeWidth="1.5" />
        <path d="M8 4.5v4.2" stroke="var(--amber)" strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="8" cy="11.2" r="0.95" fill="var(--amber)" />
      </svg>
    )
  }
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="7.25" fill="none" stroke="var(--line)" strokeWidth="1.5" />
    </svg>
  )
}

/** One take, playable, with how it sounds. */
function Take({ item, projectId, voices }: { item: PlanItem; projectId: string; voices: Voice[] }) {
  const c = item.candidate
  if (!c) return null
  const voice = voices.find((v) => v.voice_id === c.plan.voice_profile_id)?.name
  const score = soundsRight(item)
  return (
    <div className={styles.take}>
      <audio className={styles.audio} controls preload="none" src={artifactUrl(projectId, c.audio.sha256)} aria-label="Play take" />
      <span className={styles.takeLabel}>Take{voice ? ` · ${voice}'s voice` : ''}{c.fit_notes?.length ? ` · ${c.fit_notes.join(', ')}` : ''}</span>
      <span className={styles.spacer} />
      {score !== null && (
        <span className={styles.score}>sounds right <strong>{score.toFixed(2)}</strong></span>
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
    <div className={styles.wrap}>
      {proposed && suggestions.length > 0 && (
        <div className={styles.aside}>
          I also noticed {suggestions.map((s, k) => (
            <span key={s.item_id}>{k > 0 && ' and '}“{s.old_text}” at {clock(s.selection.start)}</span>
          ))}. I'll ask about {suggestions.length === 1 ? 'it' : 'those'} after {planned.length === 1 ? 'this one' : `these ${planned.length}`}, so you can see {planned.length === 1 ? 'it' : 'them'} first.
        </div>
      )}
      <div className={styles.card} data-testid="plan">
        <div className={styles.head}>
          <h2 className={styles.title}>The plan</h2>
          <span className={styles.count}>
            {proposed
              ? `${planned.length} ${planned.length === 1 ? 'change' : 'changes'}${cast > 1 ? ` · ${cast} speakers` : ''}${voiced.length > 0 && toVoice.length > 0 ? ` · ${voiced.length} voiced` : ''}`
              : plan.status === 'stopping' ? 'Stopping after this line…'
              : `${settled.length} of ${ticked.length} done`}
          </span>
          {!proposed && (
            <>
              <span className={styles.spacer} />
              <div className={styles.progress} role="progressbar" aria-label="Voicing the plan" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ticked.length ? (settled.length / ticked.length) * 100 : 0)}>
                <div className={styles.progressFill} style={{ transform: `scaleX(${ticked.length ? settled.length / ticked.length : 0})` }} />
              </div>
              {running && onStop && (
                <button className={styles.stop} onClick={() => void run('stop', onStop)} disabled={plan.status === 'stopping' || pending === 'stop'} aria-busy={pending === 'stop' || undefined}>
                  {plan.status === 'stopping' || pending === 'stop' ? 'Stopping…' : 'Stop'}
                </button>
              )}
            </>
          )}
        </div>

        {proposed && planned.length === 0 && (
          <div className={styles.empty} data-testid="plan-empty">
            Nothing to change for that. {plan.summary} Try saying what should be different, or click a line to change it yourself.
          </div>
        )}
        {planned.map((item) => {
          const at = clock(item.selection.start)
          const label = name(item)
          return (
            <div key={item.item_id} className={styles.item} data-status={item.status} aria-busy={pending === item.item_id || undefined}>
              {proposed ? (
                <label className={styles.tick}>
                  <input
                    type="checkbox"
                    checked={item.enabled}
                    disabled={pending === item.item_id}
                    aria-label={`Include the change at ${at}`}
                    onChange={(e) => void run(item.item_id, () => onToggle(item, e.target.checked))}
                  />
                </label>
              ) : (
                <span className={styles.icon}><Icon status={item.status} /></span>
              )}
              <div className={styles.body}>
                {proposed ? (
                  <>
                    <div className={styles.meta}>
                      {label && <Avatar name={label} slot={speakerSlot(speakers, item.speaker)} size={18} />}
                      <span>{label ? `${label}, ${at}` : at}</span>
                      <span className={styles.spacer} />
                      <span>{KIND[item.mix]}</span>
                    </div>
                    <input
                      className={styles.wording}
                      aria-label={`New wording at ${at}`}
                      value={drafts[item.item_id] ?? item.new_text}
                      onChange={(e) => setDrafts((d) => ({ ...d, [item.item_id]: e.target.value }))}
                      onBlur={() => commit(item)}
                      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
                    />
                    {(item.note ?? item.reason) && <div className={styles.why}>{item.note ?? item.reason}</div>}
                    {(onDelivery || onMix) && <ItemControls item={item} onDelivery={(i, d) => run(i.item_id, () => onDelivery!(i, d))} onMix={onMix ? (i, m) => run(i.item_id, () => onMix(i, m)) : undefined} busy={pending === item.item_id} />}
                    {(item.status === 'ready' || item.status === 'approved') && item.candidate && (
                      <>
                        <div className={styles.quiet}>Already voiced; it keeps this take unless you change the words, the delivery or how it meets the picture.</div>
                        <Take item={item} projectId={projectId} voices={voices} />
                      </>
                    )}
                  </>
                ) : (
                  <>
                    {item.status === 'ready' && (
                      <>
                        <div className={styles.line}>{said(item, label, voiceOf(item))}</div>
                        {item.note && <div className={styles.quiet}>{item.note}.</div>}
                        <Take item={item} projectId={projectId} voices={voices} />
                      </>
                    )}
                    {item.status === 'approved' && (
                      <div className={styles.line}>{said(item, label, voiceOf(item))} <span className={styles.quiet}>Approved.</span></div>
                    )}
                    {item.status === 'planned' && (
                      <div className={styles.quietLine}>{item.mix === 'concatenate' ? `Add “${item.new_text}” after ${at}` : `Say “${item.new_text}” at ${at}`}</div>
                    )}
                    {item.status === 'working' && (
                      <>
                        <div className={styles.line}>{item.mix === 'concatenate' ? `Adding “${item.new_text}” after ${at}.` : `Voicing “${item.new_text}” at ${at}.`}</div>
                        <div className={styles.quiet} data-testid="narration" role="status">{item.progress ?? 'Starting…'}</div>
                      </>
                    )}
                    {item.status === 'needs-you' && item.question && (
                      <>
                        <div className={styles.line}>{item.question.question}</div>
                        <div className={styles.needs} data-testid="needs-you" role="status">
                          <div className={styles.recommends}><Orb size={14} /><span>Voltage recommends</span></div>
                          {item.question.options.map((o, k) => k === 0 ? (
                            <button key={k} className={styles.recommended} onClick={() => void run(item.item_id, () => onAnswer(item, o))} disabled={busy || pending === item.item_id} aria-busy={pending === item.item_id || undefined}>
                              <span className={styles.recommendedLabel}>{o.label}</span>
                              <span className={styles.recommendedWhy}>
                                {o.text ? 'Keeps the meaning, fits the gap, nothing else changes.' : o.warning ?? 'The simplest change.'}
                              </span>
                            </button>
                          ) : null)}
                          <div className={styles.options}>
                            {item.question.options.slice(1).map((o, k) => (
                              <button key={k} className={styles.secondary} onClick={() => void run(item.item_id, () => onAnswer(item, o))} disabled={busy || pending === item.item_id}>
                                {o.label}{o.warning && <span className={styles.warning}> {o.warning}</span>}
                              </button>
                            ))}
                          </div>
                        </div>
                      </>
                    )}
                    {item.status === 'failed' && (
                      <div className={styles.failed} role="alert">
                        <span>{item.error ?? 'This line could not be voiced.'}</span>
                        <button className={styles.secondary} onClick={() => void run(item.item_id, () => onRedo(item))} disabled={busy || pending === item.item_id} aria-busy={pending === item.item_id || undefined}>{pending === item.item_id ? 'Redoing…' : 'Redo'}</button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )
        })}

        {proposed && (
          <div className={styles.foot}>
            <span className={styles.estimate}>{estimateText(plan.estimate)}</span>
            <span className={styles.spacer} />
            {onAdjust && <button className={styles.secondary} onClick={onAdjust}>Adjust</button>}
            <button className={styles.primary} onClick={() => void run('run', onRun)} disabled={busy || pending === 'run' || toVoice.length === 0 || plan.status === 'clarifying'} aria-busy={pending === 'run' || undefined}>
              {pending === 'run' ? 'Starting…' : voiced.length > 0 && toVoice.length > 0 ? `Voice ${toVoice.length === 1 ? 'the change' : `these ${toVoice.length}`}` : 'Go ahead'}
            </button>
          </div>
        )}
      </div>

      {!proposed && suggestions.map((item) => (
        <div key={item.item_id} className={styles.suggestion} data-testid="suggestion">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 1.5a4.5 4.5 0 0 0-2.6 8.2V12h5.2V9.7A4.5 4.5 0 0 0 8 1.5zM6 14h4" fill="none" stroke="var(--muted)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className={styles.body}>
            <div className={styles.noticed}>
              <strong>Noticed:</strong> at {clock(item.selection.start)} {name(item) ?? 'the line'} says “{item.old_text}”
              {item.reason ? `, ${item.reason.charAt(0).toLowerCase()}${item.reason.slice(1).replace(/\.$/, '')}` : ''}.
              {' '}Change it to “{item.new_text}”?
            </div>
            <div className={styles.options}>
              <button className={styles.secondary} onClick={() => void run(item.item_id, () => onInclude(item, true))} disabled={pending === item.item_id}>Add to plan</button>
              <button className={styles.secondary} onClick={() => void run(item.item_id, () => onInclude(item, false))} disabled={pending === item.item_id}>Leave it</button>
            </div>
          </div>
        </div>
      ))}

      {/* The last thing in the panel is what you do next. */}
      {!proposed && ready.length > 0 && !busy && (
        <div className={styles.action} data-testid="next-action">
          <span className={styles.actionText}>
            {ready.length === 1 ? 'One change is' : `${ready.length} changes are`} ready to hear and ship.
          </span>
          <button className={styles.primary} onClick={onApproveAll}>Review and ship</button>
        </div>
      )}
    </div>
  )
}
