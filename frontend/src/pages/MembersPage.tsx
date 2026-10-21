import { useCallback, useEffect, useState } from 'react'
import type { MembersPage as Page, MemberRole, WorkspaceMember, WorkspaceView } from '../types'
import type { Me } from '../api'
import { ApiError, changeMember, getWorkspace, listMembers, removeMember, revokeInvite, sendInvite, switchWorkspace } from '../api'
import { cn } from '@/lib/utils'
import { Shell, SideNav } from './Shell'
import { said, usd } from './fmt'
import { Tip } from '../guides/Tip'

const ROLE_HELP: Record<MemberRole, string> = {
  owner: 'Everything, including members and billing.',
  editor: 'Everything except members and billing.',
  reviewer: 'Watches and comments. Changes nothing.',
}
const card = 'rounded-xl border-[1.5px] border-foreground bg-card p-[22px]'
const field = 'box-border h-10 min-w-0 rounded-lg border-[1.5px] border-foreground bg-card px-2.5 text-base text-foreground outline-none placeholder:text-faint focus-visible:ring-[3px] focus-visible:ring-volt'

function money(v: string): number | null | 'bad' {
  const t = v.trim().replace(/^\$/, '')
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) / 100 : 'bad'
}

function spendLine(m: WorkspaceMember): string {
  return m.spend_limit_usd != null ? `${usd(m.spent_usd)} of ${usd(m.spend_limit_usd)} this month` : `${usd(m.spent_usd)} this month · no limit`
}

/** G2: Settings > Members. The owner sees who is in the workspace, changes
 *  roles and monthly spend limits, removes people, and invites by email; an
 *  Editor or Reviewer sees their own role. Someone in more than one
 *  workspace picks which one to work in. */
export function MembersPage({ me }: { me: Me | null }) {
  const [view, setView] = useState<WorkspaceView | null>(null)
  const [page, setPage] = useState<Page | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<MemberRole>('editor')
  const [limit, setLimit] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const v = await getWorkspace()
      setView(v)
      setPage(v.you.role === 'owner' ? await listMembers() : null)
    } catch (e) {
      setError(said(e, 'Members could not be read.'))
    }
  }, [])
  useEffect(() => { void load() }, [load])

  const act = async (key: string, work: () => Promise<Page>, done: string) => {
    setBusy(key)
    setStatus(null)
    try {
      setPage(await work())
      setStatus(done)
    } catch (e) {
      setStatus(said(e, 'That did not work. Try again.'))
    } finally {
      setBusy(null)
    }
  }
  const invite = async () => {
    const cap = money(limit)
    if (cap === 'bad') { setFormError('A spend limit is an amount like 20, or empty for none.'); return }
    setFormError(null)
    setBusy('invite')
    try {
      const out = await sendInvite(email.trim(), role, cap)
      setPage(out)
      setEmail('')
      setLimit('')
      setStatus(`Invite sent to ${out.invite?.email ?? 'them'}.`)
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : 'The invite could not be sent.')
    } finally {
      setBusy(null)
    }
  }
  const copy = async (id: string, link: string) => {
    try { await navigator.clipboard.writeText(link); setCopied(id) } catch { setCopied(null) }
  }
  const pick = async (id: string) => {
    const own = view?.workspaces.find((w) => w.workspace_id === id)?.own
    try {
      await switchWorkspace(own ? null : id)
      window.location.reload()
    } catch (e) {
      setStatus(said(e, 'Could not switch workspace.'))
    }
  }

  return (
    <Shell active="settings" me={me} mainClassName="mx-auto flex w-full max-w-[1100px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active="members" />
      <div className="flex min-w-0 flex-1 flex-col gap-[22px]">
        <h1 className="disp rise m-0 mb-1 text-[56px] leading-none font-bold">Members</h1>
        <p className="m-0 max-w-[640px] text-muted-foreground">People you invite work in this workspace. Editors change videos and projects; Reviewers watch and comment.</p>

        {error && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {error}<button type="button" className="btn sm" onClick={() => void load()}>Try again</button>
          </div>
        )}
        {!error && !view && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading members…</p>}

        {view && view.workspaces.length > 1 && (
          <label className={cn(card, 'flex flex-wrap items-center gap-3')}>
            <span className="tag text-faint">Working in</span>
            <select className={cn(field, 'h-9 text-sm')} value={view.workspace.workspace_id} onChange={(e) => void pick(e.target.value)} data-testid="workspace-pick">
              {view.workspaces.map((w) => <option key={w.workspace_id} value={w.workspace_id}>{w.own ? 'My workspace' : w.name} · {w.role === 'owner' ? 'Owner' : w.role === 'editor' ? 'Editor' : 'Reviewer'}</option>)}
            </select>
          </label>
        )}

        {view && view.you.role !== 'owner' && (
          <section className={card} data-testid="members-not-owner">
            <span className="stamp in">{view.you.role === 'editor' ? 'Editor' : 'Reviewer'}</span>
            <p className="m-0 mt-3">{ROLE_HELP[view.you.role]} Only the workspace owner manages members.</p>
          </section>
        )}

        {page && (
          <>
            {!page.sign_in && (
              <p className="m-0 rounded-lg border-[1.5px] border-foreground bg-sunk px-3.5 py-2.5 text-sm" data-testid="sign-in-off">
                Sign-in is off on this Voltage, so it has one account: you, the Owner. Invites are kept and work once sign-in is on.
              </p>
            )}
            <section className={cn(card, 'flex flex-col')} aria-labelledby="people-h" data-testid="members">
              <div className="flex items-center gap-3 pb-2"><h2 id="people-h" className="disp m-0 text-[22px] font-bold">People</h2><span className="tag text-faint">{page.members.length + 1}</span></div>
              <div className="flex flex-wrap items-center gap-3 border-t border-line py-3.5">
                <span className="min-w-0 flex-[1_1_220px] truncate font-semibold">{page.owner.email ?? 'You'}</span>
                <span className="stamp">Owner</span>
                <span className="tnum text-[13px] text-muted-foreground">{usd(page.owner.spent_usd)} this month</span>
              </div>
              {page.members.length === 0 && <p className="m-0 border-t border-line py-3.5 text-muted-foreground">Only you so far. Invite someone below.</p>}
              {page.members.map((m) => (
                <MemberRow key={m.member} m={m} busy={busy === m.member} roles={page.roles}
                  onRole={(r) => void act(m.member, () => changeMember(m.member, { role: r }), `${m.email ?? m.member} is now ${r === 'editor' ? 'an Editor' : 'a Reviewer'}.`)}
                  onLimit={(v) => void act(m.member, () => changeMember(m.member, { spend_limit_usd: v }), v == null ? 'Limit removed.' : `Limit set to ${usd(v)} a month.`)}
                  onRemove={() => void act(m.member, () => removeMember(m.member), `${m.email ?? m.member} is out of this workspace. What they made stays.`)} />
              ))}
            </section>

            <section className={cn(card, 'flex flex-col gap-3.5')} aria-labelledby="invite-h">
              <h2 id="invite-h" className="disp m-0 text-[22px] font-bold">Invite someone</h2>
              <Tip id="first-members" target="invite-form" />
              <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); void invite() }} aria-label="Invite someone" data-testid="invite-form" data-tour="invite-form">
                <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">Email</span>
                  <input className={field} type="email" autoComplete="off" value={email} onChange={(e) => { setEmail(e.target.value); setFormError(null) }} placeholder="name@agency.com" aria-invalid={formError ? true : undefined} />
                </label>
                <div className="flex flex-col gap-1">
                  <span className="text-[13px] font-semibold" id="role-l">Role</span>
                  <div className="segs self-start" role="radiogroup" aria-labelledby="role-l">
                    {page.roles.map((r) => <button key={r.role} type="button" role="radio" className="seg" aria-checked={role === r.role} onClick={() => setRole(r.role)}>{r.word}</button>)}
                  </div>
                  <span className="text-[13px] text-muted-foreground">{ROLE_HELP[role]}</span>
                </div>
                <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">Monthly spend limit (optional)</span>
                  <input className={cn(field, 'w-40')} inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="$ none" />
                  <span className="text-[13px] text-muted-foreground">What they start counts against it, inside your own ceilings.</span>
                </label>
                {formError && <span className="text-[13px] text-destructive" role="alert">{formError}</span>}
                <button type="submit" className="btn volt self-start" disabled={!email.trim() || busy === 'invite'} aria-busy={busy === 'invite' || undefined}>{busy === 'invite' ? 'Sending…' : 'Send invite'}</button>
              </form>
              {page.invites.length > 0 && (
                <div className="flex flex-col" data-testid="invites">
                  <span className="tag pt-2 pb-1 text-faint">Waiting · {page.invites.length}</span>
                  {page.invites.map((i) => (
                    <div key={i.id} className="flex flex-wrap items-center gap-3 border-t border-line py-3">
                      <span className="min-w-0 flex-[1_1_200px] truncate">{i.email}</span>
                      <span className="tag">{i.role === 'editor' ? 'Editor' : 'Reviewer'}</span>
                      <span className={cn('stamp', i.state === 'expired' ? 'need' : 'quiet')}>{i.state === 'expired' ? 'Expired' : `Until ${i.expires_at.slice(0, 10)}`}</span>
                      <button type="button" className="act" onClick={() => void act(i.id, () => revokeInvite(i.id), `The invite to ${i.email} is off.`)} disabled={busy === i.id}>Turn off</button>
                      <button type="button" className="btn sm" onClick={() => void copy(i.id, i.link)}>{copied === i.id ? 'Copied' : 'Copy link'}</button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
        <p className="m-0 min-h-5 text-sm text-muted-foreground" role="status" aria-live="polite">{status}</p>
      </div>
    </Shell>
  )
}

function MemberRow({ m, roles, busy, onRole, onLimit, onRemove }: {
  m: WorkspaceMember; roles: { role: MemberRole; word: string }[]; busy: boolean
  onRole: (r: MemberRole) => void; onLimit: (v: number | null) => void; onRemove: () => void
}) {
  const [limit, setLimit] = useState(m.spend_limit_usd != null ? String(m.spend_limit_usd) : '')
  const [asking, setAsking] = useState(false)
  const [bad, setBad] = useState(false)
  const name = m.email ?? m.member
  const commit = () => {
    const v = money(limit)
    if (v === 'bad') { setBad(true); return }
    setBad(false)
    if (v !== (m.spend_limit_usd ?? null)) onLimit(v)
  }
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-line py-3.5" data-testid="member-row" aria-busy={busy || undefined}>
      <span className="flex min-w-0 flex-[1_1_220px] flex-col">
        <span className="truncate font-semibold">{name}</span>
        <span className="tnum text-[13px] text-muted-foreground">{spendLine(m)}</span>
      </span>
      <select className={cn(field, 'h-9 text-sm')} aria-label={`Role for ${name}`} value={m.role} disabled={busy} onChange={(e) => onRole(e.target.value as MemberRole)}>
        {roles.map((r) => <option key={r.role} value={r.role}>{r.word}</option>)}
      </select>
      <input className={cn(field, 'h-9 w-28 text-sm')} aria-label={`Monthly limit for ${name}`} inputMode="decimal" placeholder="No limit" value={limit} disabled={busy}
        aria-invalid={bad || undefined} onChange={(e) => setLimit(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit() } }} />
      {asking
        ? <span className="flex items-center gap-2"><span className="text-[13px]">Remove {name}?</span><button type="button" className="act" onClick={() => setAsking(false)}>Keep</button><button type="button" className="btn sm" onClick={() => { setAsking(false); onRemove() }}>Remove</button></span>
        : <button type="button" className="act" onClick={() => setAsking(true)} disabled={busy}>Remove</button>}
    </div>
  )
}
