import { useEffect, useState } from 'react'
import type { LongLines, Selection, Voice } from '../types'
import { parseTime, timecode } from '../transcript/time'
import type { LineRequest } from './LineDoc'
import styles from './LineDoc.module.css'

interface PlaceEditorProps {
  duration: number
  voices?: Voice[]
  usdPerChar?: number | null
  longLines?: LongLines
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
const LONG_OPTIONS: { value: LongLines; label: string }[] = [
  { value: 'pause', label: 'Let Voltage fit it' },
  { value: 'shorten', label: 'Prefer a shorter wording' },
  { value: 'stretch', label: 'Speed it up' },
  { value: 'ask', label: 'Ask me' },
]
const PLACING_ID = 'voice-over'
const voiceLabel = (v: Voice) => (v.gender ? `${v.name} (${v.gender})` : v.name)
const round2 = (t: number) => Math.round(t * 100) / 100

/** Where should the voice-over go? (UX-5, SV-4.) On a clip with no speech the
 *  transcript has no rows to hang a line on, so this editor places one by
 *  time: a span on the monitor's bar (drag it, type it, or nudge it), the
 *  words, and the same choices a line's editor offers. Dragging is never the
 *  only way: the start and end can be typed and nudged. */
export function PlaceEditor({
  duration, voices = [], usdPerChar, longLines = 'pause', disabled, placing, onPlacing, onHear, onCancel, initialStart = 0.5,
}: PlaceEditorProps) {
  const defaultStart = Math.min(initialStart, Math.max(0, duration - 1))
  const [startText, setStartText] = useState(timecode(defaultStart))
  const [endText, setEndText] = useState(timecode(Math.min(duration, defaultStart + 3)))
  const [draft, setDraft] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [delivery, setDelivery] = useState<string | null>(null)
  const [ownWords, setOwnWords] = useState<string | null>(null)
  const [mix, setMix] = useState<'layer' | 'concatenate'>('layer')
  const [onLong, setOnLong] = useState<LongLines>(longLines)

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
      selection: span, text: draft.trim(), voiceId: voiceId || null, onLong,
      delivery: (ownWords?.trim() || delivery) ?? null, mix,
    })
  }
  return (
    <div className={styles.editor} data-testid="place-editor">
      <h3 className={styles.placeTitle}>Where should the voice-over go?</h3>
      <div className={styles.control}>
        <span className={styles.controlLabel}>From</span>
        <input className={styles.ownWords} aria-label="Starts at" aria-invalid={badStart || undefined} value={startText} onChange={(e) => setStartText(e.target.value)} />
        <button type="button" className={styles.secondary} aria-label="Start earlier" onClick={() => nudge('start', -0.1)}>◀</button>
        <button type="button" className={styles.secondary} aria-label="Start later" onClick={() => nudge('start', 0.1)}>▶</button>
        <span className={styles.controlLabel}>to</span>
        <input className={styles.ownWords} aria-label="Ends at" aria-invalid={badEnd || undefined} value={endText} onChange={(e) => setEndText(e.target.value)} />
        <button type="button" className={styles.secondary} aria-label="End earlier" onClick={() => nudge('end', -0.1)}>◀</button>
        <button type="button" className={styles.secondary} aria-label="End later" onClick={() => nudge('end', 0.1)}>▶</button>
        <span className={badStart || badEnd ? styles.invalid : styles.faint} role={badStart || badEnd ? 'alert' : undefined}>
          {badStart || badEnd ? `Times like 0:00.50, inside the clip's ${timecode(duration)}.` : 'Drag the block on the bar above, or type the times.'}
        </span>
      </div>
      <textarea
        className={styles.box}
        value={draft}
        rows={2}
        aria-label="Words for the voice-over"
        placeholder="What should be said here?"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); hear() }
          if (e.key === 'Escape' && onCancel) onCancel()
        }}
      />
      <div className={styles.control}>
        <span className={styles.controlLabel}>Delivery</span>
        <button type="button" className={delivery === null && ownWords === null ? styles.pillOn : styles.pill} aria-pressed={delivery === null && ownWords === null} onClick={() => { setDelivery(null); setOwnWords(null) }}>As spoken</button>
        {DELIVERIES.map((d) => (
          <button key={d} type="button" className={delivery === d ? styles.pillOn : styles.pill} aria-pressed={delivery === d} onClick={() => { setDelivery(d); setOwnWords(null) }}>
            {d.charAt(0).toUpperCase() + d.slice(1)}
          </button>
        ))}
        {ownWords === null
          ? <button type="button" className={styles.link} onClick={() => { setOwnWords(''); setDelivery(null) }}>in your words…</button>
          : <input className={styles.ownWords} aria-label="Delivery, in your words" placeholder="e.g. like a travel film" value={ownWords} onChange={(e) => setOwnWords(e.target.value)} />}
      </div>
      {voices.length > 0 && (
        <div className={styles.control}>
          <span className={styles.controlLabel}>Voice</span>
          <select aria-label="Voice" value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
            <option value="">Default voice</option>
            {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{voiceLabel(v)}</option>)}
          </select>
        </div>
      )}
      <div className={styles.control} role="group" aria-label="Sound meets picture">
        <span className={styles.controlLabel}>Sound meets picture</span>
        <button type="button" className={mix === 'layer' ? styles.pillOn : styles.pill} aria-pressed={mix === 'layer'} onClick={() => setMix('layer')}>Over the picture</button>
        <button type="button" className={mix === 'concatenate' ? styles.pillOn : styles.pill} aria-pressed={mix === 'concatenate'} onClick={() => setMix('concatenate')}>Hold the picture</button>
        <span className={styles.faint}>{mix === 'layer' ? 'The picture keeps moving under the line.' : 'The picture waits while the line plays.'}</span>
      </div>
      <div className={styles.control}>
        <span className={styles.controlLabel}>If it runs long</span>
        <select aria-label="If it runs long" value={onLong} onChange={(e) => setOnLong(e.target.value as LongLines)}>
          {LONG_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      <div className={styles.editorFoot}>
        <span className={styles.faint}>≈ {chars} characters{cost} · ready in about 10 s</span>
        <span className={styles.spacer} />
        {onCancel && <button type="button" className={styles.secondary} onClick={onCancel}>Cancel</button>}
        <button type="button" className={styles.primary} disabled={!canHear} onClick={hear}>Hear it</button>
      </div>
    </div>
  )
}
