import { useEffect, useState } from 'react'
import { ApiError, emailSignInAvailable, loginUrl, sendSignInLink } from '../api'
import { Wordmark } from './Shell'

/** The door, when sign-in is on: the promise on the left, Voltage at work on the right. */
export function LoginPage({ error }: { error?: string | null }) {
  // G2: sign in with an emailed link too, when this Voltage offers it.
  const [byEmail, setByEmail] = useState(false)
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const [mailError, setMailError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  useEffect(() => {
    let live = true
    emailSignInAvailable().then((r) => { if (live) setByEmail(r.available) }).catch(() => { /* Google only */ })
    return () => { live = false }
  }, [])
  const send = async () => {
    setSending(true)
    setMailError(null)
    try {
      const out = await sendSignInLink(email.trim())
      setSent(`Check ${out.email}. The link works once, for 15 minutes.`)
    } catch (e) {
      setMailError(e instanceof ApiError ? e.message : 'The link could not be sent.')
    } finally {
      setSending(false)
    }
  }
  return (
    <div className="flex min-h-dvh flex-wrap bg-background text-foreground">
      <section className="flex min-w-0 flex-[1_1_520px] flex-col justify-between gap-12 px-[clamp(24px,6vw,88px)] py-12">
        <Wordmark href={null} size={32} className="text-xl" />
        <div className="flex max-w-[560px] flex-col gap-7">
          <h1 className="disp rise sweep m-0 text-[clamp(44px,6vw,76px)] leading-[.98] font-bold">
            Change what your video <ins className="rounded-md px-2.5">says.</ins>
          </h1>
          <p className="m-0 text-lg leading-[1.55] text-muted-foreground">No reshoot. Tell Voltage the goal. It rewrites the line, voices it in the speaker's own voice, and keeps the picture moving.</p>
          <div className="flex flex-col items-start gap-3.5">
            <a href={loginUrl} className="btn volt lg shine">
              <svg width="20" height="20" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="7.5" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M12.6 9H9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
              Continue with Google
            </a>
            {byEmail && (sent
              ? <p className="m-0 text-sm" role="status" data-testid="email-sent">{sent}</p>
              : (
                <form className="flex w-full max-w-[420px] flex-wrap items-end gap-2.5" aria-label="Sign in with email" onSubmit={(e) => { e.preventDefault(); void send() }}>
                  <label className="flex min-w-0 flex-[1_1_220px] flex-col gap-1"><span className="text-[13px] font-semibold">Or sign in with your email</span>
                    <input type="email" autoComplete="email" className="box-border h-10 min-w-0 rounded-lg border-[1.5px] border-foreground bg-card px-2.5 text-base text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-volt" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@agency.com" aria-invalid={mailError ? true : undefined} />
                  </label>
                  <button type="submit" className="btn" disabled={!email.trim() || sending} aria-busy={sending || undefined}>{sending ? 'Sending…' : 'Email me a link'}</button>
                  {mailError && <span className="basis-full text-[13px] text-destructive" role="alert">{mailError}</span>}
                </form>
              ))}
            <span className="tag text-faint">Private by default · your footage and voices stay yours</span>
            {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</div>}
          </div>
        </div>
        <span className="tag text-faint">Videos up to 3 min · speech or silent</span>
      </section>

      <section aria-hidden="true" className="pane flex min-w-0 flex-[1_1_520px] items-center justify-center px-6 py-12">
        <div className="flex w-full max-w-[520px] flex-col gap-7">
          <div className="flex items-center gap-[18px]">
            <span className="wave h-14 gap-[3px] [&>i]:h-14 [&>i]:w-1.5 [&>i]:rounded-[3px]"><i /><i /><i /><i /><i /><i /><i /></span>
            <div className="flex flex-col">
              <span className="disp text-[28px] font-bold">Voltage</span>
              <span className="tag text-volt"><span className="blinkdot">●</span> voicing line 1</span>
            </div>
          </div>
          <div className="sweep flex flex-col gap-3.5 rounded-[14px] border border-pline bg-psunk p-[22px]">
            <span className="tag text-pmuted">0:00.4 · Speaker 1</span>
            <span className="disp text-[30px] leading-tight font-semibold">Get <del className="text-pmuted">20%</del> <ins className="px-1.5">30%</ins> off today only.</span>
            <span className="text-sm text-pmuted">Her own voice · sounds like her · fits the slot</span>
          </div>
          <div className="flex flex-col gap-1.5 font-mono text-[13px] text-pmuted">
            <span className="rise d1"><span className="opacity-50">├</span> read 1 line · found the pause after it</span>
            <span className="rise d2"><span className="opacity-50">├</span> cloned Speaker 1 from her own speech</span>
            <span className="rise d3 text-ptext"><span className="opacity-50">└</span> voiced “30% off” <span className="blinkdot inline-block h-[15px] w-2 bg-volt align-middle" /></span>
          </div>
        </div>
      </section>
    </div>
  )
}
