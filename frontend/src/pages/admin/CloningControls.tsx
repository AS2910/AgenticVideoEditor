import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { formatDate } from '../../lib/dates'
import { said } from '../fmt'
import { field } from './ui'
import type { CloningState } from './traceApi'
import { getCloning, restoreCloning, setCloneLimits, suspendCloning } from './traceApi'

/** A reason is required; it goes in the audit trail. The verb is last. */
function WhyForm({ verb, busyVerb, onSubmit, danger, children }: {
  verb: string; busyVerb: string; onSubmit: (reason: string) => Promise<void>; danger?: boolean; children?: ReactNode
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const go = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try { await onSubmit(reason.trim()); setReason('') } catch (err) { setError(said(err, 'That did not work.')) } finally { setBusy(false) }
  }
  return (
    <form className="flex flex-wrap items-end gap-2.5" onSubmit={(e) => void go(e)} aria-label={verb}>
      {children}
      <label className="flex min-w-0 flex-[1_1_200px] flex-col gap-1"><span className="text-[13px] font-semibold">Why</span>
        <input className={field} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} placeholder="kept in the audit trail" />
      </label>
      <button type="submit" className={`${danger ? 'btn ink sm' : 'btn sm'} pointer-coarse:min-h-11`} disabled={busy || reason.trim().length < 3}>{busy ? busyVerb : verb}</button>
      {error && <p className="m-0 basis-full text-sm text-destructive" role="alert">{error}</p>}
    </form>
  )
}

/** Voice consent V1, step 7: one person's voice cloning, on their admin view. Whether it is
 *  suspended (and why), their clone limits and what they used, their cloned voices by status,
 *  then Suspend cloning (every cloned voice of theirs stops speaking and no new clone is made)
 *  or Restore, each with a reason for the audit trail. Hidden while the voice checks are off for
 *  them and they are not suspended. */
export function CloningControls({ owner, onChange }: { owner: string; onChange?: () => void }) {
  const [state, setState] = useState<CloningState | null>(null)
  const [day, setDay] = useState('5')
  const [month, setMonth] = useState('30')
  const load = useCallback(() => {
    getCloning(owner).then((s) => {
      if (typeof s?.limits?.day !== 'number') return
      setState(s); setDay(String(s.limits.day)); setMonth(String(s.limits.month))
    }).catch(() => setState(null))
  }, [owner])
  useEffect(load, [load])
  if (!state || (!state.enabled && !state.suspended)) return null
  const done = () => { load(); onChange?.() }
  const v = state.voices
  return (
    <div className="flex min-w-0 flex-col gap-2.5 rounded-[10px] border border-line2 p-3.5" data-testid="user-cloning">
      <div className="flex flex-wrap items-baseline gap-2">
        <h4 className="tag m-0 text-faint">Voice cloning</h4>
        {state.suspended ? <span className="stamp need" data-testid="cloning-suspended">Cloning suspended</span> : <span className="stamp quiet">Cloning allowed</span>}
      </div>
      {state.suspended && <p className="m-0 text-sm">Suspended <span className="tnum">{formatDate(state.suspended.at)}</span> by {state.suspended.by}: {state.suspended.reason}</p>}
      <p className="m-0 text-[13px]">
        Limits {state.limits.day} a day, {state.limits.month} in 30 days · used <span className="tnum">{state.used.day}</span> today, <span className="tnum">{state.used.month}</span> in 30 days
      </p>
      <p className="m-0 text-[13px] text-muted-foreground">
        Cloned voices: {v.active} working, {v.suspended} suspended, {v.withdrawn} withdrawn
      </p>
      <WhyForm verb="Change limits" busyVerb="Saving…" onSubmit={async (r) => { await setCloneLimits(owner, Number(day), Number(month), r); done() }}>
        <label className="flex w-24 flex-col gap-1"><span className="text-[13px] font-semibold">A day</span>
          <input className={field} type="number" min="0" max="1000" step="1" value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
        <label className="flex w-24 flex-col gap-1"><span className="text-[13px] font-semibold">In 30 days</span>
          <input className={field} type="number" min="0" max="10000" step="1" value={month} onChange={(e) => setMonth(e.target.value)} />
        </label>
      </WhyForm>
      {state.suspended
        ? <WhyForm verb="Restore cloning" busyVerb="Restoring…" onSubmit={async (r) => { await restoreCloning(owner, r); done() }}>
            <p className="m-0 basis-full text-[13px] text-muted-foreground">The voices the suspension stopped work again and they can clone. A withdrawn voice stays withdrawn.</p>
          </WhyForm>
        : <WhyForm danger verb="Suspend cloning" busyVerb="Suspending…" onSubmit={async (r) => { await suspendCloning(owner, r); done() }}>
            <p className="m-0 basis-full text-[13px] text-muted-foreground">Every cloned voice of theirs stops speaking and they cannot clone a new one until you restore it.</p>
          </WhyForm>}
    </div>
  )
}
