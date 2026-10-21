import { useState } from 'react'
import { ApiError, resetPassword } from '../api'
import { Wordmark } from './Shell'

const field = 'box-border h-11 min-w-0 rounded-lg border-[1.5px] border-foreground bg-card px-2.5 text-base text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-volt'

/** Launch item 5: `#reset/<token>` from the emailed link. A new password,
 *  typed twice; every other session of the account is signed out. */
export function ResetPage({ token, onDone }: { token: string; onDone: () => void }) {
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mismatch = again.length > 0 && again !== password
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await resetPassword(token, password)
      window.location.hash = 'home'
      onDone()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The password could not be changed.')
    } finally { setBusy(false) }
  }
  return (
    <div className="flex min-h-dvh flex-col gap-10 bg-background px-[clamp(24px,6vw,88px)] py-12 text-foreground">
      <Wordmark href={null} size={32} className="text-xl" />
      <form className="flex w-full max-w-[420px] flex-col gap-3" aria-label="Choose a new password" onSubmit={(e) => { e.preventDefault(); if (!mismatch && password) void save() }}>
        <h1 className="disp m-0 text-[40px] leading-none font-bold">Choose a new password</h1>
        <p className="m-0 text-muted-foreground">At least 10 characters. You will be signed out everywhere else.</p>
        <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">New password</span>
          <input className={field} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">The same again</span>
          <input className={field} type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} aria-invalid={mismatch || undefined} />
        </label>
        {mismatch && <span className="text-[13px] text-destructive">The two do not match yet.</span>}
        {error && <span className="text-[13px] text-destructive" role="alert">{error}</span>}
        <button type="submit" className="btn volt self-start" disabled={!password || mismatch || busy} aria-busy={busy || undefined}>{busy ? 'Saving…' : 'Save and sign in'}</button>
      </form>
    </div>
  )
}
