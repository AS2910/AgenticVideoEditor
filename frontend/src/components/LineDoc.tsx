import { Fragment, useEffect, useRef, useState } from 'react'
import type React from 'react'
import type { ReactNode } from 'react'
import type {
  Candidate, ItemStatus, LineStatus, LongLines, Mix, Question, QuestionOption, Revision, Selection, Speaker, Statement, Voice, Word,
} from '../types'
import { diffWords, lineAfter, trackedChanges } from '../transcript/changes'
import { clock } from '../transcript/format'
import { speakerSlot } from '../transcript/speakers'
import { verdict } from '../transcript/verdict'
import { parseTime, timecode } from '../transcript/time'
import { Avatar } from './Avatar'
import { PlaceEditor } from './PlaceEditor'
import { GripVertical, Loader2, Play } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { Chip, ControlRow, LinkButton } from './EditorControls'
import { editorClass, riseClass, selectClass } from './editorStyles'

import { addKeyOf, keyOf } from '../transcript/keys'
import type { LineKey } from '../transcript/keys'

/** What was asked for a line, so Another take asks the same again. */
export interface LineRequest {
  selection: Selection
  text: string
  voiceId: string | null
  onLong: LongLines
  delivery: string | null
  mix: 'replace' | 'over' | 'concatenate' | 'layer'
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
  onKeep: (key: LineKey, candidate: Candidate) => void | Promise<unknown>
  onAnother: (key: LineKey) => void | Promise<unknown>
  onAnswer: (key: LineKey, option: QuestionOption) => void | Promise<unknown>
  onUndo: (editId: string) => void
  onRemove: (statement: Statement) => void
  /** UX-1c: move this line of the original speech to start at `to`. */
  onShift?: (s: Statement, to: number) => void
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
  /** UX-5: the clip's length, so a voice-over can be placed on a clip with no speech. */
  duration?: number
  /** UX-7d: review is the script filtered to what changed — a segmented control in the heading. */
  filter?: { count: number; on: boolean; onChange: (on: boolean) => void }
  /** The review rows, shown in place of the lines while the filter is on. */
  review?: ReactNode
}

const overlaps = (a: { start: number; end: number }, b: { start: number; end: number }) =>
  a.start < b.end && b.start < a.end

const STATUS: Record<string, string> = {
  reading: 'Reading', planned: 'Planned', working: 'Voicing…', ready: 'Ready to hear', 'needs-you': 'Needs you', failed: "Couldn't voice it",
}
/** A row's state is a quiet badge, tinted only where it means something: changed, needs you, kept. */
const TONE: Record<string, string> = {
  reading: 'bg-changed-soft text-changed', planned: 'bg-secondary text-muted-foreground', working: 'bg-secondary text-muted-foreground',
  ready: 'bg-changed-soft text-changed', 'needs-you': 'bg-needs-soft text-needs', failed: 'bg-needs-soft text-needs',
  kept: 'bg-ok-soft text-ok', removed: 'bg-secondary text-muted-foreground',
}
const INS = 'rounded-sm bg-changed-soft px-1 text-changed no-underline'
const DEL = 'text-muted-foreground line-through decoration-needs decoration-[1.5px]'
const hint = 'text-sm text-muted-foreground'
const faint = 'text-sm text-muted-foreground'
const actionBtn = 'whitespace-nowrap'
const rowClass = [
  'group/row relative grid min-h-11 grid-cols-[24px_44px_24px_minmax(0,1fr)_auto] items-start gap-x-3 rounded-lg border-l-2 border-transparent py-2 pl-1.5 pr-2.5 outline-none transition-colors',
  'max-[960px]:grid-cols-[24px_44px_24px_minmax(0,1fr)] max-[960px]:gap-y-1.5',
  'focus-visible:bg-muted/50 focus-visible:ring-[3px] focus-visible:ring-ring/50',
  'data-[selected=true]:border-l-primary data-[selected=true]:bg-muted/50',
  'data-[state=reading]:bg-changed-soft data-[state=ready]:border-l-changed data-[state=needs-you]:border-l-needs data-[state=failed]:border-l-needs',
  'data-[state=kept]:border-l-ok data-[state=moved]:border-l-ok data-[state=removed]:border-l-border data-[state=adding]:bg-muted/50',
  'data-[dragging]:opacity-50',
].join(' ')
const timeClass = 'tnum -my-2.5 flex min-h-11 items-center rounded-md text-left text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 group-data-[current=true]/row:font-semibold group-data-[current=true]/row:text-foreground'
const gripClass = [
  'relative -my-2.5 inline-flex h-11 w-6 cursor-grab touch-none select-none items-center justify-center rounded-md border border-transparent p-0 text-muted-foreground opacity-60 outline-none transition-opacity',
  'before:absolute before:inset-y-0 before:-inset-x-2.5 hover:bg-accent hover:text-foreground focus-visible:opacity-100 focus-visible:ring-[3px] focus-visible:ring-ring/50 active:cursor-grabbing',
  'group-hover/row:opacity-100 group-focus-within/row:opacity-100 max-[960px]:opacity-100',
].join(' ')
const lineClass = 'block min-h-0 w-full cursor-pointer rounded-sm p-0 text-left text-base leading-normal text-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50'
const sideClass = 'flex min-h-[22px] flex-col items-end gap-1.5 empty:hidden max-[960px]:col-start-4 max-[960px]:flex-row max-[960px]:flex-wrap max-[960px]:items-center max-[960px]:justify-start'
const metaClass = 'text-sm text-muted-foreground'
const unfold = 'grid grid-rows-[1fr] empty:hidden *:min-h-0 ' + riseClass
const kbd = 'mx-px inline-block min-w-[18px] rounded-sm border border-b-2 bg-muted px-1 text-center text-xs text-muted-foreground'
const actionsClass = [
  'absolute right-2.5 top-1.5 z-10 flex flex-wrap justify-end gap-1 rounded-lg border bg-popover p-1 shadow-md transition-opacity',
  '[clip-path:inset(0_0_0_100%)] opacity-0 group-hover/row:opacity-100 group-hover/row:[clip-path:inset(0)] group-focus-within/row:opacity-100 group-focus-within/row:[clip-path:inset(0)] group-data-[actions-open]/row:opacity-100 group-data-[actions-open]/row:[clip-path:inset(0)]',
  // No hover: the actions live under the line, opened by the "…" button.
  '[@media(hover:none)]:static [@media(hover:none)]:hidden [@media(hover:none)]:justify-start [@media(hover:none)]:border-0 [@media(hover:none)]:bg-transparent [@media(hover:none)]:p-0 [@media(hover:none)]:shadow-none [@media(hover:none)]:opacity-100 [@media(hover:none)]:[clip-path:none] group-data-[actions-open]/row:[@media(hover:none)]:flex',
].join(' ')
const StatusBadge = ({ status, children, role }: { status: string; children: ReactNode; role?: 'status' }) => (
  <Badge variant="secondary" className={cn('px-2.5', TONE[status])} role={role}>{children}</Badge>
)
const DELIVERIES = ['warmer', 'more excited', 'calmer', 'slower', 'firmer']
const LONG_OPTIONS: { value: LongLines; label: string }[] = [
  { value: 'pause', label: 'Let Voltage fit it' },
  { value: 'shorten', label: 'Prefer a shorter wording' },
  { value: 'stretch', label: 'Speed it up' },
  { value: 'ask', label: 'Ask me' },
]
const MIX_NOTE: Record<string, string | null> = {
  replace: null, layer: 'plays over the picture', over: 'plays over the picture', concatenate: 'the picture makes room while it plays', remove: null,
}
const voiceLabel = (v: Voice) => (v.gender ? `${v.name} (${v.gender})` : v.name)

const Spinner = () => <Loader2 size={16} aria-hidden="true" className="shrink-0 animate-spin text-changed" />
const PlayIcon = () => <Play size={14} aria-hidden="true" fill="currentColor" />

/** The transcript as the working surface: every line carries its own state,
 *  actions, editor and takes. Nothing about a line happens anywhere else. */
export function LineDoc({
  statements, words = [], speakers = [], voices = [], revisions = [], selection, currentTime, filter, review,
  pendingLines = [], lines = {}, longLines = 'pause', disabled, usdPerChar, playing, readouts = [],
  onSeek, onHear, onKeep, onAnother, onAnswer, onUndo, onRemove, onPlayTake, onDismiss, onReword,
  onLongLinesChange, onEditingChange, onMove, onMoveKept, placing, onPlacing, onShift, duration,
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
  // A row has keyboard focus: the heading shows the keys.
  const [focusedRow, setFocusedRow] = useState<number | null>(null)
  // On a touch screen the row's actions open from a "…" button (UX-6).
  const [actionsOpen, setActionsOpen] = useState<number | null>(null)
  // Backspace removes a line only when pressed twice within two seconds; Delete removes at once.
  const armed = useRef<{ index: number; at: number } | null>(null)
  const [armedRow, setArmedRow] = useState<number | null>(null)
  // UX-5: another voice-over is being placed on a clip with no speech.
  const [placingAnother, setPlacingAnother] = useState(false)
  // The control whose request is on its way: it waits, and says so (UX-6).
  const [pending, setPending] = useState<string | null>(null)
  const run = async (id: string, fn: () => void | Promise<unknown>) => {
    setPending(id)
    try { await fn() } finally { setPending((p) => (p === id ? null : p)) }
  }
  // Roving focus (UX-6): Tab moves row to row; only the row that holds focus
  // exposes its own controls to Tab, so forty lines are forty stops, not 350.
  const list = useRef<HTMLDivElement>(null)
  const [focusTick, setFocusTick] = useState(0)
  useEffect(() => {
    const root = list.current
    if (!root) return
    const active = document.activeElement?.closest('[role="listitem"]') ?? null
    for (const row of Array.from(root.querySelectorAll<HTMLElement>('[role="listitem"]'))) {
      const own = row === active
      for (const el of Array.from(row.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href]'))) {
        if (el.tabIndex !== (own ? 0 : -1)) el.tabIndex = own ? 0 : -1
      }
    }
  })
  // A row being dragged up or down to shift it in time (UX-1c).
  const [drag, setDrag] = useState<{ key: string; label: string; duration: number; at: number; to: number; apply: (to: number) => void } | null>(null)
  const box = useRef<HTMLTextAreaElement>(null)
  // A grip drag that moved must not also count as a click on the grip.
  const dragged = useRef(false)

  useEffect(() => { box.current?.focus() }, [editing])
  // The row to put focus back on when its editor closes, so the keys keep working.
  const returnTo = useRef<number | null>(null)
  useEffect(() => {
    if (editing || returnTo.current === null) return
    document.getElementById(`line-${returnTo.current}`)?.focus()
    returnTo.current = null
  }, [editing])
  useEffect(() => {
    onEditingChange?.(editing && editing.mode === 'edit' ? statements[editing.index] : null)
  }, [editing, statements, onEditingChange])

  if (statements.length === 0) {
    // UX-5: nothing to read, so the first thing is where the voice-over goes.
    if (duration) {
      return (
        <section className="flex flex-col gap-0.5" aria-label="Transcript">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-2.5 pb-2 pt-1">
            <h2 className="m-0 text-base font-semibold">Voice-over</h2>
            <span className={hint}>No one speaks in this clip. Place a line where you want it, and say what it should say.</span>
          </div>
          <PlaceEditor
            duration={duration} voices={voices} usdPerChar={usdPerChar} longLines={longLines} disabled={disabled}
            placing={placing} onPlacing={onPlacing}
            onHear={(span, request) => onHear(keyOf(span), request)}
          />
        </section>
      )
    }
    return <p className="m-0 py-6 text-muted-foreground">No lines to show. This video has no transcribed speech.</p>
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
  const close = () => {
    if (editing) returnTo.current = editing.index
    setEditing(null)
  }

  /** Keys on a focused row (UX-4): ↑↓ move, Enter opens, Space plays, K
   *  keeps the latest take, U undoes, Delete removes. Only when the row
   *  itself has focus — never while typing in it. */
  const onRowKey = (e: React.KeyboardEvent<HTMLDivElement>, index: number) => {
    if (e.target !== e.currentTarget) return
    const s = statements[index]
    const move = (to: number) => {
      const row = document.getElementById(`line-${Math.max(0, Math.min(statements.length - 1, to))}`)
      row?.focus()
      row?.scrollIntoView?.({ block: 'nearest' })
    }
    switch (e.key) {
      case 'ArrowDown': case 'j': e.preventDefault(); move(index + 1); break
      case 'ArrowUp': e.preventDefault(); move(index - 1); break
      case 'Enter': e.preventDefault(); open(index, 'edit'); break
      case ' ': e.preventDefault(); onSeek(s); break
      case 'a': case 'A': e.preventDefault(); open(index, 'add'); break
      case 's': case 'S': {
        if (onShift && onPlacing && !revisions.some((r) => overlaps(r, s) && !(r.mix === 'layer' && r.partner))) {
          e.preventDefault()
          onPlacing({ id: `shift-${keyOf(s)}`, start: s.start, duration: Math.max(0.05, s.end - s.start) })
          setPlaceText(timecode(s.start))
        }
        break
      }
      case 'k': case 'K': {
        const state = lines[keyOf(s)]
        const latest = state?.takes[state.takes.length - 1]
        if (latest && state?.status === 'ready' && !disabled) { e.preventDefault(); onKeep(keyOf(s), latest) }
        break
      }
      case 'u': case 'U': {
        const live = revisions.filter((r) => overlaps(r, s))
        const revision = live.length ? live[live.length - 1] : null
        if (revision?.edit_id) { e.preventDefault(); onUndo(revision.edit_id) }
        break
      }
      case 'Delete': case 'Backspace': {
        const live = revisions.filter((r) => overlaps(r, s))
        if (live.some((r) => r.mix === 'remove') || disabled) break
        e.preventDefault()
        const now = Date.now()
        if (e.key === 'Backspace' && !(armed.current && armed.current.index === index && now - armed.current.at < 2000)) {
          armed.current = { index, at: now }
          setArmedRow(index)
          window.setTimeout(() => { if (armed.current && armed.current.at === now) { armed.current = null; setArmedRow(null) } }, 2000)
          break
        }
        armed.current = null
        setArmedRow(null)
        onRemove(s)
        break
      }
      default: break
    }
  }
  const hear = (s: Statement) => {
    const text = draft.trim()
    if (!editing || !text || (editing.mode === 'edit' && text === standing(s) && !s.placed)) return
    const key = editing.mode === 'edit' ? keyOf(s) : addKeyOf(s)
    const chosen = editing.mode === 'add' && at.trim() ? parseTime(at) : null
    if (editing.mode === 'add' && at.trim() && chosen === null) return   // an unreadable time is never dropped silently
    onHear(key, {
      selection: { start: s.start, end: s.end }, text, voiceId: voiceId || null, onLong,
      delivery: (ownWords?.trim() || delivery) ?? null, mix: editing.mode === 'edit' ? (s.placed ? 'layer' : 'replace') : mix,
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
    const badAt = mode === 'add' && at.trim() !== '' && parseTime(at) === null
    const preview = mode === 'edit' && draft.trim() && draft.trim() !== base
      ? diffWords(base, draft.trim()) : null
    return (
      <div className={editorClass} data-testid="editor">
        <Textarea
          ref={box}
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
          <div className="text-sm leading-normal text-muted-foreground">
            You'd be changing:{' '}
            {preview.map((run, k) => (
              <Fragment key={k}>{k > 0 && ' '}
                {run.kind === 'same' ? <span>{run.text}</span> : run.kind === 'del' ? <del className={DEL}>{run.text}</del> : <ins className={INS}>{run.text}</ins>}
              </Fragment>
            ))}
          </div>
        )}
        <ControlRow label="Delivery">
          <Chip on={delivery === null && ownWords === null} onClick={() => { setDelivery(null); setOwnWords(null) }}>As spoken</Chip>
          {DELIVERIES.map((d) => (
            <Chip key={d} on={delivery === d} onClick={() => { setDelivery(d); setOwnWords(null) }}>
              {d.charAt(0).toUpperCase() + d.slice(1)}
            </Chip>
          ))}
          {ownWords === null
            ? <LinkButton onClick={() => { setOwnWords(''); setDelivery(null) }}>in your words…</LinkButton>
            : <Input className="w-48" aria-label="Delivery, in your words" placeholder="e.g. like a secret" value={ownWords} onChange={(e) => setOwnWords(e.target.value)} />}
        </ControlRow>
        {voices.length > 0 && (
          <ControlRow label="Voice">
            <select className={selectClass} aria-label="Voice" value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
              <option value="">Default voice</option>
              {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{voiceLabel(v)}</option>)}
            </select>
          </ControlRow>
        )}
        {mode === 'add' && (
          <ControlRow label="Starts at">
            <Input className="w-56" aria-label="Starts at" aria-invalid={badAt || undefined} aria-describedby="starts-at-help" placeholder={`after this line (${timecode(s.end)})`} value={at} onChange={(e) => setAt(e.target.value)} />
            <span id="starts-at-help" className={badAt ? 'text-destructive' : undefined} role={badAt ? 'alert' : undefined}>{badAt ? 'A time like 0:04.96, or leave it empty to follow this line.' : 'Leave it empty to follow this line; or any time, like 0:04.96'}</span>
          </ControlRow>
        )}
        {mode === 'add' && (
          <ControlRow label="Sound meets picture" role="group" aria-label="Sound meets picture">
            <Chip on={mix === 'over'} onClick={() => setMix('over')}>Over the picture</Chip>
            <Chip on={mix === 'concatenate'} onClick={() => setMix('concatenate')}>Hold the picture</Chip>
            <span>{mix === 'over' ? 'The picture keeps moving under the line.' : 'The picture waits while the line plays.'}</span>
          </ControlRow>
        )}
        <ControlRow label="If it runs long">
          <select className={selectClass} aria-label="If it runs long" value={onLong} onChange={(e) => chooseLong(e.target.value as LongLines)}>
            {LONG_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </ControlRow>
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <span className={cn(faint, 'tnum')}>≈ {chars} characters{cost} · ready in about 10 s</span>
          <span className="flex-1" />
          {onReword && mode === 'edit' && (
            <LinkButton disabled={asking} onClick={() => void ask(s)}>
              {asking ? 'Asking Voltage…' : 'Ask Voltage for wording'}
            </LinkButton>
          )}
          <Button type="button" variant="outline" onClick={close}>Cancel</Button>
          <Button
            type="button"
            aria-label="Hear it"
            disabled={disabled || !draft.trim() || badAt || (mode === 'edit' && draft.trim() === base)}
            onClick={() => hear(s)}
          >
            Hear it
          </Button>
        </div>
        {offers.length > 0 && (
          <div className="flex flex-col gap-1.5 border-t pt-3" data-testid="offers">
            <span className={faint}>Tighter wordings that fit the gap as it is</span>
            {offers.map((o) => <Button key={o} type="button" variant="outline" className="h-auto justify-start whitespace-normal py-2 text-left" onClick={() => { setDraft(o); setOffers([]) }}>{o}</Button>)}
          </div>
        )}
        {(() => {
          const r = readouts.find((x) => overlaps(x.selection, s))
          return r && r.tags.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 border-t pt-3 text-sm text-muted-foreground" data-testid="readout">
              <span>Last take fit by:</span>{r.tags.map((t) => <Badge key={t} variant="secondary" className="bg-ok-soft px-2.5 text-ok">{t}</Badge>)}
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
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid="place">
        {!open ? (
          <>
            <span className="tnum">Starts at {timecode(start)}</span>
            {onPlacing && <LinkButton onClick={() => { onPlacing({ id, start, duration }); setPlaceText(timecode(start)) }}>Move</LinkButton>}
          </>
        ) : (
          <>
            <span>Drag it on the bar above, or type a time:</span>
            <Input
              className="tnum w-32"
              aria-label="Starts at"
              value={placeText}
              onChange={(e) => { setPlaceText(e.target.value); const t = parseTime(e.target.value); if (t !== null) onPlacing?.({ id, start: t, duration }) }}
              onKeyDown={(e) => { if (e.key === 'Enter') { apply(current); onPlacing?.(null) } if (e.key === 'Escape') onPlacing?.(null) }}
            />
            <Button type="button" variant="outline" size="sm" aria-label="Nudge earlier" onClick={() => { const t = Math.round(Math.max(0, current - 0.1) * 100) / 100; onPlacing?.({ id, start: t, duration }); setPlaceText(timecode(t)) }}>◀</Button>
            <Button type="button" variant="outline" size="sm" aria-label="Nudge later" onClick={() => { const t = Math.round((current + 0.1) * 100) / 100; onPlacing?.({ id, start: t, duration }); setPlaceText(timecode(t)) }}>▶</Button>
            <Button type="button" size="sm" onClick={() => { apply(current); onPlacing?.(null) }} disabled={disabled}>Put it here</Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => onPlacing?.(null)}>Cancel</Button>
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
      <div
        key={c.candidate_id}
        className={cn('flex flex-col gap-2 rounded-lg border bg-card p-3 text-card-foreground shadow-xs', riseClass, total > 1 && n === total && 'border-l-2 border-l-primary')}
        data-testid="take"
        data-chosen={total > 1 && n === total ? 'true' : undefined}
      >
        <div className="flex items-center gap-2.5">
          <Button
            variant={playing === c.candidate_id ? 'default' : 'outline'}
            size="icon-sm"
            className="rounded-full"
            aria-label={`Play take ${n} in the video`}
            aria-pressed={playing === c.candidate_id}
            onClick={() => onPlayTake(c)}
          ><PlayIcon /></Button>
          <span className="min-w-0 text-sm font-medium">Take {n}{voice ? ` · ${voice}'s voice` : ''}</span>
          <span className="flex-1" />
          {v.score !== null && <span className="tnum text-sm text-muted-foreground">{v.score.toFixed(2)}</span>}
        </div>
        <div className="text-sm leading-normal">{v.text}{held ? ' Held the picture: no room to play over it.' : ''}</div>
        {onMove && placeControl(c.candidate_id, c.plan.selection.start, c.audio.duration, (t) => onMove(key, c, t))}
        {total === 1 && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void run(`keep-${c.candidate_id}`, () => onKeep(key, c))} disabled={disabled || pending !== null} aria-busy={pending === `keep-${c.candidate_id}` || undefined}>{pending === `keep-${c.candidate_id}` ? 'Keeping…' : 'Keep'}</Button>
            <Button variant="outline" onClick={() => void run(`another-${key}`, () => onAnother(key))} disabled={disabled || pending !== null} aria-busy={pending === `another-${key}` || undefined}>{pending === `another-${key}` ? 'Asking…' : 'Another take'}</Button>
          </div>
        )}
      </div>
    )
  }

  const lineBlock = (key: LineKey, s: Statement, index: number) => {
    const state = lines[key]
    if (!state) return null
    if (state.status === 'working') {
      return <div className={cn('flex items-center gap-2 text-sm text-muted-foreground', riseClass)} data-testid="line-working" role="status"><Spinner /><span>{state.progress ?? 'Voicing the line…'}</span></div>
    }
    if (state.status === 'failed') {
      return (
        <div className={cn('flex flex-wrap items-center gap-2.5 rounded-lg border border-needs/40 bg-needs-soft p-2.5 text-sm text-foreground', riseClass)} data-testid="line-error" role="alert">
          <span className="min-w-0 flex-1">{state.error ?? "Couldn't voice it."}</span>
          {state.request && <Button variant="outline" size="sm" onClick={() => onHear(key, state.request!)} disabled={disabled}>Try again</Button>}
          <Button variant="ghost" size="sm" onClick={() => onDismiss(key)}>Dismiss</Button>
        </div>
      )
    }
    if (state.status === 'needs-you' && state.question) {
      const q = state.question
      return (
        <div className={cn('flex flex-col gap-2 rounded-lg border border-needs/40 bg-needs-soft p-3 text-sm leading-normal text-foreground', riseClass)} data-testid="line-needs-you" role="status">
          <div>{q.question}</div>
          <div className="flex flex-wrap gap-2">
            {q.options.map((o, k) => (
              <Button key={k} variant={k === 0 ? 'default' : 'outline'} onClick={() => void run(`answer-${key}`, () => onAnswer(key, o))} disabled={disabled || pending !== null} aria-busy={pending === `answer-${key}` || undefined}>
                {o.label}{o.warning && <span className="font-normal opacity-80"> {o.warning}</span>}
              </Button>
            ))}
            <Button variant="ghost" onClick={() => { onDismiss(key); open(index, 'edit') }}>Change the words instead</Button>
          </div>
        </div>
      )
    }
    const takes = state.takes.slice(-2)
    const total = state.takes.length
    return (
      <div className="flex flex-col gap-2">
        <div className={takes.length > 1 ? 'flex gap-2 *:min-w-0 *:flex-1 max-sm:flex-col' : undefined}>
          {takes.map((c, i) => takeCard(key, c, s, total - takes.length + i + 1, total, state))}
        </div>
        {takes.length > 1 && (
          <div className="flex flex-wrap gap-2">
            {takes.map((c, i) => (
              <Button key={c.candidate_id} variant={i === takes.length - 1 ? 'default' : 'outline'} onClick={() => void run(`keep-${c.candidate_id}`, () => onKeep(key, c))} disabled={disabled || pending !== null} aria-busy={pending === `keep-${c.candidate_id}` || undefined}>
                {pending === `keep-${c.candidate_id}` ? 'Keeping…' : `Keep take ${total - takes.length + i + 1}`}
              </Button>
            ))}
            <Button variant="outline" onClick={() => void run(`another-${key}`, () => onAnother(key))} disabled={disabled || pending !== null}>{pending === `another-${key}` ? 'Asking…' : 'Another take'}</Button>
            <Button variant="ghost" onClick={() => { onDismiss(key); open(index, 'edit') }}>Neither — change the words</Button>
          </div>
        )}
      </div>
    )
  }

  /** The rows in time order: every line of the transcript, and for a line
   *  that was shifted, a second row where its words now play. */
  type Row = { kind: 'line'; s: Statement; i: number; start: number; end: number }
    | { kind: 'moved'; s: Statement; i: number; rev: Revision; from: Revision; start: number; end: number }
  const rows: Row[] = statements.map((s, i): Row => ({ kind: 'line', s, i, start: s.start, end: s.end }))
  for (const from of revisions) {
    if (from.mix !== 'remove' || !from.partner) continue
    const rev = revisions.find((r) => r.edit_id === from.partner)
    const i = statements.findIndex((s) => overlaps(from, s))
    if (!rev || i < 0) continue
    rows.push({ kind: 'moved', s: statements[i], i, rev, from, start: rev.start, end: rev.end })
  }
  rows.sort((a, b) => a.start - b.start || (a.kind === 'moved' ? 1 : 0) - (b.kind === 'moved' ? 1 : 0))
  const rowKey = (r: Row) => (r.kind === 'moved' ? `moved-${r.rev.edit_id}` : keyOf({ start: r.s.start, end: r.s.end }))

  /** Start dragging a row up or down; the drop puts its words where the
   *  row above ends. The bar above shows the block as it goes. */
  const startDrag = (e: React.PointerEvent, key: string, label: string, at: number, duration: number, apply: (to: number) => void) => {
    if (!onPlacing) return
    e.preventDefault()
    dragged.current = false
    setDrag({ key, label, duration, at, to: at, apply })
    onPlacing({ id: key, start: at, duration })
    const move = (ev: PointerEvent) => {
      const els = Array.from(document.querySelectorAll<HTMLElement>('[data-row-key]')).filter((el) => el.dataset.rowKey !== key)
      let to = 0
      for (const el of els) {
        const box = el.getBoundingClientRect()
        if (ev.clientY > box.top + box.height / 2) to = Number(el.dataset.rowEnd)
      }
      to = Math.round(to * 100) / 100
      dragged.current = true
      setDrag((d) => (d ? { ...d, to } : d))
      onPlacing({ id: key, start: to, duration })
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setDrag((d) => {
        if (d && Math.abs(d.to - d.at) > 0.005) d.apply(d.to)
        return null
      })
      onPlacing(null)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  /** The row the drag would drop before, for the marker. */
  const dropIndexFor = (to: number) => {
    const others = rows.filter((r) => rowKey(r) !== drag?.key)
    const target = others.find((r) => r.end > to + 0.001)
    return target ? rows.indexOf(target) : rows.length
  }
  const dropMarker = () => drag && (
    <div className="relative mx-2.5 h-0 border-t-2 border-primary" data-testid="drop-line" role="presentation">
      <span className="tnum absolute -top-3 right-0 rounded-full bg-primary px-2 py-0.5 text-xs font-semibold text-primary-foreground">Starts at {timecode(drag.to)}</span>
    </div>
  )

  /** The grip on a row that can move (UX-7e): drag it up or down the
   *  transcript; Enter opens Starts at; ↑ ↓ nudge a tenth of a second, with
   *  Shift a whole one, on the bar above; Escape lets go. Nothing is voiced. */
  const gripButton = (key: string, id: string, text: string, start: number, duration: number, apply: (to: number) => void) => {
    if (!onPlacing) return null
    const nudge = (delta: number) => {
      const current = placing?.id === id ? placing.start : start
      const t = Math.round(Math.max(0, current + delta) * 100) / 100
      onPlacing({ id, start: t, duration })
      setPlaceText(timecode(t))
    }
    return (
      <button
        type="button"
        className={gripClass}
        aria-label={`Move the line at ${clock(start)}: drag it, or press Enter to type a time`}
        onPointerDown={(e) => startDrag(e, key, text, start, duration, apply)}
        onClick={() => { if (dragged.current) { dragged.current = false; return } onPlacing({ id, start, duration }); setPlaceText(timecode(start)) }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); nudge((e.key === 'ArrowUp' ? -1 : 1) * (e.shiftKey ? 1 : 0.1)) }
          if (e.key === 'Escape' && placing?.id === id) { e.preventDefault(); onPlacing(null) }
        }}
      >
        <GripVertical size={16} aria-hidden="true" />
      </button>
    )
  }

  /** Move up / Move down, without dragging: the line lands where the row
   *  above the gap ends, as a drop would. */
  const stepTo = (key: string, direction: -1 | 1): number | null => {
    const order = rows.findIndex((r) => rowKey(r) === key)
    if (order < 0) return null
    if (direction < 0) return order === 0 ? null : order === 1 ? 0 : Math.round(rows[order - 2].end * 100) / 100
    const next = rows[order + 1]
    return next ? Math.round(next.end * 100) / 100 : null
  }

  /** A line's words where they now play, after a shift: its own row, with
   *  where it came from, Undo, Move, and a grip to drag it again. */
  const movedRow = (entry: Extract<Row, { kind: 'moved' }>, order: number) => {
    const { s, rev, from } = entry
    const label = name(s.speaker)
    const key = `moved-${rev.edit_id}`
    return (
      <Fragment key={key}>
        {drag && dropIndexFor(drag.to) === order && dropMarker()}
        <div
          id={key}
          className={rowClass}
          data-state="moved"
          data-row-key={key}
          data-row-end={rev.end}
          data-dragging={drag?.key === key || undefined}
          tabIndex={0}
          role="listitem"
          aria-label={`Moved line at ${clock(rev.start)}${label ? `, ${label}` : ''}`}
        >
          <span className="flex items-start">
            {rev.edit_id && onMoveKept && gripButton(key, `edit-${rev.edit_id}`, s.text, rev.start, Math.max(0.05, rev.end - rev.start), (t) => onMoveKept(rev.edit_id!, t))}
          </span>
          <button className={timeClass} onClick={() => onSeek({ ...s, start: rev.start, end: rev.end })} aria-label={`Go to ${clock(rev.start)}`}>{clock(rev.start)}</button>
          <span className="flex justify-center pt-px">{label && <Avatar name={label} slot={speakerSlot(speakers, s.speaker)} />}</span>
          <div className="min-w-0">
            <div className="flex flex-col gap-1.5">
              <span className="block text-base leading-normal">{s.text}</span>
              <div className={metaClass}>
                Moved from {clock(from.start)}, as spoken, over the sound here.
                {rev.edit_id && <> <LinkButton onClick={() => onUndo(rev.edit_id!)}>Undo</LinkButton></>}
              </div>
              {rev.edit_id && onMoveKept && placeControl(`edit-${rev.edit_id}`, rev.start, Math.max(0.05, rev.end - rev.start), (t) => onMoveKept(rev.edit_id!, t))}
            </div>
          </div>
          <span className={sideClass}>
            <StatusBadge status="kept">Moved</StatusBadge>
          </span>
        </div>
      </Fragment>
    )
  }

  /** One line of the transcript, as a row with everything about it inside. */
  const lineRow = (s: Statement, i: number, order: number) => {
    const key = keyOf({ start: s.start, end: s.end })
    const addKey = addKeyOf(s)
    const current = currentTime >= s.start && currentTime < s.end
    const selected = !!selection && overlaps(selection, s)
    const pending = pendingLines.find((p) => overlaps(p.selection, s) && STATUS[p.status])
    // The placed half of a shifted line belongs to the line it came from, not the one it lands on.
    const live = revisions.filter((r) => overlaps(r, s) && !(r.mix === 'layer' && r.partner))
    const revision = live.length ? live[live.length - 1] : null
    const removed = revision?.mix === 'remove'
    const movedTo = removed && revision?.partner ? revisions.find((r) => r.edit_id === revision.partner) ?? null : null
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
    // UX-7e: an untouched line shifts; a kept line moves with its take; the rest stay put.
    const mover: { id: string; start: number; duration: number; apply: (to: number) => void } | null =
      !revision && onShift ? { id: `shift-${key}`, start: s.start, duration: Math.max(0.05, s.end - s.start), apply: (t) => onShift(s, t) }
      : revision && !removed && revision.edit_id && onMoveKept ? { id: `edit-${revision.edit_id}`, start: revision.start, duration: Math.max(0.05, revision.end - revision.start), apply: (t) => onMoveKept(revision.edit_id!, t) }
      : null
    const up = mover ? stepTo(key, -1) : null
    const down = mover ? stepTo(key, 1) : null
    return (
      <Fragment key={`${s.start}-${i}`}>
        {drag && dropIndexFor(drag.to) === order && dropMarker()}
        <div
          id={`line-${i}`}
          className={rowClass}
          data-current={current}
          data-selected={selected}
          data-state={status ?? undefined}
          data-row-key={key}
          data-row-end={s.end}
          data-dragging={drag?.key === key || undefined}
          data-actions-open={actionsOpen === i || undefined}
          tabIndex={0}
          role="listitem"
          aria-label={`Line at ${clock(s.start)}${label ? `, ${label}` : ''}`}
          onKeyDown={(e) => onRowKey(e, i)}
          onFocus={(e) => { if (e.target === e.currentTarget) setFocusedRow(i) }}
          onBlur={(e) => { if (e.target === e.currentTarget) setFocusedRow((f) => (f === i ? null : f)) }}
        >
          <span className="flex items-start">
            {mover && !isEditing && !isAdding && gripButton(key, mover.id, s.text, mover.start, mover.duration, mover.apply)}
          </span>
          <button className={timeClass} onClick={() => onSeek(s)} aria-label={`Go to ${clock(s.start)}`}>{clock(s.start)}</button>
          <span className="flex justify-center pt-px">{newSpeaker && label && <Avatar name={label} slot={speakerSlot(speakers, s.speaker)} />}</span>
          <div className="min-w-0">
            {isEditing ? <div className={unfold}>{editor(s, 'edit')}</div> : (
              <div className="flex flex-col gap-1.5">
                <button className={lineClass} onClick={() => open(i, 'edit')} title="Change the words" data-testid={shown ? 'revision' : undefined}>
                  {s.placed && !shown && !removed ? <span className="italic text-muted-foreground">Voice-over, {timecode(s.start)}–{timecode(s.end)}</span>
                    : removed ? <del className={DEL}>{s.text}</del>
                    : shown ? trackedChanges(s, shown, words).map((run, k) => (
                      <Fragment key={k}>{k > 0 && ' '}
                        {run.kind === 'same' ? <span>{run.text}</span> : run.kind === 'del' ? <del className={DEL}>{run.text}</del> : <ins className={INS}>{run.text}</ins>}
                      </Fragment>
                    )) : s.text}
                </button>
                {(revision || removed) && (
                  <div className={metaClass}>
                    {movedTo ? `Moved to ${timecode(movedTo.start)}; the room's own sound stays here.`
                      : removed ? "Removed. The gap is closed with the room's own sound; the picture is untouched." : `Kept${shown && MIX_NOTE[shown.mix] ? ` · ${MIX_NOTE[shown.mix]}` : ''}.`}
                    {revision?.edit_id && <> <LinkButton onClick={() => onUndo(revision.edit_id!)}>Undo</LinkButton></>}
                  </div>
                )}
                {revision && !removed && revision.edit_id && onMoveKept && (
                  placeControl(`edit-${revision.edit_id}`, revision.start, Math.max(0.05, revision.end - revision.start), (t) => onMoveKept(revision.edit_id!, t))
                )}
{!revision && onShift && placing?.id === `shift-${key}` && (
                  placeControl(`shift-${key}`, s.start, Math.max(0.05, s.end - s.start), (t) => onShift(s, t))
                )}
                {pending && !revision && pending.text && MIX_NOTE[pending.mix ?? 'replace'] && (
                  <div className={metaClass}>Added · {MIX_NOTE[pending.mix ?? 'replace']}</div>
                )}
                {!isEditing && <div className={unfold}>{lineBlock(key, s, i)}</div>}
              </div>
            )}
          </div>
          <span className={sideClass}>
            {status && STATUS[status] && <StatusBadge status={status} role="status">{STATUS[status]}</StatusBadge>}
            {status === 'kept' && <StatusBadge status="kept">Kept</StatusBadge>}
            {status === 'removed' && <StatusBadge status="removed">{movedTo ? 'Moved away' : 'Removed'}</StatusBadge>}
            {!isEditing && !isAdding && (
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="hidden text-lg tracking-wide text-muted-foreground aria-expanded:bg-accent aria-expanded:text-foreground [@media(hover:none)]:inline-flex"
                aria-label={`Actions for ${clock(s.start)}`}
                aria-expanded={actionsOpen === i}
                onClick={() => setActionsOpen((o) => (o === i ? null : i))}
              >…</Button>
            )}
            {!isEditing && !isAdding && (
              <span className={actionsClass} role="group" aria-label={`Actions for ${clock(s.start)}`}>
                <Button variant="outline" size="sm" className={actionBtn} onClick={() => { setActionsOpen(null); open(i, 'edit') }}>Change the words</Button>
                <Button variant="outline" size="sm" className={actionBtn} onClick={() => { setActionsOpen(null); open(i, 'edit', true) }}>Change the delivery</Button>
                <Button variant="outline" size="sm" className={actionBtn} onClick={() => { setActionsOpen(null); open(i, 'add') }}>Add a line after</Button>
                {!removed && <Button variant="outline" size="sm" className={actionBtn} onClick={() => { setActionsOpen(null); onRemove(s) }}>Remove</Button>}
                {mover && up !== null && <Button variant="outline" size="sm" className={actionBtn} onClick={() => { setActionsOpen(null); mover.apply(up) }}>Move up</Button>}
                {mover && down !== null && <Button variant="outline" size="sm" className={actionBtn} onClick={() => { setActionsOpen(null); mover.apply(down) }}>Move down</Button>}
                {mover && onPlacing && (
                  <Button variant="outline" size="sm" className={actionBtn} onClick={() => { onPlacing({ id: mover.id, start: mover.start, duration: mover.duration }); setPlaceText(timecode(mover.start)) }}>Shift to a time…</Button>
                )}
                <Button variant="outline" size="sm" className={actionBtn} onClick={() => onSeek(s)}>Play original</Button>
              </span>
            )}
          </span>
        </div>
        {isAdding && (
          <div className={rowClass} data-state="adding" role="listitem" aria-label={`New line after ${clock(s.start)}`}>
            <span />
            <span />
            <span />
            <div className="min-w-0"><div className={unfold}>{editor(s, 'add')}</div></div>
          </div>
        )}
        {added && !isAdding && (
          <div className={rowClass} data-state={added.status} role="listitem" aria-label={`New line after ${clock(s.start)}`}>
            <span />
            <span className="tnum text-sm text-muted-foreground">{clock(s.end)}</span>
            <span />
            <div className="min-w-0">
              <div className={metaClass}>New line after {clock(s.start)}{added.request ? ` · ${added.request.mix === 'over' ? 'plays over the picture' : 'the picture makes room'}` : ''}</div>
              {lineBlock(addKey, s, i)}
            </div>
            <span className={sideClass}>{STATUS[added.status] && <StatusBadge status={added.status} role="status">{STATUS[added.status]}</StatusBadge>}</span>
          </div>
        )}
        {!isAdding && !added && i === statements.length - 1 && !(s.placed && placingAnother) && (
          <div className="px-2.5 py-1 pl-[110px] max-[960px]:pl-2.5" role="listitem">
            <Button variant="outline" className="border-dashed text-muted-foreground shadow-none" onClick={() => (s.placed && duration ? setPlacingAnother(true) : open(i, 'add'))}><span aria-hidden="true">+</span> {s.placed ? 'Add another voice-over' : 'Add a line here'}</Button>
          </div>
        )}
        {s.placed && placingAnother && duration && i === statements.length - 1 && (
          <div className={rowClass} data-state="adding" role="listitem" aria-label="New voice-over">
            <span />
            <span />
            <span />
            <div className="min-w-0">
              <PlaceEditor
                duration={duration} voices={voices} usdPerChar={usdPerChar} longLines={longLines} disabled={disabled}
                placing={placing} onPlacing={onPlacing} initialStart={Math.min(duration - 1, s.end + 0.3)}
                onHear={(span, request) => { setPlacingAnother(false); onHear(keyOf(span), request) }}
                onCancel={() => setPlacingAnother(false)}
              />
            </div>
          </div>
        )}
      </Fragment>
    )
  }

  return (
    <section className="flex flex-col gap-0.5" aria-label="Transcript">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-2.5 pb-2 pt-1">
        <h2 className="m-0 text-base font-semibold">Transcript</h2>
        {filter && (
          <div className="inline-flex gap-0.5 rounded-lg border bg-muted p-0.5" role="group" aria-label="Show">
            <Button variant="ghost" size="sm" className={cn('whitespace-nowrap', filter.on && 'bg-background shadow-xs hover:bg-background dark:hover:bg-background')} aria-pressed={filter.on} onClick={() => filter.onChange(true)}>Changes · {filter.count}</Button>
            <Button variant="ghost" size="sm" className={cn('whitespace-nowrap', !filter.on && 'bg-background shadow-xs hover:bg-background dark:hover:bg-background')} aria-pressed={!filter.on} onClick={() => filter.onChange(false)}>The whole script</Button>
          </div>
        )}
        <span className={hint}>
          {review ? 'Keep what sounds right; hold the rest as drafts. The Ship button in the bar counts what you keep.'
            : editing ? (editing.mode === 'edit' ? `Editing ${clock(statements[editing.index].start)}. Enter to hear it, Esc to cancel.` : `Adding a line after ${clock(statements[editing.index].start)}. Esc to cancel.`)
            : pendingLines.some((p) => p.status === 'reading') ? "Voltage is reading. The line it's on is lit."
            : focusedRow !== null ? <span className="whitespace-nowrap max-[960px]:hidden" data-testid="keys"><kbd className={kbd}>↑</kbd><kbd className={kbd}>↓</kbd> move · <kbd className={kbd}>Enter</kbd> change the words · <kbd className={kbd}>Space</kbd> play · <kbd className={kbd}>A</kbd> add after · <kbd className={kbd}>S</kbd> shift (or drag ⋮⋮) · <kbd className={kbd}>K</kbd> keep · <kbd className={kbd}>U</kbd> undo · <kbd className={kbd}>/</kbd> ask Voltage</span>
            : armedRow !== null ? <span role="status">Press Backspace again to remove the line at {clock(statements[armedRow].start)}.</span>
            : 'Each line carries its own state. Tap or hover a line, or press ↑ ↓ to move between them.'}
        </span>
      </div>

      {review ?? (
      <div role="list" className="flex flex-col gap-0.5" ref={list} onFocusCapture={() => setFocusTick((t) => t + 1)} onBlurCapture={() => setFocusTick((t) => t + 1)} data-focus-tick={focusTick}>
        {rows.map((entry, order) => (entry.kind === 'moved' ? movedRow(entry, order) : lineRow(entry.s, entry.i, order)))}
        {drag && dropIndexFor(drag.to) === rows.length && dropMarker()}
      </div>
      )}
    </section>
  )
}
