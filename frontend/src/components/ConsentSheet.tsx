import { useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogTitle } from '@/components/ui/dialog'
import { useReturnFocus } from './useReturnFocus'

interface ConsentSheetProps {
  /** Who the voice belongs to, when known: "the Shopkeeper". */
  who?: string | null
  onConfirm: () => void
  onCancel: () => void
  busy?: boolean
}

/** Asked once per project, the first time a voice is about to be made
 *  (UX-3): one sentence on what is about to happen, and why we ask. A real
 *  modal (a shadcn Dialog, so Radix does the work): focus lands on the title,
 *  Tab stays inside, Escape is "not yet", and focus returns to the opener. */
export function ConsentSheet({ who, onConfirm, onCancel, busy }: ConsentSheetProps) {
  const title = useRef<HTMLHeadingElement>(null)
  useReturnFocus()
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onCancel() }}>
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        aria-busy={busy || undefined}
        className="sm:max-w-md"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogTitle ref={title} tabIndex={-1} className="text-xl tracking-tight outline-none">Before I make a voice</DialogTitle>
        <div className="flex flex-col gap-2">
          <p className="m-0 text-base">
            I'll be creating speech in {who ? `${who}'s` : "this person's"} voice, and editing what they say on camera.
            Do you have their permission?
          </p>
          <p className="m-0 text-sm text-muted-foreground">Asked once for this project, and remembered. Deleting the project withdraws it.</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>Not yet, keep it as a draft</Button>
          <Button onClick={onConfirm} disabled={busy}>{busy ? 'Saving…' : 'Yes, I have it'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
