import { useId, useState, type ReactNode } from 'react'
import { attestVoice, ApiError } from '../api'
import { said } from '../pages/fmt'
import { cn } from '@/lib/utils'
import { ATTEST, attestTitle, type AttestChoice } from './copy'
import { LearnMore } from './LearnMore'
import type { AttestationFacts } from './types'

/** Where the form stands: the modal (a light sheet), the pane (black), a batch row. */
export type FormTone = 'sheet' | 'pane'

const TONE = {
  sheet: { muted: 'text-muted-foreground', warn: 'text-needs', box: 'border-line2 bg-sunk', cancel: 'btn sm', accept: 'btn volt sm' },
  pane: { muted: 'pm', warn: 'text-warn', box: 'border-pline bg-psunk', cancel: 'btn ghost sm', accept: 'btn volt sm' },
} as const

/** In the pane the card can be taller than the thread (1280x720 with a tip open): the
 *  action row stays at the bottom of the thread's visible area while the rest scrolls
 *  under it, on the pane's own black so nothing shows through. Its bottom is the thread's
 *  edge, not its 24 px padding (the thread is `py-6`), so nothing peeks out beneath it. */
const STICKY = 'sticky -bottom-6 z-[1] -mx-4 border-t border-pline bg-pane px-4 pt-3 pb-3'

/** Voice consent V1 step 6: the attestation, in the plan's words. Whose voice
 *  (two labelled radios), the confirmation box, the warning, then Cancel and
 *  Use this voice; the button stays off until a choice and the box. "Use this
 *  voice" posts the attestation; `onDone` runs once it is saved. The title is
 *  rendered by the caller (`title`), so a dialog can use its own heading.
 *  `stickyActions`: Cancel and Use this voice stay in view at the bottom of
 *  the scrolling thread (the pane card). */
export function AttestationForm({ facts, tone = 'sheet', title, onDone, onCancel, busyLabel = 'Saving…', stickyActions = false }: {
  facts: AttestationFacts
  tone?: FormTone
  title?: (text: string) => ReactNode
  onDone: () => void | Promise<void>
  onCancel: () => void
  busyLabel?: string
  stickyActions?: boolean
}) {
  const id = useId()
  const [choice, setChoice] = useState<AttestChoice | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const t = TONE[tone]
  const ready = choice !== null && confirmed && !busy
  const heading = attestTitle(facts)

  const accept = async () => {
    if (!ready || !choice) return
    setBusy(true); setError(null)
    try {
      await attestVoice(facts.video_id, facts.voice, choice, facts.statement_version)
      await onDone()
    } catch (e) {
      // The wording moved on since the card was made: the person reads it again (the copy here is the current one).
      setError(e instanceof ApiError && e.status === 409 ? said(e, 'The wording has changed. Read it again and confirm.') : said(e, 'That could not be saved. Try again.'))
      setChoice(null); setConfirmed(false)
    } finally { setBusy(false) }
  }

  return (
    // With the action row held at the bottom, a focused choice scrolls clear of it (never under it).
    <div className={cn('flex min-w-0 flex-col gap-3.5', stickyActions && '[&_input]:scroll-mb-20')} data-testid="attestation" role={title ? undefined : 'group'} aria-labelledby={title ? undefined : `${id}-title`} aria-describedby={`${id}-body`}>
      {title ? title(heading) : <p id={`${id}-title`} className="disp m-0 text-lg font-semibold">{heading}</p>}
      <p id={`${id}-body`} className="m-0 text-[15px] leading-relaxed">{ATTEST.body}</p>
      <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0" disabled={busy}>
        <legend className="sr-only">Whose voice is it?</legend>
        {ATTEST.choices.map((c) => (
          <label key={c.choice} className={cn('flex min-h-11 cursor-pointer items-start gap-2.5 rounded-lg border-[1.5px] px-3 py-2.5 text-sm has-[:checked]:border-volt has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50', t.box)}>
            <input type="radio" name={`${id}-choice`} value={c.choice} className="mt-0.5 size-4 shrink-0 accent-volt" checked={choice === c.choice} onChange={() => setChoice(c.choice)} data-testid={`attest-${c.choice}`} />
            <span className="min-w-0">{c.label}</span>
          </label>
        ))}
      </fieldset>
      <label className="flex min-h-11 cursor-pointer items-start gap-2.5 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 shrink-0 accent-volt" checked={confirmed} disabled={busy} onChange={(e) => setConfirmed(e.target.checked)} data-testid="attest-confirm" />
        <span className="min-w-0">{ATTEST.confirm}</span>
      </label>
      <p className={cn('m-0 text-[13px]', t.muted)}><span data-testid="attest-warning">{ATTEST.warning}</span> <LearnMore className={t.muted} /></p>
      {error && <p className={cn('m-0 text-[13px]', t.warn)} role="alert">{error}</p>}
      {/* The person's next action is the last thing: Cancel, then Use this voice. */}
      <div className={cn('flex flex-wrap items-center justify-end gap-2', stickyActions && STICKY)} data-testid="attest-actions">
        <button type="button" className={t.cancel} onClick={onCancel} disabled={busy} data-testid="attest-cancel">{ATTEST.cancel}</button>
        <button type="button" className={t.accept} onClick={() => void accept()} disabled={!ready} aria-disabled={!ready} aria-busy={busy || undefined} data-testid="attest-accept">
          {busy ? busyLabel : ATTEST.accept}
        </button>
      </div>
    </div>
  )
}
