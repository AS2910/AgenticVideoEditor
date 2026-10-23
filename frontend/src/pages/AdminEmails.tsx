import { useCallback, useEffect, useState } from 'react'
import type { EmailKind, EmailPreview, Me } from '../api'
import { getEmailKinds, getEmailPreview } from '../api'
import { hrefFor } from '../lib/route'
import { Shell, SideNav } from './Shell'
import { said } from './fmt'

/** Launch item 9: every email Voltage sends, as it looks with sample data, for admins
 *  (`#admin/emails`). The HTML is drawn in a sandboxed frame (no scripts, no same origin),
 *  the plain-text version beside it. Nothing here sends an email. */
export function AdminEmails({ me }: { me: Me | null }) {
  const [kinds, setKinds] = useState<EmailKind[] | null>(null)
  const [kind, setKind] = useState<string | null>(null)
  const [mail, setMail] = useState<EmailPreview | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadKinds = useCallback(() => {
    setError(null)
    getEmailKinds()
      .then((r) => { setKinds(r.kinds); setKind((k) => k ?? r.kinds[0]?.kind ?? null) })
      .catch((e) => setError(said(e, 'The emails could not be read.')))
  }, [])
  useEffect(() => { loadKinds() }, [loadKinds])
  useEffect(() => {
    if (!kind) return
    let live = true
    setMail(null)
    getEmailPreview(kind)
      .then((m) => { if (live) setMail(m) })
      .catch((e) => { if (live) setError(said(e, 'That email could not be read.')) })
    return () => { live = false }
  }, [kind])

  const card = 'rounded-xl border-[1.5px] border-foreground bg-card p-[22px]'
  return (
    <Shell active="settings" me={me} mainClassName="mx-auto flex w-full max-w-[1200px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active="admin" />
      <div className="flex min-w-0 flex-1 flex-col gap-[22px]" data-testid="admin-emails">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="disp rise m-0 text-[40px] leading-none font-bold">Emails</h1>
          <span className="stamp quiet">Internal</span>
        </div>
        <p className="m-0 max-w-[640px] text-muted-foreground">
          Every email Voltage sends, filled in with sample data. Nothing here sends anything. <a href={hrefFor({ page: 'admin' })} className="act">Back to Admin</a>
        </p>
        {error && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {error}<button type="button" className="btn sm" onClick={loadKinds}>Try again</button>
          </div>
        )}
        {!error && !kinds && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading the emails…</p>}
        {kinds && (
          <div role="group" aria-label="Which email" className="flex flex-wrap gap-2">
            {kinds.map((k) => (
              <button key={k.kind} type="button" className={`btn sm ${kind === k.kind ? 'ink' : ''}`} aria-pressed={kind === k.kind}
                onClick={() => { setError(null); setKind(k.kind) }}>{k.label}</button>
            ))}
          </div>
        )}
        {kind && !mail && !error && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Drawing it…</p>}
        {mail && (
          <section className={`${card} flex min-w-0 flex-col gap-4`} aria-labelledby="mail-h" data-testid="email-preview">
            <div className="flex min-w-0 flex-col gap-1">
              <span className="tag text-faint">Subject</span>
              <h2 id="mail-h" className="disp m-0 text-[22px] font-bold [overflow-wrap:anywhere]">{mail.subject}</h2>
            </div>
            <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <div className="flex min-w-0 flex-col gap-2">
                <span className="tag text-faint">HTML</span>
                <iframe title={`${mail.label}: the HTML email`} sandbox="" srcDoc={mail.html}
                  className="h-[640px] w-full rounded-lg border-[1.5px] border-foreground bg-card" data-testid="email-html" />
              </div>
              <div className="flex min-w-0 flex-col gap-2">
                <span className="tag text-faint">Plain text</span>
                <pre className="m-0 max-h-[640px] overflow-auto rounded-lg bg-sunk p-4 font-mono text-[13px] leading-[1.55] whitespace-pre-wrap [overflow-wrap:anywhere]"
                  data-testid="email-text" tabIndex={0} aria-label={`${mail.label}: the plain-text email`}>{mail.text}</pre>
              </div>
            </div>
          </section>
        )}
      </div>
    </Shell>
  )
}
