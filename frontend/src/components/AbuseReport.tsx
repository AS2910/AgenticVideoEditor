import { useEffect, useState } from 'react'
import { abuseFormOpen, reportAbuse } from '../api'
import { said } from '../pages/fmt'

const KINDS: [string, string][] = [
  ['impersonation', "Someone's voice used without their consent"], ['public_figure', "A public figure's voice"],
  ['misleading', 'Misleading or deceptive content'], ['hateful', 'Hateful, harassing or violent content'], ['other', 'Something else'],
]

/** G6: report misuse. Public (no account): on shared links and in Help. Stored, and the people
 *  who run Voltage are told. `location` defaults to the page it was opened from. */
export function AbuseReport({ location, compact = false }: { location?: string; compact?: boolean }) {
  const [open, setOpen] = useState(!compact)
  const [kind, setKind] = useState('')
  const [where, setWhere] = useState(location ?? (typeof window !== 'undefined' ? window.location.href : ''))
  const [details, setDetails] = useState('')
  const [contact, setContact] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [taking, setTaking] = useState(false)
  useEffect(() => {
    let live = true
    abuseFormOpen().then((o) => { if (live) setTaking(o) }).catch(() => { /* no form where reports are not taken */ })
    return () => { live = false }
  }, [])
  if (!taking) return null
  if (!open) return <button type="button" className="act self-start" onClick={() => setOpen(true)}>Report misuse</button>
  if (done) return <p className="m-0 rounded-lg border-[1.5px] border-foreground bg-card px-4 py-3" role="status" data-testid="abuse-done">{done}</p>
  const send = async () => {
    setBusy(true); setError(null)
    try { setDone((await reportAbuse({ location: where.trim(), kind, details: details.trim(), contact: contact.trim() })).said) }
    catch (e) { setError(said(e, 'That report did not send. Try again.')) }
    finally { setBusy(false) }
  }
  return (
    <form className="flex flex-col gap-3 rounded-xl border-[1.5px] border-foreground bg-card p-[22px]" aria-labelledby="abuse-h" data-testid="abuse-form"
      onSubmit={(e) => { e.preventDefault(); void send() }}>
      <h2 id="abuse-h" className="disp m-0 text-[22px] font-bold">Report misuse</h2>
      <p className="m-0 text-[13px] text-muted-foreground">Tell us about a voice used without consent, a public figure, or anything harmful. No account needed.</p>
      <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
        <legend className="mb-1 text-[13px] font-semibold">What is wrong</legend>
        {KINDS.map(([k, label]) => (
          <label key={k} className="flex items-center gap-2 text-sm"><input type="radio" className="accent-foreground" name="abuse-kind" value={k} checked={kind === k} onChange={() => setKind(k)} />{label}</label>
        ))}
      </fieldset>
      <label className="flex flex-col gap-1 text-[13px] font-semibold">Where (a link)
        <input className="h-9 rounded-lg border-[1.5px] border-foreground bg-card px-2 font-normal" value={where} maxLength={1000} onChange={(e) => setWhere(e.target.value)} required />
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-semibold">What happened (optional)
        <textarea className="min-h-20 rounded-lg border-[1.5px] border-foreground bg-card p-2 font-normal" value={details} maxLength={4000} onChange={(e) => setDetails(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-semibold">How to reach you (optional)
        <input className="h-9 rounded-lg border-[1.5px] border-foreground bg-card px-2 font-normal" value={contact} maxLength={200} onChange={(e) => setContact(e.target.value)} />
      </label>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      <button type="submit" className="btn volt sm self-start" disabled={busy || !kind || !where.trim()}>{busy ? 'Sending…' : 'Send report'}</button>
    </form>
  )
}
