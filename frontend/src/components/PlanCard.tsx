import { useState } from 'react'
import type { Plan, PlanItem, QuestionOption, Speaker, Voice } from '../types'
import { artifactUrl } from '../api'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { estimateText, soundsRight } from '../transcript/planText'
import { Avatar } from './Avatar'
import styles from './PlanCard.module.css'

interface PlanCardProps {
  plan: Plan
  speakers: Speaker[]
  voices: Voice[]
  projectId: string
  /** A job is voicing the plan: no second run until it is done. */
  busy?: boolean
  onToggle: (item: PlanItem, enabled: boolean) => void
  onReword: (item: PlanItem, text: string) => void
  onInclude: (item: PlanItem, include: boolean) => void
  onRun: () => void
  onAnswer: (item: PlanItem, option: QuestionOption) => void
  onRedo: (item: PlanItem) => void
  onApproveAll: () => void
}

const MIX_NOTE: Record<string, string> = { replace: 'Replaces the line', concatenate: 'Added after the line', layer: 'Over the original sound' }

const Icon = ({ status }: { status: PlanItem['status'] }) => {
  if (status === 'ready' || status === 'approved') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7.25" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
        <path d="M5 8.2l2 2 4-4.4" fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
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
      <span className={styles.takeLabel}>Take{voice ? `, ${voice}'s voice` : ''}</span>
      <span className={styles.spacer} />
      {score !== null && (
        <span className={styles.score}>sounds right <strong>{score.toFixed(2)}</strong></span>
      )}
    </div>
  )
}

/** The agent's plan: what it will change, or is changing, line by line. */
export function PlanCard({
  plan, speakers, voices, projectId, busy, onToggle, onReword, onInclude, onRun, onAnswer, onRedo, onApproveAll,
}: PlanCardProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const planned = plan.items.filter((i) => i.kind === 'planned' && i.status !== 'dismissed')
  const suggestions = plan.items.filter((i) => i.kind === 'suggestion' && i.status === 'suggested')
  const ticked = planned.filter((i) => i.enabled)
  const ready = planned.filter((i) => i.status === 'ready')
  const settled = planned.filter((i) => ['ready', 'approved', 'needs-you', 'failed'].includes(i.status))
  const proposed = plan.status === 'proposed'
  const who = (item: PlanItem) => speakers.find((s) => s.label === item.speaker)
  const name = (item: PlanItem) => who(item)?.name ?? (item.speaker ? `Speaker ${item.speaker}` : null)

  const commit = (item: PlanItem) => {
    const text = (drafts[item.item_id] ?? item.new_text).trim()
    if (text && text !== item.new_text) onReword(item, text)
    setDrafts(({ [item.item_id]: _, ...rest }) => rest)
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.card} data-testid="plan">
        <div className={styles.head}>
          <span className={styles.title}>Plan</span>
          <span className={styles.count}>
            {proposed
              ? `${planned.length} ${planned.length === 1 ? 'change' : 'changes'}`
              : `${settled.length} of ${ticked.length} ready`}
          </span>
          {!proposed && (
            <>
              <span className={styles.spacer} />
              <div className={styles.progress}>
                <div className={styles.progressFill} style={{ width: `${ticked.length ? (settled.length / ticked.length) * 100 : 0}%` }} />
              </div>
            </>
          )}
        </div>

        {planned.map((item) => {
          const at = clock(item.selection.start)
          const label = name(item)
          return (
            <div key={item.item_id} className={styles.item} data-status={item.status}>
              {proposed ? (
                <input
                  type="checkbox"
                  className={styles.tick}
                  checked={item.enabled}
                  aria-label={`Include the change at ${at}`}
                  onChange={(e) => onToggle(item, e.target.checked)}
                />
              ) : (
                <span className={styles.icon}><Icon status={item.status} /></span>
              )}
              <div className={styles.body}>
                <div className={styles.meta}>
                  {label && <Avatar name={label} slot={speakerSlot(speakers, item.speaker)} size={18} />}
                  <span>{label ? `${label}, ${at}` : at}</span>
                  <span className={styles.spacer} />
                  <span>{item.note ?? item.reason ?? MIX_NOTE[item.mix]}</span>
                </div>
                {proposed ? (
                  <input
                    className={styles.wording}
                    aria-label={`New wording at ${at}`}
                    value={drafts[item.item_id] ?? item.new_text}
                    onChange={(e) => setDrafts((d) => ({ ...d, [item.item_id]: e.target.value }))}
                    onBlur={() => commit(item)}
                    onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
                  />
                ) : (
                  <div className={styles.line}>
                    {item.mix === 'concatenate' ? <>{item.old_text} <ins className={styles.ins}>{item.new_text}</ins></> : item.new_text}
                  </div>
                )}
                {item.status === 'working' && <div className={styles.quiet}>Voicing the line…</div>}
                {item.status === 'ready' && <Take item={item} projectId={projectId} voices={voices} />}
                {item.status === 'approved' && <div className={styles.quiet}>Approved</div>}
                {item.status === 'needs-you' && item.question && (
                  <div className={styles.needs} data-testid="needs-you">
                    <div>{item.question.question}</div>
                    <div className={styles.options}>
                      {item.question.options.map((o, k) => (
                        <button key={k} className={k === 0 ? styles.primary : styles.secondary} onClick={() => onAnswer(item, o)} disabled={busy}>
                          {o.label}
                          {o.warning && <span className={styles.warning}> {o.warning}</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {item.status === 'failed' && (
                  <div className={styles.failed}>
                    <span>{item.error ?? 'This line could not be voiced.'}</span>
                    <button className={styles.secondary} onClick={() => onRedo(item)} disabled={busy}>Redo</button>
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {proposed ? (
          <div className={styles.foot}>
            <span className={styles.estimate}>{estimateText(plan.estimate)}</span>
            <span className={styles.spacer} />
            <button className={styles.primary} onClick={onRun} disabled={busy || ticked.length === 0}>
              Run {ticked.length} {ticked.length === 1 ? 'change' : 'changes'}
            </button>
          </div>
        ) : ready.length > 0 && !busy ? (
          <div className={styles.foot}>
            <span className={styles.spacer} />
            <button className={styles.primary} onClick={onApproveAll}>
              Approve {ready.length} ready {ready.length === 1 ? 'change' : 'changes'}
            </button>
          </div>
        ) : null}
      </div>

      {suggestions.map((item) => (
        <div key={item.item_id} className={styles.suggestion} data-testid="suggestion">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <path d="M8 1.5a4.5 4.5 0 0 0-2.6 8.2V12h5.2V9.7A4.5 4.5 0 0 0 8 1.5zM6 14h4" fill="none" stroke="var(--muted)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className={styles.body}>
            <div className={styles.noticed}>
              <strong>Noticed:</strong> at {clock(item.selection.start)} {name(item) ?? 'the line'} says “{item.old_text}”
              {item.reason ? `, ${item.reason.charAt(0).toLowerCase()}${item.reason.slice(1)}` : ''}.
              {' '}Change it to “{item.new_text}”?
            </div>
            <div className={styles.options}>
              <button className={styles.secondary} onClick={() => onInclude(item, true)}>Add to plan</button>
              <button className={styles.secondary} onClick={() => onInclude(item, false)}>Leave it</button>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
