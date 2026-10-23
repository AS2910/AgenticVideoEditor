import { useCallback, useEffect, useState } from 'react'
import type { AdminAuditEntry } from '../../api'
import { getAdminAudit, revokeAdminShare } from '../../api'
import { formatDate } from '../../lib/dates'
import { said } from '../fmt'
import { field } from './ui'

const WORDS: Record<string, string> = {
  grant: 'Granted credits', refund: 'Refund', suspend: 'Suspended', unsuspend: 'Unsuspended', pause: 'Paused paid work',
  resume: 'Resumed paid work', flag: 'Changed a feature', share_revoke: 'Took a link down',
}

function detail(e: AdminAuditEntry): string {
  const d = e.details
  if (e.action === 'grant') return `${d.credits} credits`
  if (e.action === 'refund') return d.invoice ? `${d.invoice}` : `${d.credit_reversal} credits taken back`
  if (e.action === 'flag') return `${d.flag} ${d.enabled === null ? 'reset' : d.enabled ? 'on' : 'off'}`
  if (e.action === 'share_revoke') return `${d.share_id}`
  return ''
}

/** Newest first: when, who, what, whose account, why. */
export function AuditList({ entries }: { entries: AdminAuditEntry[] }) {
  return (
    <ol className="m-0 flex list-none flex-col p-0">
      {entries.map((e) => (
        <li key={e.id} className="grid grid-cols-1 gap-x-3 border-t border-line py-2 text-[13px] sm:grid-cols-[150px_minmax(0,1fr)]" data-testid="audit-row">
          <span className="tnum text-muted-foreground">{formatDate(e.at)}</span>
          <span className="min-w-0 [overflow-wrap:anywhere]">
            <span className="font-medium">{WORDS[e.action] ?? e.action}</span>
            {detail(e) && <span className="tnum"> · {detail(e)}</span>}
            {e.target && <span className="tnum text-muted-foreground"> · {e.target}</span>}
            <span className="text-muted-foreground"> · by {e.actor}</span>
            {e.reason && <span className="block">{e.reason}</span>}
          </span>
        </li>
      ))}
    </ol>
  )
}

/** Rehearsal item 10: every admin action, newest first, and taking a share link down. */
export function AuditSection({ card }: { card: string }) {
  const [entries, setEntries] = useState<AdminAuditEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [unread, setUnread] = useState(false)
  const [link, setLink] = useState('')
  const [reason, setReason] = useState('')
  const [said_, setSaid] = useState<string | null>(null)
  const load = useCallback(() => { getAdminAudit().then((e) => { if (Array.isArray(e)) setEntries(e) }).catch(() => setUnread(true)) }, [])
  useEffect(load, [load])
  const takeDown = async () => {
    setSaid(null); setError(null)
    try { const r = await revokeAdminShare(link, reason); setSaid(`Link ${r.share_id} is ${r.state}.`); setLink(''); setReason(''); load() } catch (e) { setError(said(e, 'That link did not come down.')) }
  }
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="audit-h" data-testid="admin-audit">
      <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="audit-h" className="disp m-0 text-[22px] font-bold">Audit trail</h2><span className="tag text-faint">every admin action, newest first</span></div>
      <form className="flex flex-wrap items-end gap-2.5" aria-label="Take a share link down" onSubmit={(e) => { e.preventDefault(); void takeDown() }}>
        <label className="flex min-w-0 flex-[1_1_240px] flex-col gap-1"><span className="text-[13px] font-semibold">Share link</span>
          <input className={field} value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://…/#s/sh…" />
        </label>
        <label className="flex min-w-0 flex-[1_1_200px] flex-col gap-1"><span className="text-[13px] font-semibold">Why</span>
          <input className={field} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="the abuse report's number" />
        </label>
        <button type="submit" className="btn ink sm" disabled={!link.trim() || reason.trim().length < 3}>Take the link down</button>
      </form>
      {unread && <p className="m-0 text-sm text-muted-foreground">The audit trail could not be read.</p>}
      {said_ && <p className="m-0 text-sm" role="status">{said_}</p>}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {entries && (entries.length === 0 ? <p className="m-0 text-muted-foreground">No admin actions yet.</p> : <AuditList entries={entries} />)}
    </section>
  )
}
