import { useEffect, useState } from 'react'
import { track } from '../lib/analytics'
import type { AuthOptions } from '../api'
import { ApiError, forgotPassword, getAuthOptions, loginUrl, passwordLogin, resendVerify, sendSignInLink, signUp } from '../api'
import { cn } from '@/lib/utils'

const field = 'box-border h-11 min-w-0 rounded-lg border-[1.5px] border-foreground bg-card px-2.5 text-base text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-volt'

type Mode = 'signin' | 'signup' | 'forgot'

function said(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const detail = (e.body as { detail?: unknown } | null)?.detail
    if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') return (detail as { message: string }).message
    return e.message || fallback
  }
  return fallback
}

/** Launch item 5: sign in with an email and a password, make an account
 *  (accepting the Terms and Privacy notice), or get a reset link; Google and
 *  an emailed link when this Voltage offers them. `onSignedIn` reads who is
 *  signed in again. */
export function SignInForms({ onSignedIn }: { onSignedIn: () => void }) {
  const [options, setOptions] = useState<AuthOptions | null>(null)
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [unverified, setUnverified] = useState(false)
  useEffect(() => {
    let live = true
    getAuthOptions().then((o) => { if (live && o && typeof o.password === 'boolean') setOptions(o) }).catch(() => { /* Google only */ })
    return () => { live = false }
  }, [])

  const go = (m: Mode) => { setMode(m); setError(null); setNotice(null); setUnverified(false) }
  const run = async (what: () => Promise<void>, fallback: string) => {
    setBusy(true)
    setError(null)
    try { await what() } catch (e) {
      setUnverified(e instanceof ApiError && e.status === 403 && (e.body as { detail?: { code?: string } } | null)?.detail?.code === 'unverified')
      setError(said(e, fallback))
    } finally { setBusy(false) }
  }
  const submit = () => {
    if (mode === 'signin') {
      void run(async () => { await passwordLogin(email.trim(), password); onSignedIn() }, 'Could not sign you in.')
    } else if (mode === 'signup') {
      void run(async () => { const r = await signUp(email.trim(), password, code.trim() || undefined); setNotice(r.message) }, 'Could not make the account.')
    } else {
      void run(async () => { const r = await forgotPassword(email.trim()); setNotice(r.message) }, 'Could not send the link.')
    }
  }
  const ready = email.trim() && (mode === 'forgot' || password.length > 0) && (mode !== 'signup' || agreed)

  return (
    <div className="flex w-full max-w-[420px] flex-col gap-3.5" data-testid="sign-in-forms">
      {(options?.google ?? true) && (
        <a href={loginUrl} className="btn volt lg shine self-start">
          <svg width="20" height="20" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="7.5" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M12.6 9H9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
          Continue with Google
        </a>
      )}
      {options?.password && (
        <form className="flex flex-col gap-2.5" aria-label={mode === 'signup' ? 'Make an account' : mode === 'forgot' ? 'Reset your password' : 'Sign in with email and password'}
          onSubmit={(e) => { e.preventDefault(); if (ready && !busy) submit() }}>
          <span className="disp text-lg font-bold">{mode === 'signup' ? 'Make an account' : mode === 'forgot' ? 'Forgot your password?' : (options.google ? 'Or sign in with your email' : 'Sign in')}</span>
          <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">Email</span>
            <input className={field} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@agency.com" />
          </label>
          {mode !== 'forgot' && (
            <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">Password</span>
              <input className={field} type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} value={password} onChange={(e) => setPassword(e.target.value)} />
              {mode === 'signup' && <span className="text-[13px] text-muted-foreground">At least 10 characters.</span>}
            </label>
          )}
          {mode === 'signup' && options.invite_only && (
            <label className="flex flex-col gap-1"><span className="text-[13px] font-semibold">Invite code</span>
              <input className={field} autoComplete="off" value={code} onChange={(e) => setCode(e.target.value)} />
              <span className="text-[13px] text-muted-foreground">Voltage is invite-only for now. Invited by email? Use that address and leave this empty.</span>
            </label>
          )}
          {mode === 'signup' && (
            <label className="flex min-h-11 items-start gap-2.5 text-sm">
              <input type="checkbox" className="mt-1 size-4 accent-foreground" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              <span>I accept the <a href="#terms" target="_blank" rel="noreferrer">Terms</a> and the <a href="#privacy" target="_blank" rel="noreferrer">Privacy notice</a>.</span>
            </label>
          )}
          {error && <span className="text-[13px] text-destructive" role="alert">{error}</span>}
          {unverified && (
            <button type="button" className="act self-start" disabled={busy}
              onClick={() => void run(async () => { const r = await resendVerify(email.trim()); setNotice(r.message); setError(null); setUnverified(false) }, 'Could not send it.')}>
              Send the confirmation link again
            </button>
          )}
          {notice && <p className="m-0 text-sm" role="status" data-testid="auth-notice">{notice}</p>}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {mode === 'signin' && <button type="button" className="act" onClick={() => go('forgot')}>Forgot your password?</button>}
            {mode === 'signin' && <button type="button" className="act" onClick={() => go('signup')}>New here? Make an account</button>}
            {mode !== 'signin' && <button type="button" className="act" onClick={() => go('signin')}>Back to sign in</button>}
            <span className="flex-1" />
            <button type="submit" className={cn('btn', !options.google && 'volt')} disabled={!ready || busy} aria-busy={busy || undefined}>
              {busy ? 'One moment…' : mode === 'signup' ? 'Make my account' : mode === 'forgot' ? 'Email me a reset link' : 'Sign in'}
            </button>
          </div>
        </form>
      )}
      {options?.email_link && mode === 'signin' && <EmailLink />}
    </div>
  )
}

/** G2: sign in with an emailed one-use link. */
function EmailLink() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const send = async () => {
    setSending(true)
    track('signin.email_requested')
    setError(null)
    try {
      const out = await sendSignInLink(email.trim())
      setSent(`Check ${out.email}. The link works once, for 15 minutes.`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The link could not be sent.')
    } finally {
      setSending(false)
    }
  }
  if (sent) return <p className="m-0 text-sm" role="status" data-testid="email-sent">{sent}</p>
  return (
    <form className="flex w-full flex-wrap items-end gap-2.5" aria-label="Sign in with email" onSubmit={(e) => { e.preventDefault(); void send() }}>
      <label className="flex min-w-0 flex-[1_1_220px] flex-col gap-1"><span className="text-[13px] font-semibold">Or get a one-use sign-in link</span>
        <input type="email" autoComplete="email" className={field} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@agency.com" aria-invalid={error ? true : undefined} />
      </label>
      <button type="submit" className="btn" disabled={!email.trim() || sending} aria-busy={sending || undefined}>{sending ? 'Sending…' : 'Email me a link'}</button>
      {error && <span className="basis-full text-[13px] text-destructive" role="alert">{error}</span>}
    </form>
  )
}
