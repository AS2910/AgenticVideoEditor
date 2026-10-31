import { useEffect } from 'react'
import { cn } from '@/lib/utils'
import { AttestationForm } from './AttestationForm'
import { useConsent } from './context'
import { LINE, editLine, refusalKind } from './copy'
import type { AttestationFacts, LineRefusalFacts } from './types'

/** Voice consent V1 step 6: a line the guard refused, on the line and in the
 *  chat. Blocked: the guard's sentence and [Edit the line]. Held: a held
 *  state with the plan's sentence, until the notification says it was
 *  decided (cleared: Retry; not cleared: why, and [Edit the line]).
 *  Suspended: the plan's sentence. Null for any other reason. */
export function LineRefusal({ reason, code, videoId, words, tone = 'row', onEdit, onRetry }: {
  reason: string | null | undefined
  code?: LineRefusalFacts['code'] | null
  videoId?: string | null
  /** The line's words as they were sent (a held line's notification names them). */
  words?: string | null
  tone?: 'row' | 'pane'
  onEdit?: () => void
  onRetry?: () => void
}) {
  const { on, decisionFor, watchHeld } = useConsent()
  const kind = on ? refusalKind(reason, code) : null
  const decision = kind === 'held' ? decisionFor(videoId, words) : null
  const waiting = kind === 'held' && !decision
  useEffect(() => (waiting ? watchHeld() : undefined), [waiting, watchHeld])
  if (!kind) return null
  const muted = tone === 'pane' ? 'pm' : 'text-muted-foreground'
  const edit = onEdit && (
    <span className="-ml-2 flex"><button type="button" className="act" onClick={onEdit} data-testid="edit-the-line">{LINE.edit}</button></span>
  )
  if (kind === 'held') {
    return (
      <div className="flex min-w-0 flex-col gap-1.5" data-testid="line-held" data-state={decision ? (decision.cleared ? 'cleared' : 'not-cleared') : 'held'}>
        <span className="flex flex-wrap items-center gap-2">
          <span className={cn('stamp', decision?.cleared ? 'in' : 'need')} role="status">{decision ? (decision.cleared ? 'Cleared' : 'Not cleared') : 'Held for a check'}</span>
        </span>
        <p className={cn('m-0 text-sm', !decision && muted)} data-testid="line-refusal-text">{decision ? decision.title : LINE.held}</p>
        {decision?.cleared && onRetry && <span className="-ml-2 flex"><button type="button" className="act" onClick={onRetry} data-testid="voice-it-now">Voice it now</button></span>}
        {decision && !decision.cleared && edit}
      </div>
    )
  }
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid={kind === 'blocked' ? 'line-blocked' : 'line-suspended'}>
      <p className={cn('m-0 text-sm', tone === 'row' && 'text-needs')} data-testid="line-refusal-text">{kind === 'suspended' ? LINE.suspended : reason}</p>
      {kind === 'blocked' && edit}
    </div>
  )
}

/** The guard's refusal carried by a step of a turn, in the chat (whole, with [Edit the line]). */
export function RefusalNote({ refusal, videoId }: { refusal: LineRefusalFacts; videoId?: string | null }) {
  return (
    <div className="rise flex min-w-0 flex-col gap-2 rounded-xl border-[1.5px] border-pline p-3.5" data-testid="refusal-note">
      <LineRefusal tone="pane" reason={refusal.message} code={refusal.code} videoId={videoId}
        onEdit={refusal.start != null ? () => editLine(refusal.start!, refusal.end) : undefined} />
    </div>
  )
}

/** The turn paused on the attestation (a question of kind attestation_required): the
 *  modal's content inline in the pane. Use this voice posts the attestation and
 *  answers the card, so the turn goes on; Cancel answers Cancel. */
export function AttestationCard({ facts, onAnswer, tone = 'pane' }: { facts: AttestationFacts; onAnswer?: (option: string) => void; tone?: 'pane' | 'sheet' }) {
  return (
    <div className={cn('min-w-0', tone === 'pane' ? 'gate' : 'rounded-lg border-[1.5px] border-dashed border-ink bg-card p-3')} role="group" aria-label="Your answer is needed" data-testid="attestation-card">
      <span className={cn('tag', tone === 'pane' ? 'text-volt' : 'text-muted-foreground')}>Your answer is needed</span>
      <AttestationForm facts={facts} tone={tone === 'pane' ? 'pane' : 'sheet'} onDone={() => onAnswer?.('Use this voice')} onCancel={() => onAnswer?.('Cancel')} />
    </div>
  )
}
