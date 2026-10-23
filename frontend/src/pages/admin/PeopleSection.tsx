import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import type { AdminUser, AdminUserHit } from '../../api'
import { findAdminUsers, getAdminUser, grantAdminCredits, refundAdmin, suspendAdminUser, unsuspendAdminUser } from '../../api'
import { usd } from '../../lib/money'
import { formatDate } from '../../lib/dates'
import { said } from '../fmt'
import { AuditList } from './AuditSection'
import { field } from './ui'

const credits = (n: number) => `${n.toFixed(2)} ${Math.abs(n) === 1 ? 'credit' : 'credits'}`
const when = (v: unknown) => formatDate(v)

/** Rehearsal item 10: find a person by part of an address or owner id, read their account, act on it. */
export function PeopleSection({ card, onFlags }: { card: string; onFlags: (owner: string) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<AdminUserHit[] | null>(null)
  const [user, setUser] = useState<AdminUser | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const find = async (e: FormEvent) => {
    e.preventDefault()
    if (q.trim().length < 2) return
    setBusy(true); setError(null)
    try { setHits(await findAdminUsers(q.trim())) } catch (err) { setError(said(err, 'The search did not work.')) } finally { setBusy(false) }
  }
  const open = async (owner: string) => {
    setBusy(true); setError(null)
    try { setUser(await getAdminUser(owner)) } catch (err) { setError(said(err, 'That person could not be read.')) } finally { setBusy(false) }
  }
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="people-h" data-testid="admin-people">
      <div className="flex flex-wrap items-baseline gap-2.5"><h2 id="people-h" className="disp m-0 text-[22px] font-bold">People</h2><span className="tag text-faint">find someone, then act</span></div>
      <form className="flex flex-wrap items-end gap-2.5" onSubmit={(e) => void find(e)} role="search">
        <label className="flex min-w-0 flex-[1_1_260px] flex-col gap-1"><span className="text-[13px] font-semibold">Email or owner id</span>
          <input className={field} value={q} onChange={(e) => setQ(e.target.value)} placeholder="part of an address, or acct:… google:…" autoComplete="off" />
        </label>
        <button type="submit" className="btn sm" disabled={q.trim().length < 2 || busy}>{busy && !user ? 'Finding…' : 'Find'}</button>
      </form>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {hits && (
        hits.length === 0 ? <p className="m-0 text-muted-foreground" role="status">Nobody matches.</p> : (
          <ul className="m-0 flex list-none flex-col p-0" aria-label="People found">
            {hits.map((h) => (
              <li key={h.owner} className="flex flex-wrap items-center gap-3 border-t border-line py-2" data-testid="person-hit">
                <span className="min-w-0 flex-1"><span className="font-medium">{h.emails[0] ?? h.owner}</span> <span className="tnum text-[13px] text-muted-foreground">{h.owner}</span></span>
                <span className="tag text-faint">{h.kind}</span>
                {h.suspended && <span className="stamp need">Suspended</span>}
                <button type="button" className="btn sm" disabled={busy} onClick={() => void open(h.owner)} aria-label={`Open ${h.emails[0] ?? h.owner}`}>Open</button>
              </li>
            ))}
          </ul>
        )
      )}
      {user && <UserView user={user} onChange={setUser} onFlags={onFlags} />}
    </section>
  )
}

function Part({ title, children, testid }: { title: string; children: ReactNode; testid?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-[10px] border border-line2 p-3.5" data-testid={testid}>
      <h4 className="tag m-0 text-faint">{title}</h4>
      {children}
    </div>
  )
}

/** A reason is required for every admin action; it goes in the audit trail. The verb is last. */
function ReasonForm({ verb, busyVerb, onSubmit, children, danger }: {
  verb: string; busyVerb: string; onSubmit: (reason: string) => Promise<void>; children?: ReactNode; danger?: boolean
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
      <button type="submit" className={danger ? 'btn ink sm' : 'btn sm'} disabled={busy || reason.trim().length < 3}>{busy ? busyVerb : verb}</button>
      {error && <p className="m-0 basis-full text-sm text-destructive" role="alert">{error}</p>}
    </form>
  )
}

function UserView({ user, onChange, onFlags }: { user: AdminUser; onChange: (u: AdminUser) => void; onFlags: (owner: string) => void }) {
  const [amount, setAmount] = useState('5')
  const [back, setBack] = useState('1')
  const vendors = Object.entries(user.spend.by_vendor)
  return (
    <article className="flex flex-col gap-3 border-t-[1.5px] border-foreground pt-4" aria-labelledby="user-h" data-testid="admin-user">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h3 id="user-h" className="disp m-0 text-xl font-bold">{user.emails[0] ?? user.owner}</h3>
        <span className="tnum text-[13px] text-muted-foreground">{user.owner}</span>
        <span className="tag text-faint">{user.kind}</span>
        {user.is_admin && <span className="stamp quiet">Admin</span>}
        {user.suspended && <span className="stamp need" data-testid="user-suspended">Suspended</span>}
      </div>
      {user.suspended && <p className="m-0 text-sm">Suspended {when(user.suspended.suspended_at)} by {user.suspended.suspended_by}: {user.suspended.reason}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Part title="Workspace" testid="user-workspace">
          <span className="text-sm">{user.workspace.name ?? user.workspace.workspace_id} · owner</span>
          {user.workspace.members.length === 0 ? <span className="text-[13px] text-muted-foreground">No members.</span> : user.workspace.members.map((m) => (
            <span key={m.member} className="text-[13px]">{m.email ?? m.member} <span className="tag text-faint">{m.role}</span></span>
          ))}
          {user.member_of.map((w) => <span key={w.workspace_id} className="text-[13px] text-muted-foreground">Also {w.role} in {w.name}</span>)}
        </Part>
        <Part title="Spend" testid="user-spend">
          <span className="tnum text-sm">Today {usd(user.spend.today_usd)} · this month {usd(user.spend.month_usd)} · all time {usd(user.spend.all_time_usd)}</span>
          <span className="tnum text-[13px] text-muted-foreground">{vendors.length ? vendors.map(([v, n]) => `${v} ${usd(n)}`).join(' · ') : 'Nothing spent yet.'}</span>
        </Part>
        <Part title="Credits" testid="user-credits">
          {user.credits ? (
            <>
              <span className="tnum text-sm">{credits(user.credits.left)} left of {credits(user.credits.granted)} granted</span>
              {user.credits.grants.slice(0, 6).map((g, i) => (
                <span key={i} className="tnum text-[13px] text-muted-foreground">{g.kind} {g.credits > 0 ? '+' : ''}{g.credits} · {g.reference}</span>
              ))}
            </>
          ) : <span className="text-[13px] text-muted-foreground">No billing account yet. A grant makes one, with the free trial.</span>}
        </Part>
        <Part title="Recent jobs" testid="user-jobs">
          {user.jobs.length === 0 ? <span className="text-[13px] text-muted-foreground">No jobs yet.</span> : user.jobs.slice(0, 8).map((j) => (
            <span key={j.job_id} className="text-[13px]"><span className={j.status === 'failed' ? 'stamp need' : 'stamp quiet'}>{j.status}</span> <span className="tnum">{j.kind} · {j.video_id}</span>{j.error_text && <span className="text-muted-foreground"> · {j.error_text}</span>}</span>
          ))}
        </Part>
        <Part title="Recent error reports" testid="user-errors">
          {user.errors.length === 0 ? <span className="text-[13px] text-muted-foreground">No errors reported.</span> : user.errors.slice(0, 6).map((e) => (
            <span key={e.id} className="truncate text-[13px]" title={e.message}><span className="tag text-faint">{e.source}</span> {e.message}</span>
          ))}
        </Part>
        <Part title="Payments" testid="user-invoices">
          {user.invoices.length === 0 ? <span className="text-[13px] text-muted-foreground">No payments.</span> : user.invoices.map((i) => (
            <div key={i.id} className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="tnum min-w-0 flex-1">{i.number} · {i.currency} {i.total.toFixed(2)}{i.test_mode ? ' · test mode' : ''}</span>
              {i.refunded ? <span className="stamp quiet">Refunded</span> : (
                <ReasonForm verb="Refund" busyVerb="Refunding…" onSubmit={async (r) => onChange(await refundAdmin(user.owner, r, { invoice_id: i.id }))} />
              )}
            </div>
          ))}
        </Part>
      </div>
      <div className="flex flex-col gap-3" data-testid="user-actions">
        <h4 className="tag m-0 text-faint">Act</h4>
        <ReasonForm verb="Grant credits" busyVerb="Granting…" onSubmit={async (r) => onChange(await grantAdminCredits(user.owner, Number(amount), r))}>
          <label className="flex w-24 flex-col gap-1"><span className="text-[13px] font-semibold">Credits</span>
            <input className={field} type="number" min="0.01" max="10000" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
        </ReasonForm>
        <ReasonForm verb="Take credits back" busyVerb="Taking back…" onSubmit={async (r) => onChange(await refundAdmin(user.owner, r, { credits: Number(back) }))}>
          <label className="flex w-24 flex-col gap-1"><span className="text-[13px] font-semibold">Credits</span>
            <input className={field} type="number" min="0.01" max="10000" step="0.01" value={back} onChange={(e) => setBack(e.target.value)} />
          </label>
        </ReasonForm>
        {user.suspended
          ? <ReasonForm verb="Unsuspend" busyVerb="Unsuspending…" onSubmit={async (r) => onChange(await unsuspendAdminUser(user.owner, r))} />
          : !user.is_admin && (
            <ReasonForm danger verb="Suspend" busyVerb="Suspending…" onSubmit={async (r) => onChange(await suspendAdminUser(user.owner, r))}>
              <p className="m-0 basis-full text-[13px] text-muted-foreground">They and their members are signed out of this workspace, running work stops, and their share links stop working until you unsuspend.</p>
            </ReasonForm>
          )}
        <div><button type="button" className="act" onClick={() => onFlags(user.owner)}>Features for this person ↓</button></div>
      </div>
      {user.audit.length > 0 && <Part title="What admins did here"><AuditList entries={user.audit} /></Part>}
    </article>
  )
}
