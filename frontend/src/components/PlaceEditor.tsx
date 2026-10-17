import { useEffect, useState } from 'react'
import type { Selection, Voice } from '../types'
import { parseTime, timecode } from '../transcript/time'
import type { LineRequest } from './LineDoc'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Chip, ControlRow, LinkButton } from './EditorControls'
import { editorClass, selectClass } from './editorStyles'

interface PlaceEditorProps {
  duration: number
  voices?: Voice[]
  usdPerChar?: number | null
  disabled?: boolean
  /** The block on the monitor's bar while the span is chosen; dragging it moves the start. */
  placing?: { id: string; start: number; duration: number } | null
  onPlacing?: (placing: { id: string; start: number; duration: number } | null) => void
  onHear: (span: Selection, request: LineRequest) => void
  onCancel?: () => void
  /** Where the span starts when the editor opens. */
  initialStart?: number
}

const DELIVERIES = ['warmer', 'more excited', 'calmer', 'slower', 'firmer']
const PLACING_ID = 'voice-over'
const voiceLabel = (v: Voice) => (v.gender ? `${v.name} (${v.gender})` : v.name)
const round2 = (t: number) => Math.round(t * 100) / 100

/** Where should the voice-over go? (UX-5, SV-4.) On a clip with no speech the
 *  transcript has no rows to hang a line on, so this editor places one by
 *  time: a span on the monitor's bar (drag it, type it, or nudge it), the
 *  words, and the same choices a line's editor offers. Dragging is never the
 *  only way: the start and end can be typed and nudged. */
export function PlaceEditor({
  duration, voices = [], usdPerChar, disabled, placing, onPlacing, onHear, onCancel, initialStart = 0.5,
}: PlaceEditorProps) {
  const defaultStart = Math.min(initialStart, Math.max(0, duration - 1))
  const [startText, setStartText] = useState(timecode(defaultStart))
  const [endText, setEndText] = useState(timecode(Math.min(duration, defaultStart + 3)))
  const [draft, setDraft] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [delivery, setDelivery] = useState<string | null>(null)
  const [ownWords, setOwnWords] = useState<string | null>(null)
  const [mix, setMix] = useState<'layer' | 'concatenate'>('layer')

  const start = parseTime(startText)
  const end = parseTime(endText)
  const badStart = start === null || start < 0 || start >= duration
  const badEnd = end === null || (start !== null && end <= start) || end > duration + 0.001
  const span: Selection | null = !badStart && !badEnd ? { start: start!, end: end! } : null

  // The block on the bar follows the typed span; a drag of the block moves the start.
  useEffect(() => {
    if (!onPlacing || !span) return
    if (placing?.id === PLACING_ID && Math.abs(placing.start - span.start) < 0.005 && Math.abs(placing.duration - (span.end - span.start)) < 0.005) return
    onPlacing({ id: PLACING_ID, start: span.start, duration: span.end - span.start })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [span?.start, span?.end])
  useEffect(() => {
    if (placing?.id !== PLACING_ID || !span) return
    if (Math.abs(placing.start - span.start) < 0.005) return
    const length = span.end - span.start
    setStartText(timecode(round2(placing.start)))
    setEndText(timecode(round2(Math.min(duration, placing.start + length))))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placing?.start])
  useEffect(() => () => { if (onPlacing) onPlacing(null) }, [onPlacing])

  const nudge = (which: 'start' | 'end', by: number) => {
    if (which === 'start' && start !== null) {
      const length = end !== null && end > start ? end - start : 3
      const s = round2(Math.min(Math.max(0, start + by), Math.max(0, duration - 0.5)))
      setStartText(timecode(s))
      setEndText(timecode(round2(Math.min(duration, s + length))))
    }
    if (which === 'end' && end !== null) setEndText(timecode(round2(Math.min(duration, Math.max((start ?? 0) + 0.5, end + by)))))
  }
  const chars = draft.trim().length
  const cost = usdPerChar ? ` · about ${Math.max(1, Math.round(chars * usdPerChar * 100))}¢` : ''
  const canHear = !disabled && !!draft.trim() && span !== null
  const hear = () => {
    if (!canHear || !span) return
    onHear(span, {
      selection: span, text: draft.trim(), voiceId: voiceId || null,
      delivery: (ownWords?.trim() || delivery) ?? null, mix,
    })
  }
  const invalid = badStart || badEnd
  return (
    <div className={editorClass} data-testid="place-editor">
      <h3 className="m-0 text-base font-semibold">Where should the voice-over go?</h3>
      <ControlRow label="From">
        <Input className="w-28" aria-label="Starts at" aria-invalid={badStart || undefined} value={startText} onChange={(e) => setStartText(e.target.value)} />
        <Button type="button" variant="outline" size="sm" aria-label="Start earlier" onClick={() => nudge('start', -0.1)}>◀</Button>
        <Button type="button" variant="outline" size="sm" aria-label="Start later" onClick={() => nudge('start', 0.1)}>▶</Button>
        <span className="whitespace-nowrap">to</span>
        <Input className="w-28" aria-label="Ends at" aria-invalid={badEnd || undefined} value={endText} onChange={(e) => setEndText(e.target.value)} />
        <Button type="button" variant="outline" size="sm" aria-label="End earlier" onClick={() => nudge('end', -0.1)}>◀</Button>
        <Button type="button" variant="outline" size="sm" aria-label="End later" onClick={() => nudge('end', 0.1)}>▶</Button>
        <span className={invalid ? 'text-destructive' : 'text-muted-foreground'} role={invalid ? 'alert' : undefined}>
          {invalid ? `Times like 0:00.50, inside the clip's ${timecode(duration)}.` : 'Drag the block on the bar above, or type the times.'}
        </span>
      </ControlRow>
      <Textarea
        value={draft}
        rows={2}
        aria-label="Words for the voice-over"
        placeholder="The exact words to say, e.g. Welcome to Goa. (A brief goes to Voltage in the box on the right.)"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); hear() }
          if (e.key === 'Escape' && onCancel) onCancel()
        }}
      />
      <ControlRow label="Delivery">
        <Chip on={delivery === null && ownWords === null} onClick={() => { setDelivery(null); setOwnWords(null) }}>As spoken</Chip>
        {DELIVERIES.map((d) => (
          <Chip key={d} on={delivery === d} onClick={() => { setDelivery(d); setOwnWords(null) }}>
            {d.charAt(0).toUpperCase() + d.slice(1)}
          </Chip>
        ))}
        {ownWords === null
          ? <LinkButton onClick={() => { setOwnWords(''); setDelivery(null) }}>in your words…</LinkButton>
          : <Input className="w-48" aria-label="Delivery, in your words" placeholder="e.g. like a travel film" value={ownWords} onChange={(e) => setOwnWords(e.target.value)} />}
      </ControlRow>
      {voices.length > 0 && (
        <ControlRow label="Voice">
          <select className={selectClass} aria-label="Voice" value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
            <option value="">Default voice</option>
            {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{voiceLabel(v)}</option>)}
          </select>
        </ControlRow>
      )}
      <ControlRow label="Sound meets picture" role="group" aria-label="Sound meets picture">
        <Chip on={mix === 'layer'} onClick={() => setMix('layer')}>Over the picture</Chip>
        <Chip on={mix === 'concatenate'} onClick={() => setMix('concatenate')}>Hold the picture</Chip>
        <span>{mix === 'layer' ? 'The picture keeps moving under the line.' : 'The picture waits while the line plays.'}</span>
      </ControlRow>
      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
        <span className="tnum text-sm text-muted-foreground">≈ {chars} characters{cost} · ready in about 10 s</span>
        <span className="flex-1" />
        {onCancel && <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>}
        <Button type="button" disabled={!canHear} onClick={hear}>Voice it</Button>
      </div>
    </div>
  )
}
