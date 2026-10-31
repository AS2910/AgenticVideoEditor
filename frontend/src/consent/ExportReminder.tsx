import { useId, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { confirmExport } from '../api'
import { said } from '../pages/fmt'
import { useReturnFocus } from '../components/useReturnFocus'
import { EXPORT, exportTitle } from './copy'
import type { ExportFacts } from './types'

/** Voice consent V1 step 6: the export reminder, in the plan's words. The
 *  "AI voice" label is ticked by default (the person may untick it); the
 *  permission box is required. One reminder covers every voice of the export,
 *  or of the whole batch. Export posts `{label_on}`; Back (or Escape) leaves
 *  the export unmade. A real dialog: focus in, Tab stays inside, focus back. */
export function ExportReminder({ facts, onDone, onBack }: { facts: ExportFacts; onDone: () => void; onBack: () => void }) {
  const id = useId()
  const title = useRef<HTMLHeadingElement>(null)
  const [label, setLabel] = useState(facts.label_default ?? true)
  const [permission, setPermission] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useReturnFocus()
  const ready = permission && !busy

  const accept = async () => {
    if (!ready) return
    setBusy(true); setError(null)
    try {
      await confirmExport(facts.export_ref, label)
      onDone()
    } catch (e) { setError(said(e, 'That could not be saved. Try again.')); setBusy(false) }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onBack() }}>
      <DialogContent showCloseButton={false} aria-describedby={undefined} aria-busy={busy || undefined} className="gap-4 border-[1.5px] border-ink sm:max-w-md"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }} onInteractOutside={(e) => e.preventDefault()} data-testid="export-reminder">
        <DialogTitle ref={title} tabIndex={-1} className="disp text-xl leading-snug tracking-tight outline-none">{exportTitle(facts.voices)}</DialogTitle>
        <div className="flex flex-col gap-2">
          <label className="flex min-h-11 cursor-pointer items-start gap-2.5 text-sm" htmlFor={`${id}-label`}>
            <input id={`${id}-label`} type="checkbox" className="mt-0.5 size-4 shrink-0 accent-volt" checked={label} disabled={busy} onChange={(e) => setLabel(e.target.checked)} data-testid="export-label" />
            <span>{EXPORT.label}</span>
          </label>
          <label className="flex min-h-11 cursor-pointer items-start gap-2.5 text-sm" htmlFor={`${id}-ok`}>
            <input id={`${id}-ok`} type="checkbox" className="mt-0.5 size-4 shrink-0 accent-volt" checked={permission} disabled={busy} onChange={(e) => setPermission(e.target.checked)} data-testid="export-permission" />
            <span>{EXPORT.confirm}</span>
          </label>
        </div>
        {error && <p className="m-0 text-[13px] text-needs" role="alert">{error}</p>}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button type="button" className="btn sm" onClick={onBack} disabled={busy} data-testid="export-back">{EXPORT.back}</button>
          <button type="button" className="btn ink sm" onClick={() => void accept()} disabled={!ready} aria-busy={busy || undefined} data-testid="export-accept">{busy ? 'Saving…' : EXPORT.accept}</button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
