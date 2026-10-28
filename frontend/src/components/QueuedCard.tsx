import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import type { QueueItem } from '../types'
import { QUEUE_STATE_STAMP, firstWords, isCardState, queueCardLabel, queueStateLabel, queuedText } from '../lib/queueState'

/** The stamp a queued message wears, by its state: "Queued 1 of 2", "Running", "Done", "Stopped", "Failed". */
export function QueueStamp({ item, live }: { item: QueueItem; live: QueueItem[] }) {
  const tone = isCardState(item.status) ? QUEUE_STATE_STAMP[item.status] : 'quiet'
  return <span className={cn('stamp shrink-0', tone)} data-testid="queued-state" data-state={item.status}>{queueStateLabel(item, live)}</span>
}

interface QueuedCardProps {
  item: QueueItem
  /** Up next as it stands (running first, then waiting in order): the card counts its place from it. */
  live: QueueItem[]
  /** Another tab's or member's work, or a reviewer: shown, not changed. */
  readOnly?: boolean
  /** New words for it; the server refuses once it has started (the promise rejects with its sentence). */
  onEdit?: (item: QueueItem, text: string) => Promise<unknown> | void
  onRemove?: (item: QueueItem) => void
}

/** Addendum 3.3: a message typed while Voltage was Working, in the thread where it will run.
 *  "Queued 1 of 2: <first words>" until it starts, with Edit and Remove; once it starts, your words
 *  become that turn's bubble and carry its state there. */
export function QueuedCard({ item, live, readOnly, onEdit, onRemove }: QueuedCardProps) {
  const text = queuedText(item)
  const waiting = item.status === 'queued'
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(text)
  const [saving, setSaving] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  // It started while the editor was open: nothing more can change, so the editor closes.
  useEffect(() => { if (!waiting) setEditing(false) }, [waiting])
  const open = () => {
    setDraft(text)                    // the editor opens on the words as they are now
    setEditing(true)
    requestAnimationFrame(() => { const el = box.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length) } })
  }
  const save = async () => {
    const next = draft.trim()
    if (!next || next === text.trim()) { setEditing(false); return }
    setSaving(true)
    try { await onEdit?.(item, next); setEditing(false) } catch { /* the editor stays open; the app says why */ } finally { setSaving(false) }
  }
  const short = firstWords(text)
  return (
    <div className={cn('flex flex-col gap-2 rounded-[10px] border-[1.5px] px-3.5 py-3', waiting ? 'border-dashed border-pline' : 'border-pline')}
      data-testid="queued-card" data-state={item.status} aria-label={queueCardLabel(item, live)} role="group">
      <div className="flex min-w-0 items-center gap-2 text-sm">
        <QueueStamp item={item} live={live} />
        <span className="sr-only">: </span>
        <span className="min-w-0 truncate" title={text}>{short}</span>
      </div>
      {editing ? (
        <div className="flex flex-col gap-2">
          <label htmlFor={`queued-${item.id}`} className="sr-only">Change what you asked</label>
          <textarea id={`queued-${item.id}`} ref={box} rows={2} value={draft} onChange={(e) => setDraft(e.target.value)}
            className="m-0 w-full resize-none rounded-lg border border-pline bg-psunk px-3 py-2 text-[15px] text-ptext outline-none focus-visible:outline-2 focus-visible:outline-volt"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void save() }
              if (e.key === 'Escape') { e.preventDefault(); setEditing(false) }
            }} />
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button type="button" className="btn ghost sm" onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
            <button type="button" className="btn volt sm" onClick={() => void save()} disabled={saving || !draft.trim()} aria-busy={saving || undefined}>Save</button>
          </div>
        </div>
      ) : (
        <>
          {short !== text.trim() && <p className="pm m-0 text-sm">{text}</p>}
          {item.status === 'failed' && item.error && <p className="pm m-0 text-sm">{item.error}</p>}
          {waiting && !readOnly && (onEdit || onRemove) && (
            <div className="flex flex-wrap items-center gap-1">
              {onEdit && <button type="button" className="act h-8 px-2 pointer-coarse:h-11" onClick={open} aria-label={`Edit ${short}`}>Edit</button>}
              {onRemove && <button type="button" className="act h-8 px-2 pointer-coarse:h-11" onClick={() => onRemove(item)} aria-label={`Remove ${short}`}>Remove</button>}
            </div>
          )}
        </>
      )}
    </div>
  )
}
