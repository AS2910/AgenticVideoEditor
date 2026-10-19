import { Fragment, useEffect, useRef, useState } from 'react'
import type React from 'react'
import type { ReactNode } from 'react'
import type {
  Candidate, ItemStatus, Mix, PlanItem, Revision, Selection, Speaker, Statement, Voice, Word,
} from '../types'
import { diffWords, lineAfter, trackedChanges } from '../transcript/changes'
import { clock } from '../transcript/format'
import { verdict } from '../transcript/verdict'
import { takeFacts } from '../transcript/facts'
import { parseTime, timecode } from '../transcript/time'
import { PlaceEditor } from './PlaceEditor'
import { GripVertical, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { Chip, ControlRow, LinkButton } from './EditorControls'
import { editorClass, riseClass, selectClass } from './editorStyles'

import { addKeyOf, keyOf } from '../transcript/keys'
import type { LineKey } from '../transcript/keys'

/** What the editor asks for a line: the words and the choices. App says it
 *  to Voltage in one sentence; nothing is voiced outside a turn. */
export interface LineRequest {
  selection: Selection
  text: string
  voiceId: string | null
  delivery: string | null
  mix: 'replace' | 'over' | 'concatenate' | 'layer'
  /** For an added line: a chosen start on the timeline instead of "after this line". */
  at?: number | null
  /** 20f: a proposal voiced again with these words (its item), or an added
   *  line redone (its edit, which the new take swaps out). */
  itemId?: string
  editId?: string
  /** The words the line has now, for the sentence to Voltage. */
  before?: string
}

/** A line the agent's plan is working on: where it stands, and the new words. */
export interface PendingLine { selection: Selection; status: ItemStatus | 'reading'; text?: string; mix?: Mix }

interface LineDocProps {
  statements: Statement[]
  words?: Word[]
  speakers?: Speaker[]
  voices?: Voice[]
  /** Approved edits still in force, shown on their lines. */
  revisions?: Revision[]
  selection?: Selection | null
  currentTime: number
  /** The agent's plan, line by line: where each line stands. */
  pendingLines?: PendingLine[]
  /** The plan's items (planned and on), so a line carries its take, its progress, or its state. */
  items?: PlanItem[]
  disabled?: boolean
  /** The ElevenLabs rate, for the cost line; unknown = no cost shown. */
  usdPerChar?: number | null
  /** The take playing in the video right now, if any. */
  playing?: string | null
  onSeek: (statement: Statement) => void
  /** Hear it: what the editor asks for; App says it to Voltage as one turn. */
  onHear: (key: LineKey, request: LineRequest) => void
  /** Add it (20e): the proposal under a line goes into the video — its plan item is approved and rendered. */
  onAdd: (item: PlanItem) => void | Promise<unknown>
  /** Discard a proposal: it leaves the plan. */
  onDiscard: (item: PlanItem) => void | Promise<unknown>
  /** Add them all: every proposal at once. */
  onAddAll?: (items: PlanItem[]) => void | Promise<unknown>
  /** Take it out: an added line leaves the video and stands as a proposal again. */
  onUndo: (editId: string) => void
  /** Discard on a line as shot: proposes removing it (the room's own sound in its place). */
  onRemove: (statement: Statement) => void
  /** Hear it on a proposal: the take in place. */
  onHearTake: (item: PlanItem, candidate: Candidate) => void
  /** 20g: a line mixed under the words (background) or at full level, nothing voiced again. */
  onLevel?: (target: { editId?: string; candidate?: Candidate; item?: PlanItem }, levelDb: number) => void
  backgroundDb?: number
  /** UX-9: a delivery chip on a proposal asks Voltage for that take again, said that way. */
  onDelivery?: (item: PlanItem, delivery: string) => void
  /** UX-1c: move this line of the original speech to start at `to`. */
  onShift?: (s: Statement, to: number) => void
  /** A take dragged to a new start; the moved take replaces it under the line. */
  onMove?: (item: PlanItem, candidate: Candidate, start: number) => void
  /** A kept line dragged to a new start. */
  onMoveKept?: (editId: string, start: number) => void
  /** While a take or kept line is being placed: its start, for the bar. */
  placing?: { id: string; start: number; duration: number } | null
  onPlacing?: (placing: { id: string; start: number; duration: number } | null) => void
  onEditingChange?: (statement: Statement | null) => void
  /** UX-5: the clip's length, so a voice-over can be placed on a clip with no speech. */
  duration?: number
  /** As shot (2026-10-19): the version the player plays. In As shot the live edits are not in it:
   *  added and moved lines dim with "not in this version", removed and replaced lines read as shot. */
  version?: 'edited' | 'proposals' | 'as-shot'
}

const NOT_IN_VERSION = <span className="tag rounded-[4px] border border-dashed border-line2 px-1.5 py-px text-faint" data-testid="not-in-version">not in this version</span>

const overlaps = (a: { start: number; end: number }, b: { start: number; end: number }) =>
  a.start < b.end && b.start < a.end

const STATUS: Record<string, string> = {
  reading: 'Reading', planned: 'Planned', working: 'Voicing…', ready: 'Proposed', 'needs-you': 'Waiting on you', failed: "Couldn't voice it",
  kept: '✓ In the video', removed: 'Removed',
}
/** A row's state is a stamp (Volt): volt for a proposal, amber for a step waiting on you, an outline for what is in the video. */
const TONE: Record<string, string> = {
  reading: '', planned: 'in', working: 'in', ready: '', 'needs-you': 'need', failed: 'need', kept: 'in', removed: 'in',
}
const INS = ''
const DEL = ''
const hint = 'meta'
const faint = 'text-sm text-muted-foreground'
// UX-9: every audio line is a card. A proposal wears the accent border; an
// added line a quiet one; a removed line fades until hovered.
// Volt: the transcript row from the mocks — a grip, the time, the body. A
// proposal is `.prop` (ink border, offset shadow); a line waiting on you is
// dashed; a line as shot shows its actions on hover.
const rowClass = [
  'group/row relative grid min-h-11 grid-cols-[24px_76px_minmax(0,1fr)] items-start gap-x-3 gap-y-2 rounded-[10px] px-3.5 py-3 outline-none transition-colors',
  'focus-visible:ring-[3px] focus-visible:ring-ring/50',
  'data-[selected=true]:bg-sunk data-[state=reading]:bg-sunk hover:bg-sunk',
  'data-[state=ready]:prop data-[state=ready]:my-1.5 data-[state=ready]:hover:bg-card data-[state=needs-you]:waiting data-[state=failed]:waiting',
  'data-[state=removed]:opacity-75 data-[state=removed]:hover:opacity-100 data-[state=adding]:border-[1.5px] data-[state=adding]:border-dashed data-[state=adding]:border-foreground',
  'data-[dragging]:opacity-50',
].join(' ')
const timeClass = 'tnum flex min-h-6 items-start pt-[3px] rounded-md text-left text-xs text-faint outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 group-data-[current=true]/row:font-semibold group-data-[current=true]/row:text-foreground'
const gripClass = [
  'relative -my-2.5 inline-flex h-11 w-6 cursor-grab touch-none select-none items-center justify-center rounded-md border border-transparent p-0 text-muted-foreground opacity-60 outline-none transition-opacity',
  'before:absolute before:inset-y-0 before:-inset-x-2.5 hover:bg-accent hover:text-foreground focus-visible:opacity-100 focus-visible:ring-[3px] focus-visible:ring-ring/50 active:cursor-grabbing',
  'group-hover/row:opacity-100 group-focus-within/row:opacity-100 max-[960px]:opacity-100',
].join(' ')
const lineClass = 'say block min-h-0 w-full cursor-pointer rounded-sm p-0 text-left text-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50'
const metaClass = 'meta'
const unfold = 'grid grid-rows-[1fr] empty:hidden *:min-h-0 ' + riseClass
const kbd = 'kbd mx-px'
// A line as shot shows its actions on hover or focus (quiet `.act`s); on touch the "…" button opens them.
const actionsClass = [
  'flex flex-wrap items-center gap-0.5 -ml-2 transition-opacity',
  'opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100 group-data-[actions-open]/row:opacity-100',
  '[@media(hover:none)]:hidden group-data-[actions-open]/row:[@media(hover:none)]:flex [@media(hover:none)]:opacity-100',
].join(' ')
const StatusBadge = ({ status, children, role }: { status: string; children: ReactNode; role?: 'status' }) => (
  <span className={cn('stamp', TONE[status])} role={role} data-status={status}>{children}</span>
)
const KBD = ({ k }: { k: string }) => <span className="kbd ml-0.5" aria-hidden="true">{k}</span>
const PlayGlyph = () => <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.5v11l9-5.5z" fill="currentColor" /></svg>
const BoltGlyph = () => <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true"><path d="M9 1.5 3.5 9H8l-1 5.5L12.5 7H8z" fill="currentColor" /></svg>
const DELIVERIES = ['warmer', 'more excited', 'calmer', 'slower', 'firmer']
const MIX_NOTE: Record<string, string | null> = {
  replace: null, layer: 'plays over the picture', over: 'plays over the picture', concatenate: 'the picture makes room while it plays', remove: null,
}
const voiceLabel = (v: Voice) => (v.category === 'mine' ? `${v.name} (yours)` : v.gender ? `${v.name} (${v.gender})` : v.name)

const Spinner = () => <Loader2 size={16} aria-hidden="true" className="shrink-0 animate-spin text-changed" />

/** The transcript as the working surface: every line carries its own state,
 *  actions, editor and takes. Nothing about a line happens anywhere else. */
export function LineDoc({
  statements, words = [], speakers = [], voices = [], revisions = [], selection, currentTime,
  pendingLines = [], items = [], disabled, usdPerChar, playing,
  onSeek, onHear, onAdd, onDiscard, onAddAll, onUndo, onRemove, onHearTake, onLevel, backgroundDb = -12, onDelivery,
  onEditingChange, onMove, onMoveKept, placing, onPlacing, onShift, duration, version = 'edited',
}: LineDocProps) {
  const asShot = version === 'as-shot'
  const [at, setAt] = useState<string>('')          // the add editor's "starts at", as typed
  const [placeText, setPlaceText] = useState('')     // the placing control's time, as typed
  const [editing, setEditing] = useState<{ order: number; mode: 'edit' | 'add' | 'layer' } | null>(null)
  const [draft, setDraft] = useState('')
  const [voiceId, setVoiceId] = useState('')
  const [delivery, setDelivery] = useState<string | null>(null)
  const [ownWords, setOwnWords] = useState<string | null>(null)
  const [mix, setMix] = useState<'over' | 'concatenate'>('over')
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
  // Volt: depth on demand — the proposal opened in place (its item id), and which runs of untouched lines are unfolded.
  const [expanded, setExpanded] = useState<string | null>(null)
  const [unfolded, setUnfolded] = useState<Set<number>>(() => new Set())
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
  // The rows as last rendered, for effects that need a row by its order.
  const rowsRef = useRef<Row[]>([])

  useEffect(() => { box.current?.focus() }, [editing])
  // The row to put focus back on when its editor closes, so the keys keep working.
  const returnTo = useRef<number | null>(null)
  useEffect(() => {
    if (editing || returnTo.current === null) return
    document.getElementById(`line-${returnTo.current}`)?.focus()
    returnTo.current = null
  }, [editing])

  // 20f: audio lines are rows of their own. An added line in the video (a
  // layered edit) and a proposed or working added line (a plan item) each
  // stand as a row at their own time, however many share a moment: two
  // audios may play at once, and the transcript says so with two rows.
  const isAdd = (i: { mix: Mix }) => i.mix === 'over' || i.mix === 'concatenate' || i.mix === 'layer'
  const layerRevisions = revisions.filter((r) => isAdd(r) && !r.partner)
  const addedItems = items.filter((i) => isAdd(i) && i.status !== 'approved' && i.status !== 'dismissed')

  useEffect(() => {
    onEditingChange?.(editing && editing.mode === 'edit' ? (statements[rowsRef.current[editing.order]?.kind === 'line' ? (rowsRef.current[editing.order] as { i: number }).i : -1] ?? null) : null)
  }, [editing, statements, onEditingChange])

  if (statements.length === 0 && layerRevisions.length === 0 && addedItems.length === 0) {
    // UX-5: nothing to read and nothing placed yet, so the first thing is where the voice-over goes.
    if (duration) {
      return (
        <section className="flex flex-col gap-0.5" aria-label="Transcript">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-2.5 pb-2 pt-1">
            <h2 className="m-0 text-base font-semibold">Voice-over</h2>
            <span className={hint}>No one speaks in this clip. Place a line where you want it, and say what it should say.</span>
          </div>
          <PlaceEditor
            duration={duration} voices={voices} usdPerChar={usdPerChar} disabled={disabled}
            placing={placing} onPlacing={onPlacing}
            onHear={(span, request) => onHear(keyOf(span), request)}
          />
        </section>
      )
    }
    return <p className="m-0 py-6 text-muted-foreground">No lines to show. This video has no transcribed speech.</p>
  }

  /** The speaker's name; an unnamed one is Speaker 1, 2, 3 in order of appearance (20e). */
  const name = (label?: string | null) => {
    if (!label) return null
    const sp = speakers.find((s) => s.label === label)
    if (sp?.name) return sp.name
    const order = speakers.length ? speakers.map((x) => x.label) : [...new Set(statements.map((st) => st.speaker).filter(Boolean))] as string[]
    const n = order.indexOf(label)
    return `Speaker ${n >= 0 ? n + 1 : label}`
  }

  const proposals = items.filter((i) => i.status === 'ready' && i.candidate)

  /** The edits on a spoken line itself: a replacement or a removal. A layer
   *  over it is another row, never a change to its words. */
  const ownRevisions = (s: Statement) => revisions.filter((r) => overlaps(r, s) && !isAdd(r))
  /** The line as it stands now: the kept wording, or the original. */
  const standing = (s: Statement): string => {
    const live = ownRevisions(s)
    const revision = live.length ? live[live.length - 1] : null
    return revision && revision.mix !== 'remove' ? lineAfter(s, revision, words) : s.text
  }
  /** The plan's change to the line itself (a replacement, a removal). */
  const ownItem = (s: Statement) => items.find((i) => overlaps(i.selection, s) && !isAdd(i) && i.status !== 'dismissed') ?? null

  /** The rows in time order: every spoken line; a shifted line again where it
   *  now plays; every added line in the video; every proposed or working one. */
  type Row = { kind: 'line'; s: Statement; i: number; start: number; end: number }
    | { kind: 'moved'; s: Statement; i: number; rev: Revision; from: Revision; start: number; end: number }
    | { kind: 'layer'; rev: Revision; start: number; end: number }
    | { kind: 'item'; item: PlanItem; start: number; end: number }
  const rows: Row[] = statements.map((s, i): Row => ({ kind: 'line', s, i, start: s.start, end: s.end }))
  for (const from of revisions) {
    if (from.mix !== 'remove' || !from.partner) continue
    const rev = revisions.find((r) => r.edit_id === from.partner)
    const i = statements.findIndex((s) => overlaps(from, s))
    if (!rev || i < 0) continue
    rows.push({ kind: 'moved', s: statements[i], i, rev, from, start: rev.start, end: rev.end })
  }
  for (const rev of layerRevisions) rows.push({ kind: 'layer', rev, start: rev.start, end: rev.end })
  for (const item of addedItems) {
    const span = item.candidate?.plan.selection ?? item.selection
    rows.push({ kind: 'item', item, start: span.start, end: item.candidate ? span.start + item.candidate.audio.duration : span.end })
  }
  const rank = (r: Row) => (r.kind === 'line' ? 0 : r.kind === 'moved' ? 1 : r.kind === 'layer' ? 2 : 3)
  rows.sort((a, b) => a.start - b.start || rank(a) - rank(b))
  rowsRef.current = rows
  const rowKey = (r: Row) => (r.kind === 'moved' ? `moved-${r.rev.edit_id}` : r.kind === 'layer' ? `layer-${r.rev.edit_id}` : r.kind === 'item' ? `item-${r.item.item_id}` : keyOf({ start: r.s.start, end: r.s.end }))
  /** What a row says and when, as a statement, for the editor, the player and the hint. */
  const rowStatement = (r: Row): Statement => (
    r.kind === 'line' ? r.s
    : r.kind === 'moved' ? { ...r.s, start: r.rev.start, end: r.rev.end }
    : r.kind === 'layer' ? { text: r.rev.text, start: r.rev.start, end: r.rev.end, speaker: null }
    : { text: r.item.new_text, start: r.start, end: r.end, speaker: r.item.speaker ?? null })

  /** Where to start editing from: the last wording Voltage tried on this line
   *  (a take waiting, a line being voiced, one that needs you), else the line
   *  as it stands. Never the original when you have already moved past it. */
  const startingPoint = (s: Statement) => {
    const own = ownItem(s)
    return own && own.mix !== 'remove' ? own : null
  }

  /** Open a row's editor: on a spoken line, its words as they stand (or the
   *  last wording Voltage tried); on an added line or a proposal, its own
   *  words, voice and delivery. */
  const open = (order: number, mode: 'edit' | 'add' | 'layer', focusDelivery = false) => {
    const row = rows[order]
    if (!row) return
    const s = rowStatement(row)
    const last = row.kind === 'line' && mode === 'edit' ? startingPoint(row.s) : row.kind === 'item' ? row.item : null
    setEditing({ order, mode })
    setDraft(mode === 'add' ? '' : mode === 'edit' ? (last?.new_text ?? standing(s)) : (last?.new_text ?? s.text))
    setVoiceId(last?.candidate?.plan.voice_profile_id ?? speakers.find((sp) => sp.label === s.speaker)?.voice_id ?? '')
    const known = last?.delivery && DELIVERIES.includes(last.delivery) ? last.delivery : null
    setDelivery(known)
    setOwnWords(focusDelivery && !last?.delivery ? '' : last?.delivery && !known ? last.delivery : null)
    setMix(last?.mix === 'concatenate' ? 'concatenate' : 'over')
    setAt('')
  }
  const close = () => {
    if (editing) returnTo.current = editing.order
    setEditing(null)
  }

  /** Keys on a focused row (UX-4, 20f): ↑↓ move, Enter edits it, Space hears
   *  it, K adds it, Delete discards (or proposes removing a spoken line), U
   *  takes an added line out, A adds after, S shifts. Only when the row
   *  itself has focus — never while typing in it. */
  const onRowKey = (e: React.KeyboardEvent<HTMLDivElement>, order: number) => {
    if (e.target !== e.currentTarget) return
    const row = rows[order]
    if (!row) return
    const move = (to: number) => {
      const el = document.getElementById(`line-${Math.max(0, Math.min(rows.length - 1, to))}`)
      el?.focus()
      el?.scrollIntoView?.({ block: 'nearest' })
    }
    const s = rowStatement(row)
    const proposal = row.kind === 'item' ? row.item : row.kind === 'line' ? ownItem(row.s) : null
    switch (e.key) {
      case 'ArrowDown': case 'j': e.preventDefault(); move(order + 1); break
      case 'ArrowUp': e.preventDefault(); move(order - 1); break
      case 'Enter': {
        if (row.kind === 'moved') break
        e.preventDefault(); open(order, row.kind === 'line' ? 'edit' : 'layer'); break
      }
      case ' ': {
        e.preventDefault()
        if (row.kind === 'item' && row.item.status === 'ready' && row.item.candidate) onHearTake(row.item, row.item.candidate)
        else onSeek(s)
        break
      }
      case 'a': case 'A': if (row.kind === 'line') { e.preventDefault(); open(order, 'add') } break
      case 's': case 'S': {
        if (row.kind === 'line' && onShift && onPlacing && ownRevisions(row.s).length === 0) {
          e.preventDefault()
          onPlacing({ id: `shift-${keyOf(row.s)}`, start: s.start, duration: Math.max(0.05, s.end - s.start) })
          setPlaceText(timecode(s.start))
        }
        break
      }
      case 'k': case 'K': {
        if (proposal?.status === 'ready' && proposal.candidate && !disabled) { e.preventDefault(); void onAdd(proposal) }
        break
      }
      case 'u': case 'U': {
        const editId = row.kind === 'layer' || row.kind === 'moved' ? row.rev.edit_id : row.kind === 'line' ? ownRevisions(row.s).at(-1)?.edit_id : undefined
        if (editId) { e.preventDefault(); onUndo(editId) }
        break
      }
      case 'Delete': case 'Backspace': {
        if (disabled || row.kind === 'moved' || row.kind === 'layer') break
        if (proposal && proposal.status !== 'approved') { e.preventDefault(); void onDiscard(proposal); break }
        if (row.kind !== 'line' || ownRevisions(row.s).some((r) => r.mix === 'remove')) break
        e.preventDefault()
        const now = Date.now()
        if (e.key === 'Backspace' && !(armed.current && armed.current.index === order && now - armed.current.at < 2000)) {
          armed.current = { index: order, at: now }
          setArmedRow(order)
          window.setTimeout(() => { if (armed.current && armed.current.at === now) { armed.current = null; setArmedRow(null) } }, 2000)
          break
        }
        armed.current = null
        setArmedRow(null)
        onRemove(row.s)
        break
      }
      default: break
    }
  }
  const hear = (s: Statement) => {
    const text = draft.trim()
    if (!editing || !text || (editing.mode === 'edit' && text === standing(s))) return
    const row = rows[editing.order]
    const key = editing.mode === 'add' ? addKeyOf(s) : keyOf(s)
    const chosen = editing.mode === 'add' && at.trim() ? parseTime(at) : null
    if (editing.mode === 'add' && at.trim() && chosen === null) return   // an unreadable time is never dropped silently
    onHear(key, {
      selection: { start: s.start, end: s.end }, text, voiceId: voiceId || null,
      delivery: (ownWords?.trim() || delivery) ?? null, mix: editing.mode === 'edit' ? 'replace' : editing.mode === 'layer' ? 'layer' : mix,
      ...(chosen !== null ? { at: chosen } : {}),
      ...(row?.kind === 'item' ? { itemId: row.item.item_id, before: row.item.new_text } : {}),
      ...(row?.kind === 'layer' && row.rev.edit_id ? { editId: row.rev.edit_id, before: row.rev.text } : {}),
    })
    close()
  }
  const editor = (s: Statement, mode: 'edit' | 'add' | 'layer') => {
    const chars = draft.trim().length
    const cost = usdPerChar ? ` · about ${Math.max(1, Math.round(chars * usdPerChar * 100))}¢` : ''
    const base = mode === 'edit' ? standing(s) : mode === 'layer' ? s.text : ''
    const badAt = mode === 'add' && at.trim() !== '' && parseTime(at) === null
    const preview = mode !== 'add' && draft.trim() && draft.trim() !== base
      ? diffWords(base, draft.trim()) : null
    return (
      <div className={editorClass} data-testid="editor">
        <Textarea
          ref={box}
          value={draft}
          rows={2}
          aria-label={mode === 'add' ? 'Words for the new line' : 'New wording'}
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
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <span className={cn(faint, 'tnum')}>≈ {chars} characters{cost} · Voltage voices it; the take comes back proposed</span>
          <span className="flex-1" />
          <Button type="button" variant="outline" onClick={close}>Cancel</Button>
          <Button
            type="button"
            aria-label="Voice it"
            disabled={disabled || !draft.trim() || badAt || (mode === 'edit' && draft.trim() === base)}
            onClick={() => hear(s)}
          >
            Voice it
          </Button>
        </div>
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

  /** 20g: "background (−12 dB) · Make it foreground", or "Make it background". */
  const levelControl = (levelDb: number | null | undefined, target: { editId?: string; candidate?: Candidate; item?: PlanItem }) => {
    if (!onLevel) return null
    const background = (levelDb ?? 0) < 0
    return (
      <span className="tnum" data-testid="level">
        {background ? `background (${Math.round(levelDb!)} dB) · ` : ''}
        <LinkButton onClick={() => onLevel(target, background ? 0 : backgroundDb)}>{background ? 'Make it foreground' : 'Make it background'}</LinkButton>
      </span>
    )
  }

  /** The four verbs on a proposal (20e, Volt): Hear it, Add it, Edit it (opens the depth), Discard. */
  const verbs = (item: PlanItem, c: Candidate, order: number, mode: 'edit' | 'layer', inDepth = false) => (
    <span className="flex flex-wrap items-center gap-2" role="group" aria-label={`Proposal at ${clock(c.plan.selection.start)}`}>
      <button type="button" className={cn('btn sm', playing === c.candidate_id && 'ink')} aria-pressed={playing === c.candidate_id} onClick={() => onHearTake(item, c)} data-tour-action={item.item_id === firstProposalId ? 'proposal-row' : undefined}>
        <PlayGlyph />{playing === c.candidate_id ? 'Stop' : 'Hear it'}<KBD k="␣" />
      </button>
      <button type="button" className="btn volt sm" data-tour={item.item_id === firstProposalId ? 'add-it' : undefined} onClick={() => void run(`add-${item.item_id}`, () => onAdd(item))} disabled={disabled || pending !== null} aria-busy={pending === `add-${item.item_id}` || undefined}>
        <BoltGlyph />{pending === `add-${item.item_id}` ? 'Adding…' : item.mix === 'remove' ? 'Remove it' : 'Add it'}<KBD k="K" />
      </button>
      {inDepth && item.mix !== 'remove' && onDelivery && (
        <button type="button" className="btn sm" onClick={() => void run(`again-${item.item_id}`, () => onDelivery(item, (item.delivery ?? c.plan.delivery ?? 'the same way')))} disabled={disabled || pending !== null}>
          {pending === `again-${item.item_id}` ? 'Asking…' : 'Voice it again'}
        </button>
      )}
      {!inDepth && item.mix !== 'remove' && <button type="button" className="act" onClick={() => setExpanded(item.item_id)}>Edit it</button>}
      {inDepth && item.mix !== 'remove' && <button type="button" className="act" onClick={() => open(order, mode)}>Change the words</button>}
      <button type="button" className="act" onClick={() => void run(`discard-${item.item_id}`, () => onDiscard(item))} disabled={disabled || pending !== null} aria-busy={pending === `discard-${item.item_id}` || undefined}>
        {pending === `discard-${item.item_id}` ? 'Discarding…' : 'Discard'}
      </button>
      {inDepth && <><span className="flex-1" /><button type="button" className="act" onClick={() => setExpanded(null)}><span className="tag">Less ↑</span></button></>}
    </span>
  )

  /** A proposal's one line of facts (Volt): whose voice · the verdict · what the picture does. */
  const takeMeta = (item: PlanItem, c: Candidate, speaker: string | null | undefined) => {
    const v = verdict(c, name(speaker))
    const voice = voices.find((x) => x.voice_id === c.plan.voice_profile_id)?.name
    const facts = takeFacts(c, voice)
    const picture = facts.grid.find((f) => f.label === 'Picture')?.value
    const held = item.mix === 'over' && c.plan.mix === 'concatenate'
    return (
      <div className="flex flex-col gap-1.5" data-testid="take">
        <div className={cn(metaClass, !v.passed && 'text-needs')}>
          {voice ? `${voice}'s voice` : 'The default voice'} · {v.text}
          {picture && picture !== 'as shot' ? ` The picture ${picture}.` : ''}{held ? ' Held the picture: no room to play over it.' : ''}
          {!v.passed && ' Add it anyway if it sounds right to you.'}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {onMove && placeControl(c.candidate_id, c.plan.selection.start, c.audio.duration, (t) => onMove(item, c, t))}
          {isAdd(item) && levelControl(c.plan.level_db, { candidate: c, item })}
        </div>
      </div>
    )
  }

  /** Depth on demand (Volt): the proposal opened in place — Before/After, the
   *  delivery pills, Voltage's direction, the facts, the measured meters. */
  const depth = (item: PlanItem, c: Candidate, s: Statement, order: number, mode: 'edit' | 'layer') => {
    const voice = voices.find((x) => x.voice_id === c.plan.voice_profile_id)?.name
    const facts = takeFacts(c, voice)
    const current = (item.delivery ?? c.plan.delivery ?? '').toLowerCase()
    const fact = (label: string) => facts.grid.find((f) => f.label === label)?.value ?? '—'
    const before = item.mix === 'replace' ? standing(s) : null
    return (
      <div className="flex flex-col gap-4.5" data-testid="depth">
        {before !== null ? (
          <div className="grid grid-cols-[64px_minmax(0,1fr)] items-baseline gap-x-3 gap-y-2">
            <span className="who">Before</span><span className="say text-muted-foreground"><del>{before}</del></span>
            <span className="who">After</span><span className="say disp text-[22px] font-semibold"><ins>{item.new_text}</ins></span>
          </div>
        ) : (
          <div className="say disp text-[22px] font-semibold"><ins>{item.new_text}</ins></div>
        )}
        <div className="flex flex-col gap-2">
          <span className="tag text-faint">Delivery</span>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Said again">
            {['as spoken', ...DELIVERIES].map((d) => (
              <button key={d} type="button" className="pill" aria-pressed={d === 'as spoken' ? current === '' || current === 'as spoken' : current === d} disabled={disabled || pending !== null || !onDelivery}
                onClick={() => { if (onDelivery && (d === 'as spoken' ? current !== '' && current !== 'as spoken' : current !== d)) void run(`delivery-${item.item_id}`, () => onDelivery(item, d)) }}>
                {d.charAt(0).toUpperCase() + d.slice(1)}
              </button>
            ))}
            <button type="button" className="pill" onClick={() => open(order, mode, true)}>Your words…</button>
            {pending === `delivery-${item.item_id}` && <span className={cn(metaClass, 'text-xs')} role="status">Asking Voltage…</span>}
          </div>
          {item.reason && <p className="m-0 text-sm text-muted-foreground"><span className="tag text-foreground">Voltage's direction ›</span> “{item.reason}”</p>}
        </div>
        <dl className="m-0 grid grid-cols-2 gap-3.5 border-y-[1.5px] border-line py-3.5 sm:grid-cols-4" data-testid="facts">
          {([['Voice', voice ?? 'the default'], ['Model', fact('Voice').split(' · ')[1] ?? 'default'], ['Dials', fact('Dials')], ['Fit', `${fact('Fit')} · picture ${fact('Picture')}`]] as const).map(([k, v]) => (
            <div key={k} className="flex min-w-0 flex-col gap-0.5"><dt className="tag text-faint">{k}</dt><dd className={cn('m-0 truncate text-sm', k !== 'Voice' && 'tnum')} title={v}>{v}</dd></div>
          ))}
        </dl>
        <div className="flex flex-col gap-2.5">
          <span className="tag text-faint">Measured</span>
          {facts.measured.length > 0 ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="measured">
              {facts.measured.map((f) => {
                const [, num] = /([\d.]+) · wants ([\d.]+)/.exec(f.value) ?? []
                const [, , wants] = /([\d.]+) · wants ([\d.]+)/.exec(f.value) ?? []
                const n = Number(num), w = Number(wants)
                const pct = f.label === 'UTMOS' ? Math.min(100, (n / 5) * 100) : Math.min(100, n * 100)
                return (
                  <div key={f.label} className="flex flex-col gap-1 rounded-lg border-[1.5px] border-line2 bg-card p-3">
                    <span className="tag text-faint">{f.label === 'SIM-o' ? 'Voice match' : f.label === 'UTMOS' ? 'Natural' : f.label}</span>
                    <span className="disp text-2xl font-bold">{num}</span>
                    <div className="meter"><span style={{ width: `${pct}%`, background: f.tone === 'needs' ? 'var(--warn)' : undefined }} /></div>
                    <span className="tnum text-xs text-muted-foreground">bar {wants} · {n >= w ? 'pass' : 'below'}</span>
                  </div>
                )
              })}
            </div>
          ) : <span className="tag text-faint">Not measured yet</span>}
          <span className="tag text-faint">Lip-sync · not measured yet</span>
          {facts.flagged && <span className="meta text-needs">Flagged: {facts.flagged}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {onMove && placeControl(c.candidate_id, c.plan.selection.start, c.audio.duration, (t) => onMove(item, c, t))}
          {isAdd(item) && levelControl(c.plan.level_db, { candidate: c, item })}
        </div>
        {verbs(item, c, order, mode, true)}
      </div>
    )
  }

  /** What stands under a line while Voltage is on it. */
  const lineBlock = (item: PlanItem | null, speaker: string | null | undefined) => {
    if (!item) return null
    if (item.status === 'working') {
      return (
        <div className={cn('flex flex-col gap-1.5', riseClass)}>
          <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="line-working" role="status"><Spinner /><span>{item.progress ?? 'Voicing the line…'}</span></div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true"><div className="h-full w-2/3 animate-pulse rounded-full bg-primary" /></div>
        </div>
      )
    }
    if (item.status === 'ready' && item.candidate) return takeMeta(item, item.candidate, speaker)
    if (item.status === 'failed' && item.error) return <div className={cn(metaClass, 'text-needs')}>{item.error}</div>
    return null
  }

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

  // Volt: long runs of untouched lines fold to "+ N more lines" once the
  // transcript has anything proposed or in the video, so what changed stands
  // out. The current, selected, focused or edited line never folds; a drag
  // keeps every row in place.
  const isPlain = (r: Row, order: number) => r.kind === 'line'
    && !ownItem(r.s) && ownRevisions(r.s).length === 0
    && !pendingLines.some((p) => overlaps(p.selection, r.s))
    && !(currentTime >= r.s.start && currentTime < r.s.end)
    && !(selection && overlaps(selection, r.s))
    && focusedRow !== order && editing?.order !== order && actionsOpen !== order
  const folds = (() => {
    const hidden = new Set<number>()
    const after = new Map<number, number>()   // the order a "+ N more lines" button follows → N
    if (drag || rows.length <= 8 || !rows.some((r, o) => !isPlain(r, o))) return { hidden, after }
    let start = -1
    const close = (end: number) => {
      const n = end - start
      if (start >= 0 && n > 3 && !unfolded.has(start)) { for (let o = start + 1; o < end; o++) hidden.add(o); after.set(start, n - 1) }
      start = -1
    }
    rows.forEach((r, o) => { if (isPlain(r, o)) { if (start < 0) start = o } else close(o) })
    close(rows.length)
    return { hidden, after }
  })()
  const reveal = (order: number) => {
    for (const [start, n] of folds.after) if (order > start && order <= start + n) setUnfolded((u) => new Set(u).add(start))
  }

  // The tour's anchors: the first spoken line, and the first proposal ready to hear (and its Add it).
  const firstLineOrder = rows.findIndex((r) => r.kind === 'line')
  const readyOf = (r: Row) => (r.kind === 'item' ? r.item : r.kind === 'line' ? ownItem(r.s) : null)
  const firstProposalOrder = rows.findIndex((r) => { const it = readyOf(r); return !!it && it.status === 'ready' && !!it.candidate })
  const firstProposalId = firstProposalOrder >= 0 ? readyOf(rows[firstProposalOrder])?.item_id ?? null : null
  const tourOf = (order: number) => [order === firstLineOrder && 'transcript-row', order === firstProposalOrder && 'proposal-row'].filter(Boolean).join(' ') || undefined

  /** The keyboard and focus wiring every row shares. */
  const rowProps = (order: number, key: string, label: string, end: number) => ({
    id: `line-${order}`,
    'data-tour': tourOf(order),
    'data-row-key': key,
    'data-row-end': end,
    'data-dragging': drag?.key === key || undefined,
    tabIndex: 0,
    role: 'listitem' as const,
    'aria-label': label,
    onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.target === e.currentTarget && (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'j')) {
        const to = e.key === 'ArrowUp' ? order - 1 : order + 1
        if (folds.hidden.has(to)) {
          e.preventDefault()
          reveal(to)
          window.setTimeout(() => document.getElementById(`line-${to}`)?.focus(), 0)
          return
        }
      }
      onRowKey(e, order)
    },
    onFocus: (e: React.FocusEvent<HTMLDivElement>) => { if (e.target === e.currentTarget) setFocusedRow(order) },
    onBlur: (e: React.FocusEvent<HTMLDivElement>) => { if (e.target === e.currentTarget) setFocusedRow((f) => (f === order ? null : f)) },
  })

  /** The row's first line: who says it, and where it stands. */
  const whoLine = (who: ReactNode, stamp: ReactNode) => (who || stamp) ? (
    <div className="flex flex-wrap items-center gap-2.5">{who && <span className="who">{who}</span>}{stamp}</div>
  ) : null

  /** The quiet verbs under a line that is in the video: Hear it, Take it out, Edit it. */
  const keptActs = (s: Statement, editId: string, order: number, mode: 'edit' | 'layer', at: number) => (
    <span className="-ml-2 flex flex-wrap items-center gap-0.5" role="group" aria-label={`Added line at ${clock(at)}`}>
      <button type="button" className="act" onClick={() => onSeek(s)}><PlayGlyph />Hear it</button>
      <button type="button" className="act" onClick={() => onUndo(editId)}>Take it out</button>
      <button type="button" className="act" onClick={() => open(order, mode)}>Edit it</button>
    </span>
  )

  const foldButton = (order: number) => folds.after.has(order) && (
    <div className="pl-[112px]" role="listitem" key={`fold-${order}`}>
      <button type="button" className="act -ml-2" onClick={() => setUnfolded((u) => new Set(u).add(order))}>
        <span className="tag">+ {folds.after.get(order)} more lines</span>
      </button>
    </div>
  )

  /** A line's words where they now play, after a shift: its own row, with
   *  where it came from, Undo, Move, and a grip to drag it again. */
  const movedRow = (entry: Extract<Row, { kind: 'moved' }>, order: number) => {
    const { s, rev, from } = entry
    const label = name(s.speaker)
    const key = `moved-${rev.edit_id}`
    return (
      <Fragment key={key}>
        {drag && dropIndexFor(drag.to) === order && dropMarker()}
        <div className={cn(rowClass, asShot && 'opacity-50')} data-state="moved" data-version={version} {...rowProps(order, key, `Moved line at ${clock(rev.start)}${label ? `, ${label}` : ''}`, rev.end)}>
          <span className="flex items-start">
            {rev.edit_id && onMoveKept && gripButton(key, `edit-${rev.edit_id}`, s.text, rev.start, Math.max(0.05, rev.end - rev.start), (t) => onMoveKept(rev.edit_id!, t))}
          </span>
          <button className={timeClass} onClick={() => onSeek({ ...s, start: rev.start, end: rev.end })} aria-label={`Go to ${clock(rev.start)}`}>{clock(rev.start)}</button>
          <div className="flex min-w-0 flex-col gap-1.5">
            {whoLine(label, <>{<StatusBadge status="kept">Moved</StatusBadge>}{asShot && NOT_IN_VERSION}</>)}
            <span className="say">{s.text}</span>
            <div className={metaClass}>
              Moved from {clock(from.start)}, as spoken, over the sound here.
              {rev.edit_id && <> <LinkButton onClick={() => onUndo(rev.edit_id!)}>Undo</LinkButton></>}
            </div>
            {rev.edit_id && onMoveKept && placeControl(`edit-${rev.edit_id}`, rev.start, Math.max(0.05, rev.end - rev.start), (t) => onMoveKept(rev.edit_id!, t))}
          </div>
        </div>
      </Fragment>
    )
  }

  /** An added line that is in the video (20f): its own row at its own time,
   *  however many play at that moment. Hear it, Take it out, Edit it. */
  const layerRow = (entry: Extract<Row, { kind: 'layer' }>, order: number) => {
    const { rev } = entry
    const key = `layer-${rev.edit_id}`
    const s = rowStatement(entry)
    const isEditing = editing?.order === order && editing.mode === 'layer'
    const others = rows.filter((r) => r !== entry && r.kind !== 'moved' && overlaps(r, entry)).length
    const voice = voices.find((v) => v.voice_id === rev.voice_profile_id)?.name
    return (
      <Fragment key={key}>
        {drag && dropIndexFor(drag.to) === order && dropMarker()}
        <div className={cn(rowClass, asShot && 'opacity-50')} data-state="kept" data-version={version} data-current={currentTime >= rev.start && currentTime < rev.end} {...rowProps(order, key, `Added line at ${clock(rev.start)}`, rev.end)}>
          <span className="flex items-start">
            {!isEditing && rev.edit_id && onMoveKept && gripButton(key, `edit-${rev.edit_id}`, rev.text, rev.start, Math.max(0.05, rev.end - rev.start), (t) => onMoveKept(rev.edit_id!, t))}
          </span>
          <button className={timeClass} onClick={() => onSeek(s)} aria-label={`Go to ${clock(rev.start)}`}>{clock(rev.start)}</button>
          <div className="flex min-w-0 flex-col gap-1.5">
            {whoLine(<>+ New line{rev.speaker && name(rev.speaker) ? ` · ${name(rev.speaker)}` : ''}</>, <>{<StatusBadge status="kept" role="status">{STATUS.kept}</StatusBadge>}{asShot && NOT_IN_VERSION}</>)}
            {isEditing ? <div className={unfold}>{editor(s, 'layer')}</div> : (
              <>
                <span className="say">{rev.text}</span>
                <div className={metaClass}>{(MIX_NOTE[rev.mix] ?? 'Over the picture').replace(/^./, (ch) => ch.toUpperCase())}{voice ? ` · ${voice}'s voice` : ''}{others > 0 ? ` · with ${others} other ${others === 1 ? 'line' : 'lines'} at this moment` : ''}</div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 empty:hidden">
                  {rev.edit_id && onMoveKept && placeControl(`edit-${rev.edit_id}`, rev.start, Math.max(0.05, rev.end - rev.start), (t) => onMoveKept(rev.edit_id!, t))}
                  {rev.edit_id && levelControl(rev.level_db, { editId: rev.edit_id })}
                </div>
                {rev.edit_id && keptActs(s, rev.edit_id, order, 'layer', rev.start)}
              </>
            )}
          </div>
        </div>
      </Fragment>
    )
  }

  /** A proposed or working added line (20f): its own row, with its facts and
   *  the four verbs once its take is ready. */
  const itemRow = (entry: Extract<Row, { kind: 'item' }>, order: number) => {
    const { item } = entry
    const key = `item-${item.item_id}`
    const s = rowStatement(entry)
    const isEditing = editing?.order === order && editing.mode === 'layer'
    const c = item.candidate
    const status = STATUS[item.status] ? item.status : null
    const after = statements.filter((st) => st.end <= entry.start + 0.001).at(-1)
    const inDepth = expanded === item.item_id && item.status === 'ready' && !!c
    return (
      <Fragment key={key}>
        {drag && dropIndexFor(drag.to) === order && dropMarker()}
        <div className={rowClass} data-state={status ?? undefined} data-current={currentTime >= entry.start && currentTime < entry.end} data-depth={inDepth || undefined} {...rowProps(order, key, `Proposed line at ${clock(entry.start)}`, entry.end)}>
          <span className="flex items-start">
            {!isEditing && c && onMove && gripButton(key, c.candidate_id, item.new_text, c.plan.selection.start, c.audio.duration, (t) => onMove(item, c, t))}
          </span>
          <button className={timeClass} onClick={() => onSeek(s)} aria-label={`Go to ${clock(entry.start)}`}>{clock(entry.start)}</button>
          <div className={cn('flex min-w-0 flex-col', item.status === 'ready' ? 'gap-2.5' : 'gap-1.5')}>
            {whoLine(<>+ New line{item.speaker && name(item.speaker) ? ` · ${name(item.speaker)}` : ''}</>, status && <StatusBadge status={status} role="status">{STATUS[status]}</StatusBadge>)}
            {isEditing ? <div className={unfold}>{editor(s, 'layer')}</div> : inDepth ? depth(item, c!, s, order, 'layer') : (
              <>
                <span className={cn('say', item.status === 'ready' && 'text-lg')}><ins>{item.new_text}</ins></span>
                <div className={metaClass}>
                  {after && statements.length > 0 ? `New line after ${clock(after.start)}` : 'New line'} · {item.mix === 'concatenate' ? 'the picture makes room' : 'over the picture'}
                </div>
                {item.note && <div className={cn(metaClass, 'text-needs')}>{item.note}</div>}
                <div className={unfold}>{lineBlock(item, item.speaker)}</div>
                {item.status === 'ready' && c && verbs(item, c, order, 'layer')}
                {(item.status === 'needs-you' || item.status === 'failed' || item.status === 'planned') && (
                  <span className="-ml-2 flex"><button type="button" className="act" onClick={() => void run(`discard-${item.item_id}`, () => onDiscard(item))} disabled={disabled || pending !== null}>Discard</button></span>
                )}
              </>
            )}
          </div>
        </div>
      </Fragment>
    )
  }

  /** One spoken line of the transcript, as a row with everything about it inside. */
  const lineRow = (s: Statement, i: number, order: number) => {
    const key = keyOf({ start: s.start, end: s.end })
    const current = currentTime >= s.start && currentTime < s.end
    const selected = !!selection && overlaps(selection, s)
    // The line's own change: a replacement or a removal (an added line is its own row).
    const pending = pendingLines.find((p) => overlaps(p.selection, s) && STATUS[p.status] && !isAdd({ mix: p.mix ?? 'replace' }))
    const live = ownRevisions(s)
    const revision = live.length ? live[live.length - 1] : null
    const removed = revision?.mix === 'remove'
    const movedTo = removed && revision?.partner ? revisions.find((r) => r.edit_id === revision.partner) ?? null : null
    const shown: Revision | null = pending?.text
      ? { start: pending.selection.start, end: pending.selection.end, text: pending.text, mix: pending.mix ?? 'replace' }
      : revision && !removed && !asShot ? revision : null
    const own = ownItem(s)
    // The row's state word comes from the plan's item itself when there is one (20e), so a proposal reads Proposed without the plan's pending list.
    const itemStatus = own && own.status !== 'approved' && own.status !== 'dismissed' && STATUS[own.status] ? own.status : null
    const status: string | null = pending?.status ?? itemStatus ?? (removed ? 'removed' : revision ? 'kept' : null)
    const label = name(s.speaker)
    const isEditing = editing?.order === order && editing.mode === 'edit'
    const isAdding = editing?.order === order && editing.mode === 'add'
    const proposed = own?.status === 'ready' && !!own.candidate
    const inDepth = proposed && expanded === own!.item_id
    // UX-7e: an untouched line shifts; a kept line moves with its take; the rest stay put.
    const mover: { id: string; start: number; duration: number; apply: (to: number) => void } | null =
      !revision && onShift ? { id: `shift-${key}`, start: s.start, duration: Math.max(0.05, s.end - s.start), apply: (t) => onShift(s, t) }
      : revision && !removed && revision.edit_id && onMoveKept ? { id: `edit-${revision.edit_id}`, start: revision.start, duration: Math.max(0.05, revision.end - revision.start), apply: (t) => onMoveKept(revision.edit_id!, t) }
      : null
    const up = mover ? stepTo(key, -1) : null
    const down = mover ? stepTo(key, 1) : null
    const plain = !isEditing && !isAdding && !proposed && !(revision && !removed)
    const stamp = status && STATUS[status] && status !== 'removed' ? <StatusBadge status={status} role="status">{STATUS[status]}</StatusBadge>
      : status === 'removed' ? <StatusBadge status="removed" role="status">{movedTo ? 'Moved away' : 'Removed'}</StatusBadge> : null
    const wordsButton = (
      <button className={cn(lineClass, proposed && 'text-lg')} onClick={() => open(order, 'edit')} title="Change the words" data-testid={shown ? 'revision' : undefined}>
        {(removed && !asShot) || (own?.mix === 'remove' && own.status === 'ready') ? <del>{s.text}</del>
          : shown ? trackedChanges(s, shown, words).map((run, k) => (
            <Fragment key={k}>{k > 0 && ' '}
              {run.kind === 'same' ? <span>{run.text}</span> : run.kind === 'del' ? <del>{run.text}</del> : <ins>{run.text}</ins>}
            </Fragment>
          )) : s.text}
      </button>
    )
    return (
      <Fragment key={`${s.start}-${i}`}>
        {drag && dropIndexFor(drag.to) === order && dropMarker()}
        <div
          className={rowClass}
          data-current={current}
          data-selected={selected}
          data-state={asShot && revision ? undefined : status ?? undefined} data-version={version}
          data-depth={inDepth || undefined}
          data-actions-open={actionsOpen === order || undefined}
          {...rowProps(order, key, `Line at ${clock(s.start)}${label ? `, ${label}` : ''}`, s.end)}
        >
          <span className="flex items-start">
            {mover && !isEditing && !isAdding && gripButton(key, mover.id, s.text, mover.start, mover.duration, mover.apply)}
          </span>
          <button className={timeClass} onClick={() => onSeek(s)} aria-label={`Go to ${clock(s.start)}`}>{clock(s.start)}</button>
          <div className={cn('flex min-w-0 flex-col', proposed ? 'gap-2.5' : 'gap-1.5')}>
            {whoLine(label, <>{stamp}{asShot && revision && NOT_IN_VERSION}</>)}
            {isEditing ? <div className={unfold}>{editor(s, 'edit')}</div> : inDepth ? depth(own!, own!.candidate!, s, order, 'edit') : (
              <>
                {wordsButton}
                {(revision || removed) && !asShot && (
                  <div className={metaClass}>
                    {movedTo ? `Moved to ${timecode(movedTo.start)}; the room's own sound stays here.`
                      : removed ? "Removed. The gap is closed with the room's own sound; the picture is untouched." : `${shown && MIX_NOTE[shown.mix] ? (MIX_NOTE[shown.mix] ?? '').replace(/^./, (ch) => ch.toUpperCase()) : 'In place of the words as shot'}.`}
                  </div>
                )}
                {revision && !removed && revision.edit_id && onMoveKept && (
                  placeControl(`edit-${revision.edit_id}`, revision.start, Math.max(0.05, revision.end - revision.start), (t) => onMoveKept(revision.edit_id!, t))
                )}
                {!revision && onShift && placing?.id === `shift-${key}` && (
                  placeControl(`shift-${key}`, s.start, Math.max(0.05, s.end - s.start), (t) => onShift(s, t))
                )}
                {own?.mix === 'remove' && own.status === 'ready' && (
                  <div className={cn(metaClass, 'text-needs')}>Proposed: these words go, and the room's own sound stays in their place.</div>
                )}
                <div className={unfold}>{lineBlock(own, s.speaker)}</div>
                {proposed && !isAdding && verbs(own!, own!.candidate!, order, 'edit')}
                {revision && !removed && revision.edit_id && !isAdding && keptActs(s, revision.edit_id, order, 'edit', s.start)}
                {removed && revision?.edit_id && !isAdding && (
                  <span className="-ml-2 flex"><button type="button" className="act" onClick={() => onUndo(revision.edit_id!)}>Put it back</button></span>
                )}
                {plain && (
                  <div className="flex items-start gap-1">
                    <span className={actionsClass} role="group" aria-label={`Actions for ${clock(s.start)}`}>
                      <button type="button" className="act" onClick={() => { setActionsOpen(null); onSeek(s) }}><PlayGlyph />Hear it</button>
                      {!removed && <button type="button" className="act" onClick={() => { setActionsOpen(null); open(order, 'edit') }}>Edit it</button>}
                      {!removed && !own && <button type="button" className="act" onClick={() => { setActionsOpen(null); onRemove(s) }}>Discard</button>}
                      <button type="button" className="act" onClick={() => { setActionsOpen(null); open(order, 'add') }}>Add a line after</button>
                      {mover && up !== null && <button type="button" className="act" onClick={() => { setActionsOpen(null); mover.apply(up) }}>Move up</button>}
                      {mover && down !== null && <button type="button" className="act" onClick={() => { setActionsOpen(null); mover.apply(down) }}>Move down</button>}
                      {mover && onPlacing && (
                        <button type="button" className="act" onClick={() => { onPlacing({ id: mover.id, start: mover.start, duration: mover.duration }); setPlaceText(timecode(mover.start)) }}>Shift to a time…</button>
                      )}
                    </span>
                    <button
                      type="button"
                      className="act hidden h-8 w-8 justify-center px-0 text-lg tracking-wide aria-expanded:bg-sunk aria-expanded:text-foreground [@media(hover:none)]:inline-flex"
                      aria-label={`Actions for ${clock(s.start)}`}
                      aria-expanded={actionsOpen === order}
                      onClick={() => setActionsOpen((o) => (o === order ? null : order))}
                    >…</button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
        {isAdding && (
          <div className={rowClass} data-state="adding" role="listitem" aria-label={`New line after ${clock(s.start)}`}>
            <span />
            <span />
            <div className="min-w-0"><div className={unfold}>{editor(s, 'add')}</div></div>
          </div>
        )}
      </Fragment>
    )
  }

  const lastLine = rows.map((r, order) => ({ r, order })).filter(({ r }) => r.kind === 'line').at(-1)?.order ?? null
  const editingAt = editing ? rowStatement(rows[editing.order] ?? rows[0]) : null

  // Volt: the heading — how many lines, how many proposed, how many in the video.
  const inVideo = layerRevisions.length + revisions.filter((r) => !isAdd(r) && !r.partner).length
  const shownRows = rows.map((r, order) => ({ r, order })).filter(({ order }) => !folds.hidden.has(order))

  return (
    <section className="flex min-h-0 flex-col gap-2.5" aria-label="Transcript">
      <div className="flex flex-col gap-1.5 px-1 pt-1">
        <div className="flex flex-wrap items-end gap-3.5">
          <h2 className="disp m-0 text-[26px] leading-none font-bold">Transcript</h2>
          <span className="tag pb-0.5 text-faint">{rows.length} {rows.length === 1 ? 'line' : 'lines'}</span>
          <span className="flex-1" />
          {(proposals.length > 0 || inVideo > 0) && (
            <span className="tag pb-1" role="status" aria-label="Where things stand" data-testid="counts">
              <span className={cn('rounded-[3px] px-1.5 py-px', proposals.length > 0 ? 'bg-volt text-ink' : 'bg-sunk')}>{proposals.length}</span> proposed · {inVideo} in the video
            </span>
          )}
          {proposals.length > 1 && onAddAll && (
            <button type="button" className="btn volt sm shine" onClick={() => void run('add-all', () => onAddAll(proposals))} disabled={disabled || pending !== null} aria-busy={pending === 'add-all' || undefined}>
              <BoltGlyph />{pending === 'add-all' ? 'Adding…' : `Add all ${proposals.length}`}
            </button>
          )}
        </div>
        <span className={hint}>
          {editing && editingAt ? (editing.mode === 'add' ? `Adding a line after ${clock(editingAt.start)}. Esc to cancel.` : `Editing ${clock(editingAt.start)}. Enter to voice it, Esc to cancel.`)
            : pendingLines.some((p) => p.status === 'reading') ? "Voltage is reading. The line it's on is lit."
            : focusedRow !== null ? <span className="whitespace-nowrap max-[960px]:hidden" data-testid="keys"><kbd className={kbd}>↑</kbd><kbd className={kbd}>↓</kbd> move · <kbd className={kbd}>Enter</kbd> edit it · <kbd className={kbd}>␣</kbd> hear it · <kbd className={kbd}>K</kbd> add it · <kbd className={kbd}>⌫</kbd> discard · <kbd className={kbd}>A</kbd> add after · <kbd className={kbd}>S</kbd> shift (or drag ⋮⋮) · <kbd className={kbd}>U</kbd> take it out · <kbd className={kbd}>/</kbd> ask Voltage</span>
            : armedRow !== null && rows[armedRow] ? <span role="status">Press Backspace again to propose removing the line at {clock(rows[armedRow].start)}.</span>
            : proposals.length > 0 ? `${proposals.length === 1 ? 'One line is proposed' : `${proposals.length} lines are proposed`}: hear it, then Add it, Edit it or Discard. Nothing is in the video until you add it.`
            : 'One transcript: what is in the video, and what is proposed. Lines at the same moment play together. Hover a line for Hear it, Edit it, Discard.'}
        </span>
      </div>

      <div role="list" className="flex flex-col gap-1.5" ref={list} onFocusCapture={() => setFocusTick((t) => t + 1)} onBlurCapture={() => setFocusTick((t) => t + 1)} data-focus-tick={focusTick}>
        {shownRows.map(({ r: entry, order }) => (
          <Fragment key={`r-${order}`}>
            {entry.kind === 'moved' ? movedRow(entry, order)
              : entry.kind === 'layer' ? layerRow(entry, order)
              : entry.kind === 'item' ? itemRow(entry, order)
              : lineRow(entry.s, entry.i, order)}
            {foldButton(order)}
          </Fragment>
        ))}
        {drag && dropIndexFor(drag.to) === rows.length && dropMarker()}
        {statements.length > 0 && lastLine !== null && !(editing?.order === lastLine && editing.mode === 'add') && (
          <div className="mt-2 pl-[94px]" role="listitem">
            <button type="button" className="act -ml-2" onClick={() => open(lastLine, 'add')}><span className="tag">+ Add a line</span></button>
          </div>
        )}
        {statements.length === 0 && duration && !placingAnother && (
          <div className="py-1" role="listitem">
            <button type="button" className="btn w-full border-dashed" onClick={() => setPlacingAnother(true)}><span aria-hidden="true">+</span> Add another voice-over</button>
          </div>
        )}
        {statements.length === 0 && duration && placingAnother && (
          <div className={rowClass} data-state="adding" role="listitem" aria-label="New voice-over">
            <span />
            <span />
            <div className="min-w-0">
              <PlaceEditor
                duration={duration} voices={voices} usdPerChar={usdPerChar} disabled={disabled}
                placing={placing} onPlacing={onPlacing} initialStart={Math.min(duration - 1, (rows.at(-1)?.end ?? 0) + 0.3)}
                onHear={(span, request) => { setPlacingAnother(false); onHear(keyOf(span), request) }}
                onCancel={() => setPlacingAnother(false)}
              />
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
