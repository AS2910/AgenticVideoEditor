import { useRef } from 'react'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { useReturnFocus } from '../components/useReturnFocus'
import { AttestationForm } from './AttestationForm'
import type { AttestationFacts } from './types'

/** Voice consent V1 step 6: the attestation as a modal, opened by a 409
 *  attestation_required wherever a voicing starts. A shadcn Dialog, so Radix
 *  does the work: focus lands on the title, Tab stays inside, Escape cancels,
 *  and focus goes back to the opener. */
export function AttestationModal({ facts, onDone, onCancel }: { facts: AttestationFacts; onDone: () => void; onCancel: () => void }) {
  const title = useRef<HTMLHeadingElement>(null)
  useReturnFocus()
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onCancel() }}>
      <DialogContent showCloseButton={false} aria-describedby={undefined} className="border-[1.5px] border-ink sm:max-w-md"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }} onInteractOutside={(e) => e.preventDefault()} data-testid="attestation-modal">
        <AttestationForm facts={facts} onDone={onDone} onCancel={onCancel}
          title={(text) => <DialogTitle ref={title} tabIndex={-1} className="disp text-xl leading-snug tracking-tight outline-none">{text}</DialogTitle>} />
      </DialogContent>
    </Dialog>
  )
}
