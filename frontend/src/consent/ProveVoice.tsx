import { useRef, useState } from 'react'
import { Dialog, DialogContent, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { promoteVoice, type ConsentStatus } from '../api'
import { LivenessStep } from '../components/LivenessStep'
import { useReturnFocus } from '../components/useReturnFocus'
import { said } from '../pages/fmt'
import { VOICES, keptWhy, type ProveOutcome } from './copy'
import type { VoiceScope } from './types'

/** Voice consent V1 step 6: "Save to My voices" on a video-only voice opens
 *  the existing own-voice check, retitled "Prove it's your voice". A pass
 *  promotes the voice (POST /voices/{id}/promote); review or a fail keeps it
 *  for its video, with the reason. A real dialog (focus in, Escape closes). */
export function ProveVoice({ name, scope, onClose }: { name: string; scope: VoiceScope; onClose: (outcome: ProveOutcome | null) => void }) {
  const title = useRef<HTMLHeadingElement>(null)
  const [outcome, setOutcome] = useState<ProveOutcome | null>(null)
  const [busy, setBusy] = useState(false)
  useReturnFocus()
  const videoId = scope.source_video_id
  const speaker = scope.speaker_label && scope.speaker_label !== '_' ? scope.speaker_label : null

  const passed = async (attemptId: string | null) => {
    if (!attemptId || busy) return
    setBusy(true)
    try {
      await promoteVoice(scope.voice_id)
      setOutcome({ saved: true })
    } catch (e) {
      setOutcome({ saved: false, status: 'error', reason: said(e, 'It could not be saved. Try again.') })
    } finally { setBusy(false) }
  }
  const settled = (status: ConsentStatus, reason: string) => {
    if (status === 'review' || status === 'failed') setOutcome({ saved: false, status, reason })
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(outcome) }}>
      <DialogContent showCloseButton={false} aria-describedby={undefined} className="border-[1.5px] border-ink sm:max-w-md"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }} onInteractOutside={(e) => e.preventDefault()} data-testid="prove-voice">
        <DialogTitle ref={title} tabIndex={-1} className="disp text-xl tracking-tight outline-none">{VOICES.prove}</DialogTitle>
        <p className="m-0 text-sm text-muted-foreground">Read the phrase in your own voice. When it matches {name}, the voice is saved to My voices and works in any video.</p>
        {videoId
          ? <LivenessStep videoId={videoId} who={name} speaker={speaker} onPassed={(id) => void passed(id)} onSettled={settled} />
          : <p className="m-0 text-sm text-needs" role="alert">The video this voice came from is gone, so it cannot be checked.</p>}
        {outcome && (
          <p className={outcome.saved ? 'm-0 text-sm' : 'm-0 text-sm text-needs'} role="status" data-testid="prove-outcome">
            {outcome.saved ? `Saved. ${name} is in My voices now.` : keptWhy(outcome)}
          </p>
        )}
        <DialogFooter>
          <button type="button" className={outcome?.saved ? 'btn volt sm' : 'btn sm'} onClick={() => onClose(outcome)} disabled={busy}>{outcome ? 'Done' : 'Cancel'}</button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
