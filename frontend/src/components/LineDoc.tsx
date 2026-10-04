import { Fragment, useEffect, useRef, useState } from 'react'
import type {
  Candidate, ItemStatus, LineStatus, LongLines, Mix, Question, QuestionOption, Revision, Selection, Speaker, Statement, Voice, Word,
} from '../types'
import { diffWords, lineAfter, trackedChanges } from '../transcript/changes'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { verdict } from '../transcript/verdict'
import { parseTime, timecode } from '../transcript/time'
import { Avatar } from './Avatar'
import styles from './LineDoc.module.css'

import { addKeyOf, keyOf } from '../transcript/keys'
import type { LineKey } from '../transcript/keys'

/** What was asked for a line, so Another take asks the same again. */
export interface LineRequest {
  selection: Selection
  text: string
  voiceId: string | null
  onLong: LongLines
  delivery: string | null
  mix: 'replace' | 'over' | 'concatenate'
  /** For an added line: a chosen start on the timeline instead of "after this line". */
  at?: number | null
}

/** Where a line stands while Voltage works on it, and the takes to choose from. */
export interface LineState {
  status: 'working' | 'ready' | 'needs-you' | 'failed'
  takes: Candidate[]
  question?: Question | null
  error?: string | null
  progress?: string | null
  request?: LineRequest
}

/** A line the agent's plan is working on: where it stands, and the new words. */
export interface PendingLine { selection: Selection; status: LineStatus | ItemStatus | 'reading'; text?: string; mix?: Mix }

/** How the last take of a line was made to fit, for the readout under the editor. */
export interface FitReadout { selection: Selection; tags: string[] }

interface LineDocProps {
  statements: Statement[]
  words?: Word[]
  speakers?: Speaker[]
  voices?: Voice[]
  /** Approved edits still in force, shown on their lines. */
  revisions?: Revision[]
  selection?: Selection | null
  currentTime: number
  /** The agent's plan, line by line. */
  pendingLines?: PendingLine[]
  /** Lines being worked on by hand, keyed by `keyOf` / `addKeyOf`. */
  lines?: Record<LineKey, LineState>
  longLines?: LongLines
  disabled?: boolean
  /** The ElevenLabs rate, for the cost line; unknown = no cost shown. */
  usdPerChar?: number | null
  /** The take playing in the video right now, if any. */
  playing?: string | null
  readouts?: FitReadout[]
  onSeek: (statement: Statement) => void
  onHear: (key: LineKey, request: LineRequest) => void
  onKeep: (key: LineKey, candidate: Candidate) => void
  onAnother: (key: LineKey) => void
  onAnswer: (key: LineKey, option: QuestionOption) => void
  onUndo: (editId: string) => void
  onRemove: (statement: Statement) => void
  onPlayTake: (candidate: Candidate) => void
  onDismiss: (key: LineKey) => void
  /** A take dragged to a new start; the moved take replaces it under the line. */
  onMove?: (key: LineKey, candidate: Candidate, start: number) => void
  /** A kept line dragged to a new start. */
  onMoveKept?: (editId: string, start: number) => void
  /** While a take or kept line is being placed: its start, for the bar. */
  placing?: { id: string; start: number; duration: number } | null
  onPlacing?: (placing: { id: string; start: number; duration: number } | null) => void
  onReword?: (statement: Statement, draft: string) => Promise<string[]>
  onLongLinesChange?: (value: LongLines) => void
  onEditingChange?: (statement: Statement | null) => void
}

const overlaps = (a: { start: number; end: number }, b: { start: number; end: number }) =>
  a.start < b.end && b.start < a.end

const STATUS: Record<string, string> = {
  reading: 'Reading', planned: 'Planned', working: 'Voicing…', ready: 'Ready to hear', 'needs-you': 'Needs you', failed: "Couldn't voice it",
}
const TONE: Record<string, string> = {
  reading: 'amber', planned: 'muted', working: 'muted', ready: 'amber', 'needs-you': 'rose', failed: 'rose', kept: 'ok', removed: 'muted',
}
const DELIVERIES = ['warmer', 'more excited', 'calmer', 'slower', 'firmer']
const LONG_OPTIONS: { value: LongLines; label: string }[] = [
  { value: 'pause', label: 'Let Voltage fit it' },
  { value: 'shorten', label: 'Prefer a shorter wording' },
  { value: 'stretch', label: 'Speed it up' },
  { value: 'ask', label: 'Ask me' },
]
const MIX_NOTE: Record<string, string | null> = {
  replace: null, layer: 'plays over the picture', over: 'plays over the picture', concatenate: 'the picture holds while it plays', remove: null,
}
const voiceLabel = (v: Voice) => (v.gender ? `${v.name} (${v.gender})` : v.name)

const Spinner = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className={styles.spin}>
    <circle cx="8" cy="8" r="7.25" fill="none" stroke="var(--line)" strokeWidth="1.5" />
    <path d="M8 0.75a7.25 7.25 0 0 1 7.25 7.25" fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
)
const PlayIcon = () => <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true"><path d="M1 1l8 5-8 5z" fill="currentColor" /></svg>

/** The transcript as the working surface: every line carries its own state,
 *  actions, editor and takes. Nothing about a line happens anywhere else. */
export function LineDoc({
  statements, words = [], speakers = [], voices = [], revisions = [], selection, currentTime,
  pendingLines = [], lines = {}, longLines = 'pause', disabled, usdPerChar, playing, readouts = [],
  onSeek, onHear, onKeep, onAnother, onAnswer, onUndo, onRemove, onPlayTake, onDismiss, onReword,
  onLongLinesChange, onEditingChange, onMove, onMoveKept, placing, onPlacing,
}: LineDocProps) {
  const [at, setAt] = useState<string>('')          // the add editor's "starts at", as typed
  const [placeText, setPlaceText] = useState('')     // the placing control's time, as typed
  const [editing, setEditing] = useState<{ index: number; mode: 'edit' | 'add' } | null>(null)
  const [draft, setDraft] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [onLong, setOnLong] = useState<LongLines>(longLines)
  const [delivery, setDelivery] = useState<string | null>(null)
  const [ownWords, setOwnWords] = useState<string | null>(null)
  const [mix, setMix] = useState<'over' | 'concatenate'>('over')
  const [asking, setAsking] = useState(false)
  const [offers, setOffers] = useState<string[]>([])
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { box.current?.focus() }, [editing])
  useEffect(() => {
    onEditingChange?.(editing && editing.mode === 'edit' ? statements[editing.index] : null)
  }, [editing, statements, onEditingChange])

  if (statements.length === 0) {
    return <p className={styles.empty}>No lines to show. This video has no transcribed speech.</p>
  }

  const name = (label?: string | null) => {
    const sp = speakers.find((s) => s.label === label)
    return sp?.name ?? (label ? `Speaker ${label}` : null)
  }

  /** The line as it stands now: the kept wording, or the original. */
  const standing = (s: Statement): string => {
    const live = revisions.filter((r) => overlaps(r, s))
    const revision = live.length ? live[live.length - 1] : null
    return revision && revision.mix !== 'remove' ? lineAfter(s, revision, words) : s.text
  }

  /** Where to start editing from: the last wording tried on this line (a take
   *  waiting, a question, an error), else the line as it stands. Never the
   *  original when you have already moved past it. */
  const startingPoint = (s: Statement) => {
    const last = lines[keyOf({ start: s.start, end: s.end })]?.request
    return last && last.mix === 'replace' ? last : null
  }

  const open = (index: number, mode: 'edit' | 'add', focusDelivery = false) => {
    const s = statements[index]
    const last = mode === 'edit' ? startingPoint(s) : lines[addKeyOf(s)]?.request ?? null
    setEditing({ index, mode })
    setDraft(mode === 'edit' ? (last?.text ?? standing(s)) : (last?.text ?? ''))
    setOffers([])
    setVoiceId(last?.voiceId ?? speakers.find((sp) => sp.label === s.speaker)?.voice_id ?? '')
    setOnLong(last?.onLong ?? longLines)
    const known = last?.delivery && DELIVERIES.includes(last.delivery) ? last.delivery : null
    setDelivery(known)
    setOwnWords(focusDelivery && !last?.delivery ? '' : last?.delivery && !known ? last.delivery : null)
    setMix(last?.mix === 'concatenate' ? 'concatenate' : 'over')
    setAt(last?.at != null ? timecode(last.at) : '')
  }
  const close = () => setEditing(null)
  const hear = (s: Statement) => {
    const text = draft.trim()
    if (!editing || !text || (editing.mode === 'edit' && text === standing(s))) return
    const key = editing.mode === 'edit' ? keyOf(s) : addKeyOf(s)
    const chosen = editing.mode === 'add' && at.trim() ? parseTime(at) : null
    onHear(key, {
      selection: { start: s.start, end: s.end }, text, voiceId: voiceId || null, onLong,
      delivery: (ownWords?.trim() || delivery) ?? null, mix: editing.mode === 'edit' ? 'replace' : mix,
      ...(chosen !== null ? { at: chosen } : {}),
    })
    close()
  }
  const ask = async (s: Statement) => {
    if (!onReword) return
    setAsking(true)
    try {
      const texts = await onReword(s, draft.trim())
      if (texts.length === 1) setDraft(texts[0])
      else setOffers(texts)
    } finally {
      setAsking(false)
    }
  }
  const chooseLong = (v: LongLines) => { setOnLong(v); onLongLinesChange?.(v) }

  const editor = (s: Statement, mode: 'edit' | 'add') => {
    const chars = draft.trim().length
    const cost = usdPerChar ? ` · about ${Math.max(1, Math.round(chars * usdPerChar * 100))}¢` : ''
    const base = mode === 'edit' ? standing(s) : ''
    const preview = mode === 'edit' && draft.trim() && draft.trim() !== base
      ? diffWords(base, draft.trim()) : null
    return (
      <div className={styles.editor} data-testid="editor">
        <textarea
          ref={box}
          className={styles.box}
          value={draft}
          rows={2}
          aria-label={mode === 'edit' ? 'New wording' : 'Words for the new line'}
          placeholder={mode === 'add' ? 'What should be said here?' : undefined}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); hear(s) }
            if (e.key === 'Escape') close()
          }}
        />
        {preview && (
          <div className={styles.changing}>
            You'd be changing:{' '}
            {preview.map((run, k) => (
              <Fragment key={k}>{k > 0 && ' '}
                {run.kind === 'same' ? <span>{run.text}</span> : run.kind === 'del' ? <del className={styles.del}>{run.text}</del> : <ins className={styles.ins}>{run.text}</ins>}
              </Fragment>
            ))}
          </div>
        )}
        <div className={styles.control}>
          <span className={styles.controlLabel}>Delivery</span>
          <button type="button" className={delivery === null && ownWords === null ? styles.pillOn : styles.pill} onClick={() => { setDelivery(null); setOwnWords(null) }}>As spoken</button>
          {DELIVERIES.map((d) => (
            <button key={d} type="button" className={delivery === d ? styles.pillOn : styles.pill} onClick={() => { setDelivery(d); setOwnWords(null) }}>
              {d.charAt(0).toUpperCase() + d.slice(1)}
            </button>
          ))}
          {ownWords === null
            ? <button type="button" className={styles.link} onClick={() => { setOwnWords(''); setDelivery(null) }}>in your words…</button>
            : <input className={styles.ownWords} aria-label="Delivery, in your words" placeholder="e.g. like a secret" value={ownWords} onChange={(e) => setOwnWords(e.target.value)} />}
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
        {mode === 'add' && (
          <div className={styles.control}>
            <span className={styles.controlLabel}>Starts at</span>
            <input className={styles.ownWords} aria-label="Starts at" placeholder={`after this line (${timecode(s.end)})`} value={at} onChange={(e) => setAt(e.target.value)} />
            <span className={styles.faint}>{at.trim() && parseTime(at) === null ? 'A time like 0:04.96' : 'Leave it empty to follow this line; or any time, like 0:04.96'}</span>
          </div>
        )}
        {mode === 'add' && (
          <div className={styles.control} role="group" aria-label="Sound meets picture">
            <span className={styles.controlLabel}>Sound meets picture</span>
            <button type="button" className={mix === 'over' ? styles.pillOn : styles.pill} aria-pressed={mix === 'over'} onClick={() => setMix('over')}>Over the picture</button>
            <button type="button" className={mix === 'concatenate' ? styles.pillOn : styles.pill} aria-pressed={mix === 'concatenate'} onClick={() => setMix('concatenate')}>Hold the picture</button>
            <span className={styles.faint}>{mix === 'over' ? 'The picture keeps moving under the line.' : 'The picture waits while the line plays.'}</span>
          </div>
        )}
        <div className={styles.control}>
          <span className={styles.controlLabel}>If it runs long</span>
          <select aria-label="If it runs long" value={onLong} onChange={(e) => chooseLong(e.target.value as LongLines)}>
            {LONG_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div className={styles.editorFoot}>
          <span className={styles.faint}>≈ {chars} characters{cost} · ready in about 10 s</span>
          <span className={styles.spacer} />
          {onReword && mode === 'edit' && (
            <button type="button" className={styles.link} disabled={asking} onClick={() => void ask(s)}>
              {asking ? 'Asking Voltage…' : 'Ask Voltage for wording'}
            </button>
          )}
          <button type="button" className={styles.secondary} onClick={close}>Cancel</button>
          <button
            type="button"
            className={styles.primary}
            aria-label="Hear it"
            disabled={disabled || !draft.trim() || (mode === 'edit' && draft.trim() === base)}
            onClick={() => hear(s)}
          >
            Hear it
          </button>
        </div>
        {offers.length > 0 && (
          <div className={styles.offers} data-testid="offers">
            <span className={styles.faint}>Tighter wordings that fit the gap as it is</span>
            {offers.map((o) => <button key={o} type="button" className={styles.offer} onClick={() => { setDraft(o); setOffers([]) }}>{o}</button>)}
          </div>
        )}
        {(() => {
          const r = readouts.find((x) => overlaps(x.selection, s))
          return r && r.tags.length > 0 ? (
            <div className={styles.readout} data-testid="readout">
              <span>Last take fit by:</span>{r.tags.map((t) => <span key={t} className={styles.fitTag}>{t}</span>)}
            </div>
          ) : null
        })()}
      </div>
    )
  }

  /** "Starts at 0:04.96 · Move": opens a control to drag it on the bar or type a time. */
  const placeControl = (id: string, start: number, duration: number, apply: (start: number) => void) => {
    const open = placing?.id === id
    const current = open ? placing!.start : start
    return (
      <div className={styles.place} data-testid="place">
        {!open ? (
          <>
            <span className={styles.faint}>Starts at {timecode(start)}</span>
            {onPlacing && <button type="button" className={styles.link} onClick={() => { onPlacing({ id, start, duration }); setPlaceText(timecode(start)) }}>Move</button>}
          </>
        ) : (
          <>
            <span className={styles.faint}>Drag it on the bar above, or type a time:</span>
            <input
              className={styles.ownWords}
              aria-label="Starts at"
              value={placeText}
              onChange={(e) => { setPlaceText(e.target.value); const t = parseTime(e.target.value); if (t !== null) onPlacing?.({ id, start: t, duration }) }}
              onKeyDown={(e) => { if (e.key === 'Enter') { apply(current); onPlacing?.(null) } if (e.key === 'Escape') onPlacing?.(null) }}
            />
            <button type="button" className={styles.secondary} aria-label="Nudge earlier" onClick={() => { const t = Math.round(Math.max(0, current - 0.1) * 100) / 100; onPlacing?.({ id, start: t, duration }); setPlaceText(timecode(t)) }}>◀</button>
            <button type="button" className={styles.secondary} aria-label="Nudge later" onClick={() => { const t = Math.round((current + 0.1) * 100) / 100; onPlacing?.({ id, start: t, duration }); setPlaceText(timecode(t)) }}>▶</button>
            <button type="button" className={styles.primary} onClick={() => { apply(current); onPlacing?.(null) }} disabled={disabled}>Put it here</button>
            <button type="button" className={styles.ghost} onClick={() => onPlacing?.(null)}>Cancel</button>
          </>
        )}
      </div>
    )
  }

  const takeCard = (key: LineKey, c: Candidate, s: Statement, n: number, total: number, state: LineState) => {
    const v = verdict(c, name(s.speaker))
    const voice = voices.find((x) => x.voice_id === c.plan.voice_profile_id)?.name
    const held = state.request?.mix === 'over' && c.plan.mix === 'concatenate'
    return (
      <div key={c.candidate_id} className={styles.take} data-testid="take" data-chosen={total > 1 && n === total ? 'true' : undefined}>
        <div className={styles.takeHead}>
          <button className={styles.play} aria-label={`Play take ${n} in the video`} aria-pressed={playing === c.candidate_id} onClick={() => onPlayTake(c)}><PlayIcon /></button>
          <span className={styles.takeLabel}>Take {n}{voice ? ` · ${voice}'s voice` : ''}</span>
          <span className={styles.spacer} />
          {v.score !== null && <span className={styles.score}>{v.score.toFixed(2)}</span>}
        </div>
        <div className={styles.verdict}>{v.text}{held ? ' Held the picture: no room to play over it.' : ''}</div>
        {onMove && placeControl(c.candidate_id, c.plan.selection.start, c.audio.duration, (t) => onMove(key, c, t))}
        {total === 1 && (
          <div className={styles.takeButtons}>
            <button className={styles.primary} onClick={() => onKeep(key, c)} disabled={disabled}>Keep</button>
            <button className={styles.secondary} onClick={() => onAnother(key)} disabled={disabled}>Another take</button>
          </div>
        )}
      </div>
    )
  }

  const lineBlock = (key: LineKey, s: Statement, index: number) => {
    const state = lines[key]
    if (!state) return null
    if (state.status === 'working') {
      return <div className={styles.working} data-testid="line-working"><Spinner /><span>{state.progress ?? 'Voicing the line…'}</span></div>
    }
    if (state.status === 'failed') {
      return (
        <div className={styles.failed} data-testid="line-error">
          <span className={styles.spacer}>{state.error ?? "Couldn't voice it."}</span>
          {state.request && <button className={styles.secondary} onClick={() => onHear(key, state.request!)} disabled={disabled}>Try again</button>}
          <button className={styles.ghost} onClick={() => onDismiss(key)}>Dismiss</button>
        </div>
      )
    }
    if (state.status === 'needs-you' && state.question) {
      const q = state.question
      return (
        <div className={styles.needs} data-testid="line-needs-you">
          <div>{q.question}</div>
          <div className={styles.options}>
            {q.options.map((o, k) => (
              <button key={k} className={k === 0 ? styles.primary : styles.secondary} onClick={() => onAnswer(key, o)} disabled={disabled}>
                {o.label}{o.warning && <span className={styles.warning}> {o.warning}</span>}
              </button>
            ))}
            <button className={styles.ghost} onClick={() => { onDismiss(key); open(index, 'edit') }}>Change the words instead</button>
          </div>
        </div>
      )
    }
    const takes = state.takes.slice(-2)
    const total = state.takes.length
    return (
      <div className={styles.takes}>
        <div className={takes.length > 1 ? styles.twoTakes : undefined}>
          {takes.map((c, i) => takeCard(key, c, s, total - takes.length + i + 1, total, state))}
        </div>
        {takes.length > 1 && (
          <div className={styles.takeButtons}>
            {takes.map((c, i) => (
              <button key={c.candidate_id} className={i === takes.length - 1 ? styles.primary : styles.secondary} onClick={() => onKeep(key, c)} disabled={disabled}>
                Keep take {total - takes.length + i + 1}
              </button>
            ))}
            <button className={styles.secondary} onClick={() => onAnother(key)} disabled={disabled}>Another take</button>
            <button className={styles.ghost} onClick={() => { onDismiss(key); open(index, 'edit') }}>Neither — change the words</button>
          </div>
        )}
      </div>
    )
  }

  return (
    <section className={styles.doc} aria-label="Transcript">
      <div className={styles.heading}>
        <span className={styles.title}>Transcript</span>
        <span className={styles.hint}>
          {editing ? (editing.mode === 'edit' ? `Editing ${clock(statements[editing.index].start)}. Enter to hear it, Esc to cancel.` : `Adding a line after ${clock(statements[editing.index].start)}.`)
            : pendingLines.some((p) => p.status === 'reading') ? "Voltage is reading. The line it's on is lit."
            : 'Each line carries its own state. Hover a line for what you can do to it.'}
        </span>
      </div>

      {statements.map((s, i) => {
        const key = keyOf({ start: s.start, end: s.end })
        const addKey = addKeyOf(s)
        const current = currentTime >= s.start && currentTime < s.end
        const selected = !!selection && overlaps(selection, s)
        const pending = pendingLines.find((p) => overlaps(p.selection, s) && STATUS[p.status])
        const live = revisions.filter((r) => overlaps(r, s))
        const revision = live.length ? live[live.length - 1] : null
        const removed = revision?.mix === 'remove'
        const shown: Revision | null = pending?.text
          ? { start: pending.selection.start, end: pending.selection.end, text: pending.text, mix: pending.mix ?? 'replace' }
          : revision && !removed ? revision : null
        const state = lines[key]
        const status: string | null = state?.status ?? pending?.status ?? (removed ? 'removed' : revision ? 'kept' : null)
        const label = name(s.speaker)
        const newSpeaker = !!label && s.speaker !== statements[i - 1]?.speaker
        const isEditing = editing?.index === i && editing.mode === 'edit'
        const isAdding = editing?.index === i && editing.mode === 'add'
        const added = lines[addKey]
        return (
          <Fragment key={`${s.start}-${i}`}>
            <div id={`line-${i}`} className={styles.row} data-current={current} data-selected={selected} data-state={status ?? undefined}>
              <button className={styles.time} onClick={() => onSeek(s)} aria-label={`Go to ${clock(s.start)}`}>{clock(s.start)}</button>
              <span className={styles.who}>{newSpeaker && label && <Avatar name={label} slot={speakerSlot(speakers, s.speaker)} />}</span>
              <div className={styles.body}>
                {isEditing ? editor(s, 'edit') : (
                  <div className={styles.lineWrap}>
                    <button className={styles.line} onClick={() => open(i, 'edit')} title="Change the words" data-testid={shown ? 'revision' : undefined}>
                      {removed ? <del className={styles.del}>{s.text}</del>
                        : shown ? trackedChanges(s, shown, words).map((run, k) => (
                          <Fragment key={k}>{k > 0 && ' '}
                            {run.kind === 'same' ? <span>{run.text}</span> : run.kind === 'del' ? <del className={styles.del}>{run.text}</del> : <ins className={styles.ins}>{run.text}</ins>}
                          </Fragment>
                        )) : s.text}
                    </button>
                    {(revision || removed) && (
                      <div className={styles.meta}>
                        {removed ? "Removed. The gap is closed with the room's own sound; the picture is untouched." : `Kept${shown && MIX_NOTE[shown.mix] ? ` · ${MIX_NOTE[shown.mix]}` : ''}.`}
                        {revision?.edit_id && <> <button className={styles.undo} onClick={() => onUndo(revision.edit_id!)}>Undo</button></>}
                      </div>
                    )}
                    {revision && !removed && revision.edit_id && onMoveKept && (
                      placeControl(`edit-${revision.edit_id}`, revision.start, Math.max(0.05, revision.end - revision.start), (t) => onMoveKept(revision.edit_id!, t))
                    )}
                    {pending && !revision && pending.text && MIX_NOTE[pending.mix ?? 'replace'] && (
                      <div className={styles.meta}>Added · {MIX_NOTE[pending.mix ?? 'replace']}</div>
                    )}
                    {!isEditing && lineBlock(key, s, i)}
                  </div>
                )}
              </div>
              <span className={styles.side}>
                {status && STATUS[status] && <span className={styles.chip} data-tone={TONE[status]}>{STATUS[status]}</span>}
                {status === 'kept' && <span className={styles.chip} data-tone="ok">Kept</span>}
                {status === 'removed' && <span className={styles.chip} data-tone="muted">Removed</span>}
                {!isEditing && !isAdding && (
                  <span className={styles.actions} role="group" aria-label={`Actions for ${clock(s.start)}`}>
                    <button className={styles.action} onClick={() => open(i, 'edit')}>Change the words</button>
                    <button className={styles.action} onClick={() => open(i, 'edit', true)}>Change the delivery</button>
                    <button className={styles.action} onClick={() => open(i, 'add')}>Add a line after</button>
                    {!removed && <button className={styles.action} onClick={() => onRemove(s)}>Remove</button>}
                    <button className={styles.action} onClick={() => onSeek(s)}>Play original</button>
                  </span>
                )}
              </span>
            </div>
            {isAdding && (
              <div className={styles.row} data-state="adding">
                <span className={styles.time} />
                <span className={styles.who} />
                <div className={styles.body}>{editor(s, 'add')}</div>
              </div>
            )}
            {added && !isAdding && (
              <div className={styles.row} data-state={added.status}>
                <span className={styles.time}>{clock(s.end)}</span>
                <span className={styles.who} />
                <div className={styles.body}>
                  <div className={styles.meta}>New line after {clock(s.start)}{added.request ? ` · ${added.request.mix === 'over' ? 'plays over the picture' : 'the picture holds'}` : ''}</div>
                  {lineBlock(addKey, s, i)}
                </div>
                <span className={styles.side}>{STATUS[added.status] && <span className={styles.chip} data-tone={TONE[added.status]}>{STATUS[added.status]}</span>}</span>
              </div>
            )}
            {!isAdding && !added && i === statements.length - 1 && (
              <div className={styles.addRow}>
                <button className={styles.add} onClick={() => open(i, 'add')}><span aria-hidden="true">+</span> Add a line here</button>
              </div>
            )}
          </Fragment>
        )
      })}
    </section>
  )
}
