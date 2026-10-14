import { Fragment, useRef, useState } from 'react'
import type { PlanItem } from '../types'
import { diffWords } from '../transcript/changes'
import { clock } from '../transcript/format'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Presence } from './Presence'
import { useReturnFocus } from './useReturnFocus'

export interface Shipped {
  /** The lines that went into this render. */
  items: PlanItem[]
  /** Lines held back as drafts. */
  held: number
  /** Removed lines in force (hands-on), counted for the file's contents. */
  removed: number
  before: number
  after: number
  download: { url: string; filename: string }
  spendUsd: number
  /** Voice calls made for the plan: how many takes it took (the polish pass). */
  takesVoiced?: number
}

interface ShipSheetProps {
  shipped: Shipped
  onVariant: () => void
  /** Undo a line that just shipped: it goes back to a draft. */
  onUndo?: (item: PlanItem) => void
  onClose: () => void
  busy?: boolean
}

const after = (item: PlanItem) =>
  item.mix === 'concatenate' || item.mix === 'over' ? `${item.old_text} ${item.new_text}` : item.new_text

/** The receipt (UX-7d, from the ship sheet of UX-3): what is in the file as
 *  stat tiles and as the lines themselves, what was held, the stand-in voice
 *  said plainly, then Download, Copy link, Make a variant. A shadcn Dialog:
 *  focus lands on the title, Tab stays inside, Escape closes, and focus goes
 *  back to whatever opened it. */
export function ShipSheet({ shipped, onVariant, onUndo, onClose, busy }: ShipSheetProps) {
  const [copied, setCopied] = useState<boolean | 'failed'>(false)
  const title = useRef<HTMLHeadingElement>(null)
  useReturnFocus()
  const changed = shipped.items.filter((i) => i.mix === 'replace').length
  const added = shipped.items.filter((i) => i.mix !== 'replace' && i.mix !== 'remove').length
  const removed = shipped.items.filter((i) => i.mix === 'remove').length + shipped.removed
  const longer = shipped.after - shipped.before
  const length = Math.abs(longer) < 0.05
    ? `Same length as before, ${shipped.after.toFixed(1)} seconds.`
    : `${Math.abs(longer).toFixed(1)} s ${longer > 0 ? 'longer' : 'shorter'}: ${shipped.before.toFixed(1)} → ${shipped.after.toFixed(1)} seconds.`
  const link = new URL(shipped.download.url, window.location.origin).toString()
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
    } catch {
      setCopied('failed')
    }
  }
  const tiles: { n: string; label: string }[] = [
    { n: String(changed), label: changed === 1 ? 'line changed' : 'lines changed' },
    ...(added > 0 ? [{ n: String(added), label: added === 1 ? 'line added' : 'lines added' }] : []),
    ...(removed > 0 ? [{ n: String(removed), label: removed === 1 ? 'line removed' : 'lines removed' }] : []),
    { n: String(shipped.held), label: shipped.held === 1 ? 'held as a draft' : 'held as drafts' },
    ...(shipped.takesVoiced ? [{ n: String(shipped.takesVoiced), label: shipped.takesVoiced === 1 ? 'take voiced' : 'takes voiced' }] : []),
    { n: `$${shipped.spendUsd.toFixed(2)}`, label: 'for this plan' },
  ]
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        data-testid="ship-sheet"
        className="max-h-[calc(100dvh-2rem)] gap-4 overflow-y-auto sm:max-w-2xl"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <div className="flex items-start gap-3">
          <Presence size={24} className="mt-1" />
          <div>
            <DialogTitle ref={title} tabIndex={-1} className="text-2xl tracking-tight outline-none">It's shipped.</DialogTitle>
            <p className="m-0 mt-1 text-base text-muted-foreground">{length}</p>
          </div>
        </div>
        <dl className="m-0 grid grid-cols-[repeat(auto-fit,minmax(110px,1fr))] gap-4 rounded-lg border border-border bg-muted p-4" aria-label="What is in the file, counted">
          {tiles.map((t) => (
            <div key={t.label} className="flex flex-col gap-0.5"><dd className="tnum m-0 text-2xl font-semibold tracking-tight">{t.n}</dd><dt className="text-xs text-muted-foreground">{t.label}</dt></div>
          ))}
        </dl>
        <div className="flex flex-col gap-1">
          <h3 className="m-0 mb-1 text-base font-semibold tracking-tight">What's in the file</h3>
          <ul className="m-0 flex max-h-[30dvh] list-none flex-col overflow-y-auto p-0 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" tabIndex={shipped.items.length > 4 ? 0 : undefined} aria-label="What was said">
            {shipped.items.map((i) => (
              <li key={i.item_id} className="grid grid-cols-[44px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border py-2.5 text-sm leading-normal first:border-t-0">
                <span className="tnum text-xs text-muted-foreground">{clock(i.selection.start)}</span>
                <span className="min-w-0">
                  <span className="sr-only">{i.mix === 'replace' ? 'Said ' : i.mix === 'remove' ? 'Removed ' : 'Added '}</span>
                  {i.mix === 'remove' ? <span className="text-muted-foreground">Removed. The room's own quiet fills the gap.</span>
                    : diffWords(i.old_text, after(i)).filter((r) => r.kind !== 'del').map((run, k) => (
                      <Fragment key={k}>{k > 0 && ' '}{run.kind === 'ins' ? <ins className="rounded-sm bg-changed-soft px-1 text-changed no-underline">{run.text}</ins> : run.text}</Fragment>
                    ))}
                  {i.note && <span className="text-muted-foreground"> {i.note}{/[.!?]$/.test(i.note) ? '' : '.'}</span>}
                  {i.candidate?.plan.flex != null && Math.abs(i.candidate.plan.flex - 1) > 0.005 && <span className="text-muted-foreground"> picture at {i.candidate.plan.flex.toFixed(2)}×</span>}
                </span>
                {onUndo && i.edit_id && <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => onUndo(i)} disabled={busy}>Undo</Button>}
              </li>
            ))}
            {shipped.held > 0 && (
              <li className="grid grid-cols-[44px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border py-2.5 text-sm leading-normal first:border-t-0">
                <span aria-hidden="true" />
                <span className="min-w-0 text-muted-foreground">{shipped.held === 1 ? 'One change held as a draft; that line is in as shot.' : `${shipped.held} changes held as drafts; those lines are in as shot.`}</span>
              </li>
            )}
          </ul>
        </div>
        <p className="m-0 text-sm text-muted-foreground">The new words are in a stand-in voice, and the mouth still moves to the old ones.</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild><a href={shipped.download.url} download={shipped.download.filename}>Download MP4</a></Button>
          <Button variant="outline" onClick={() => void copy()}>{copied === true ? 'Link copied' : 'Copy link'}</Button>
          <span className="sr-only" role="status">{copied === true ? 'Link copied' : copied === 'failed' ? 'Could not copy the link; use Download instead.' : ''}</span>
          <Button variant="outline" onClick={onVariant} disabled={busy}>{busy ? 'Making a variant…' : 'Make a variant'}</Button>
          <span className="flex-1" />
          <Button variant="ghost" className="text-muted-foreground" onClick={onClose}>Back to the transcript</Button>
        </div>
        <p className="m-0 text-sm text-muted-foreground">A variant is this clip again with the plan as a draft, for another offer or another wording; nothing is voiced until you say so.</p>
      </DialogContent>
    </Dialog>
  )
}
