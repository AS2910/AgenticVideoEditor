import { useCallback, useEffect, useState } from 'react'
import { getAdminWaitlist, sendWaitlistInvite } from '../api'
import type { WaitlistRow } from '../api'
import { formatDate } from '../lib/dates'
import { said } from './fmt'

/** Launch item 8: everyone who asked for access on the landing page, newest first,
 *  waiting or invited. Send invite emails the address and lets it sign up while
 *  Voltage is invite-only; the row then says who invited and when. Invite to beta (beta kit)
 *  does the same with the beta invite, and the address joins the beta cohort when it first signs in. */
export function AdminWaitlist({ card }: { card: string }) {
  const [rows, setRows] = useState<WaitlistRow[] | null>(null)
  const [inviteOnly, setInviteOnly] = useState<boolean | null>(null)
  const [busy, setBusy] = useState<{ id: number; beta: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [unread, setUnread] = useState(false)
  const load = useCallback(() => {
    getAdminWaitlist()
      .then((v) => { if (Array.isArray(v?.rows)) { setRows(v.rows); setInviteOnly(!!v.invite_only) } })
      .catch(() => setUnread(true))
  }, [])
  useEffect(() => { load() }, [load])

  const invite = async (row: WaitlistRow, beta = false) => {
    setBusy({ id: row.id, beta })
    setError(null)
    try {
      const { row: next } = await sendWaitlistInvite(row.id, beta)
      setRows((all) => (all ?? []).map((r) => (r.id === next.id ? next : r)))
    } catch (e) { setError(said(e, 'The invite did not go.')) } finally { setBusy(null) }
  }

  const waiting = rows?.filter((r) => r.status === 'waiting').length ?? 0
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="waitlist-h" data-testid="admin-waitlist">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id="waitlist-h" className="disp m-0 text-[22px] font-bold">Waitlist</h2>
        {rows && <span className="tag text-faint">{rows.length} asked · {waiting} waiting</span>}
        {inviteOnly === false && <span className="stamp quiet">Invite-only is off</span>}
      </div>
      {unread && <p className="m-0 text-sm text-muted-foreground">The waitlist could not be read.</p>}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {rows && rows.length === 0 && <p className="m-0 text-muted-foreground">Nobody has asked for access yet.</p>}
      {rows && rows.length > 0 && (
        <ul className="m-0 flex list-none flex-col p-0">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-line py-2.5" data-testid="waitlist-row">
              <span className="flex min-w-0 flex-[1_1_260px] flex-col">
                <span className="font-medium break-all">{r.email}{r.name && <span className="font-normal text-muted-foreground"> · {r.name}</span>}</span>
                {r.use_case && <span className="text-[13px] text-muted-foreground">{r.use_case}</span>}
                <span className="text-[12px] text-faint">
                  Asked {formatDate(r.created_at)}
                  {r.invited_at && <> · invited {formatDate(r.invited_at)} by {r.invited_by}</>}
                </span>
              </span>
              <span className={r.status === 'invited' ? 'stamp in' : 'stamp need'}>{r.status === 'invited' ? 'Invited' : 'Waiting'}</span>
              {r.beta && <span className="stamp inkd">Beta</span>}
              <button type="button" className={r.status === 'invited' ? 'btn sm' : 'btn volt sm'} disabled={busy !== null} onClick={() => void invite(r)}
                aria-label={`${r.status === 'invited' ? 'Send the invite again to' : 'Send invite to'} ${r.email}`}>
                {busy?.id === r.id && !busy.beta ? 'Sending…' : r.status === 'invited' ? 'Send again' : 'Send invite'}
              </button>
              <button type="button" className="btn sm" disabled={busy !== null} onClick={() => void invite(r, true)}
                aria-label={`${r.beta ? 'Send the beta invite again to' : 'Invite to beta:'} ${r.email}`}>
                {busy?.id === r.id && busy.beta ? 'Sending…' : r.beta ? 'Beta invite again' : 'Invite to beta'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
