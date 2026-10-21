import { useEffect, useState } from 'react'
import { track } from '../lib/analytics'
import { giveDecisionReason } from '../api'
import { said } from '../pages/fmt'

/** D2: after Discard, one optional question: why? A tap on a reason tells
 *  Voltage (it learns from your decisions in this project); Skip or doing
 *  nothing for a while closes it. Nothing about the video changes. */
export function DiscardWhy({ videoId, decisionId, line, reasons, onClose }: {
  videoId: string; decisionId: number; line: string; reasons: readonly string[]; onClose: () => void
}) {
  const [state, setState] = useState<'ask' | 'sending' | 'thanks'>('ask')
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const t = window.setTimeout(onClose, state === 'thanks' ? 2500 : 15000)
    return () => window.clearTimeout(t)
  }, [state, onClose])
  const send = async (reason: string) => {
    setState('sending')
    setError(null)
    try {
      await giveDecisionReason(videoId, decisionId, reason)
      track('proposal.discard_reason_given', { reason })
      setState('thanks')
    } catch (e) {
      setError(said(e, 'Could not send that.'))
      setState('ask')
    }
  }
  return (
    <div role="group" aria-label="Why was it discarded?" data-testid="discard-why"
      className="rise fixed bottom-6 left-1/2 z-30 flex w-[min(560px,calc(100vw-32px))] min-[960px]:left-[calc((100vw-400px)/2)] -translate-x-1/2 flex-wrap items-center gap-2 rounded-xl border-[1.5px] border-ink bg-card p-3.5 shadow-volt"
      onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }}>
      {state === 'thanks' ? (
        <span className="text-sm" role="status">Thanks. Voltage learns from this in this project.</span>
      ) : (
        <>
          <span className="min-w-0 flex-[1_1_100%] text-sm">Discarded {line}. Tell Voltage why? <span className="text-muted-foreground">Optional.</span></span>
          {reasons.map((r) => (
            <button key={r} type="button" className="pill" disabled={state === 'sending'} onClick={() => void send(r)}>{r}</button>
          ))}
          <span className="flex-1" />
          <button type="button" className="act" onClick={onClose}>Skip</button>
          {error && <span className="flex-[1_1_100%] text-[13px] text-destructive" role="alert">{error}</span>}
        </>
      )}
    </div>
  )
}
