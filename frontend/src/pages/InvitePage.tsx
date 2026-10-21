import { useEffect, useState } from 'react'
import type { InviteView } from '../types'
import { ApiError, acceptInvite, openInvite } from '../api'
import { hrefFor } from '../lib/route'
import { Wordmark } from './Shell'

/** G2: an invite link (`#invite/<token>`). Says which workspace and role,
 *  then Accept invite last; a dead link says why. */
export function InvitePage({ token }: { token: string }) {
  const [invite, setInvite] = useState<InviteView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [joined, setJoined] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let live = true
    openInvite(token).then((i) => { if (live) setInvite(i) }).catch((e) => { if (live) setError(e instanceof ApiError ? e.message : 'This invite could not be read.') })
    return () => { live = false }
  }, [token])
  const accept = async () => {
    setBusy(true)
    setError(null)
    try {
      const out = await acceptInvite(token)
      setJoined(`You are in ${out.workspace_name} as ${out.role_word === 'Editor' ? 'an' : 'a'} ${out.role_word}.`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The invite could not be accepted.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <header className="flex min-h-[62px] items-center border-b-[1.5px] border-foreground bg-card px-4 sm:px-6"><Wordmark /></header>
      <main id="main" className="mx-auto flex w-full max-w-[560px] flex-col gap-5 px-4 pt-14 pb-20">
        <span className="tag text-faint">Invite</span>
        {!invite && !error && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading the invite…</p>}
        {invite && !joined && (
          <section className="flex flex-col gap-4 rounded-xl border-[1.5px] border-foreground bg-card p-[22px] shadow-volt" data-testid="invite">
            <h1 className="disp m-0 text-[36px] leading-tight font-bold">Join {invite.workspace_name}</h1>
            <p className="m-0 text-muted-foreground">
              {invite.invited_by ? `${invite.invited_by} invited ` : 'You are invited '}{invite.email} as {invite.role_word === 'Editor' ? 'an' : 'a'} <span className="stamp in">{invite.role_word}</span>.{' '}
              {invite.role === 'reviewer' ? 'You can watch and comment on videos.' : 'You can edit videos and projects.'} The link works until {invite.expires_at.slice(0, 10)}.
            </p>
            {!invite.sign_in && <p className="m-0 text-sm">Sign-in is off on this Voltage, so the invite cannot be accepted yet.</p>}
            <button type="button" className="btn volt self-start" onClick={() => void accept()} disabled={busy || !invite.sign_in} aria-busy={busy || undefined}>{busy ? 'Joining…' : 'Accept invite'}</button>
          </section>
        )}
        {joined && (
          <section className="flex flex-col gap-4 rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" role="status">
            <p className="disp m-0 text-xl font-bold">{joined}</p>
            <a className="btn volt self-start" href={hrefFor({ page: 'projects' })}>Open Home</a>
          </section>
        )}
        {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</div>}
      </main>
    </div>
  )
}
