import { useState } from 'react'
import { withdrawConsent } from '../api'
import { said } from '../pages/fmt'

/** G6: withdraw consent now. The speaker's clone is deleted at the voice service at once (not
 *  when the Bin empties); asked once inline before it happens. */
export function WithdrawConsent({ videoId, onWithdrawn }: { videoId: string; onWithdrawn: () => void }) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const go = async () => {
    setBusy(true); setNote(null)
    try { const r = await withdrawConsent(videoId); setNote(r.said); setAsking(false); onWithdrawn() } catch (e) { setNote(said(e, 'Consent was not withdrawn. Try again.')) } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-2 rounded-xl border-[1.5px] border-line2 bg-card px-4 py-3" data-testid="withdraw-consent">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex-1 text-sm text-muted-foreground">{note ?? 'Consent to use the speaker\'s voice is on record. Withdrawing it deletes their voice clone now.'}</span>
        {!asking && !note && <button type="button" className="act" onClick={() => setAsking(true)}>Withdraw consent now</button>}
      </div>
      {asking && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border-[1.5px] border-destructive bg-card p-3" role="group" aria-label="Withdraw consent?">
          <span className="flex-1 text-sm">The clone is deleted at the voice service and new lines in this voice stop. Lines already added stay.</span>
          <button type="button" className="act" onClick={() => setAsking(false)} disabled={busy}>Keep it</button>
          <button type="button" className="btn sm border-destructive text-destructive" onClick={() => void go()} disabled={busy}>{busy ? 'Withdrawing…' : 'Withdraw and delete the clone'}</button>
        </div>
      )}
    </div>
  )
}
