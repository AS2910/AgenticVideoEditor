import type { ActivityJob, PlanItem, RenderIncludes, TurnView } from '../types'

/** One processing model (2026-10-20): what every surface says, worked out
 *  from the jobs alone, so the strip, the rows, the player and the chat can
 *  never disagree. Nothing here invents a number: an estimate shows only when
 *  the server measured one. */

export const isActive = (j: ActivityJob) => j.status === 'queued' || j.status === 'running'
export const isVoice = (j: ActivityJob) => j.kind === 'voice_line'
export const isRender = (j: ActivityJob) => j.kind === 'render_preview' || j.kind === 'export'

/** "about 12 s", "about 2 min"; nothing when there is no estimate (never 0, never negative). */
export function aboutEta(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return null
  const s = Math.max(1, Math.ceil(seconds))
  return s < 60 ? `about ${s} s` : `about ${Math.round(s / 60)} min`
}

/** "just now", "2 min ago", "1 h ago". */
export function ago(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const s = Math.max(0, Math.round((now - t) / 1000))
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

/** Newest first, one record per id (a later update replaces an earlier one). */
export function mergeJob(jobs: ActivityJob[], next: ActivityJob): ActivityJob[] {
  const rest = jobs.filter((j) => j.job_id !== next.job_id)
  return [next, ...rest].sort((a, b) => (b.created_at > a.created_at ? 1 : b.created_at < a.created_at ? -1 : b.job_id.localeCompare(a.job_id, undefined, { numeric: true })))
}

/** The latest job about a line (an item or an edit id), of the given kinds. */
export function latestFor(jobs: ActivityJob[], lineId: string, kinds: (j: ActivityJob) => boolean = isVoice): ActivityJob | null {
  return jobs.find((j) => kinds(j) && j.line_ids.includes(lineId)) ?? null
}

/** "Checking fit" and the like: the voice job's step is the fit check. */
const checking = (j: ActivityJob) => /fit|check/i.test(j.step_label)

// ── Row states ───────────────────────────────────────────────────────────────

export type ChipState = 'original' | 'planned' | 'waiting' | 'queued' | 'voicing' | 'ready' | 'rendering' | 'in-video' | 'removed' | 'failed'
export interface RowChip {
  state: ChipState
  label: string
  /** Failed: why, in a sentence. */
  reason?: string | null
  /** Voicing: 0..1 and the step the job is on. */
  progress?: number
  step?: string
  eta?: string | null
  /** The job behind the chip, for Retry. */
  job?: ActivityJob | null
}

export const CHIP_LABEL: Record<ChipState, string> = {
  original: 'Original', planned: 'Planned', waiting: 'Waiting on you', queued: 'Queued', voicing: 'Voicing',
  ready: 'Ready to hear', rendering: 'Rendering', 'in-video': 'In the video', removed: 'Removed', failed: 'Failed',
}

const carries = (inc: RenderIncludes | null | undefined, ids: (string | null | undefined)[]) =>
  !!inc && ids.some((id) => !!id && (inc.candidate_ids.includes(id) || inc.edit_ids.includes(id) || inc.item_ids.includes(id)))

export interface RowFacts {
  item?: PlanItem | null
  /** A kept edit on the line (in force). */
  editId?: string | null
  candidateId?: string | null
  removed?: boolean
  jobs: ActivityJob[]
  /** What the video now carries: the render playing (the edited one while As shot plays); null when unknown. */
  video?: RenderIncludes | null
  /** True when the video's render is unknown (no render record yet): kept lines count as in it. */
  videoUnknown?: boolean
  /** The render in progress, when there is one. */
  rendering?: RenderIncludes | null
}

/** Exactly one chip per line: Original · Queued · Voicing · Ready to hear · Rendering · In the video · Failed (reason). */
export function rowChip({ item, editId, candidateId, removed, jobs, video, videoUnknown, rendering }: RowFacts): RowChip {
  const chip = (state: ChipState, extra: Partial<RowChip> = {}): RowChip => ({ state, label: CHIP_LABEL[state], ...extra })
  const live = item && item.status !== 'approved' && item.status !== 'dismissed' ? item : null
  if (live) {
    const job = latestFor(jobs, live.item_id)
    if (job?.status === 'running') return chip('voicing', { progress: job.progress, step: job.step_label, eta: aboutEta(job.eta_s), job })
    if (job?.status === 'queued') return chip('queued', { eta: aboutEta(job.eta_s), job })
    if (live.status === 'working') return chip('voicing', { step: live.progress ?? undefined })
    if (live.status === 'failed') {
      return chip('failed', { reason: (job?.status === 'failed' ? job.error_text : null) ?? live.error ?? null, job: job?.status === 'failed' ? job : null })
    }
    if (live.status === 'needs-you') return chip('waiting')
    if (live.status === 'planned') return chip('planned')
    if (live.status === 'ready' && live.candidate) {
      const ids = [live.candidate.candidate_id, live.item_id]
      if (carries(video, ids)) return chip('in-video')
      if (carries(rendering, ids)) return chip('rendering')
      return chip('ready')
    }
  }
  if (editId) {
    const ids = [editId, candidateId]
    const inVideo = carries(video, ids) || (!video && videoUnknown)
    if (inVideo) return chip(removed ? 'removed' : 'in-video')
    if (carries(rendering, ids)) return chip('rendering')
    return chip('ready')
  }
  return chip('original')
}

// ── The turn's step list ─────────────────────────────────────────────────────

export type StepState = 'done' | 'running' | 'todo' | 'failed' | 'skipped'
export interface Step { key: string; label: string; state: StepState }

/** The jobs a turn caused, oldest first. */
export const turnJobs = (jobs: ActivityJob[], turnId: string | null | undefined) =>
  turnId ? jobs.filter((j) => j.turn_id === turnId).slice().reverse() : []

/** [check] Plan ready · [spinner] Voicing line 2 of 5 · [ ] Fit check · [ ] Render preview, updated in place. */
export function turnSteps(turn: TurnView | null, jobs: ActivityJob[]): Step[] {
  if (!turn) return []
  const mine = turnJobs(jobs, turn.turn_id)
  const voices = mine.filter((j) => isVoice(j) && j.status !== 'cancelled')
  const render = mine.filter(isRender).at(-1) ?? null
  const ended = turn.status === 'done' || turn.status === 'failed'
  const doneN = voices.filter((j) => j.status === 'done').length
  const failedN = voices.filter((j) => j.status === 'failed').length
  const running = voices.find((j) => j.status === 'running') ?? null
  const steps: Step[] = []
  steps.push({ key: 'plan', label: voices.length || ended ? 'Plan ready' : 'Planning', state: voices.length || ended ? 'done' : 'running' })
  if (voices.length) {
    const n = voices.length
    const settled = voices.every((j) => !isActive(j))
    const at = Math.min(n, doneN + failedN + 1)
    const label = !settled ? `Voicing line ${at} of ${n}`
      : failedN ? `Voiced ${doneN} of ${n} ${n === 1 ? 'line' : 'lines'}, ${failedN} failed`
      : `Voiced ${n} ${n === 1 ? 'line' : 'lines'}`
    steps.push({ key: 'voice', label, state: !settled ? 'running' : failedN && !doneN ? 'failed' : 'done' })
    const tooLong = voices.filter((j) => j.status === 'failed' && j.error_code === 'too_long').length
    const fit: StepState = settled ? (tooLong ? 'failed' : 'done') : running && checking(running) ? 'running' : doneN ? 'running' : 'todo'
    steps.push({ key: 'fit', label: tooLong && settled ? `Fit check: ${tooLong} too long` : 'Fit check', state: fit })
  }
  if (render) {
    const v = render.detail?.version
    const label = render.status === 'done' ? `Preview${v ? ` v${v}` : ''} ready`
      : render.status === 'failed' ? `Render failed${render.error_text ? `: ${render.error_text}` : ''}`
      : `Render preview${v ? ` v${v}` : ''}${aboutEta(render.eta_s) ? ` · ${aboutEta(render.eta_s)}` : ''}`
    steps.push({ key: 'render', label, state: render.status === 'done' ? 'done' : render.status === 'failed' ? 'failed' : isActive(render) ? 'running' : 'skipped' })
  } else if (voices.length && !ended) {
    steps.push({ key: 'render', label: 'Render preview', state: 'todo' })
  }
  return steps
}

/** "Done. 5 lines voiced, v5 is playing. $0.09 spent." */
export function turnSummary(turn: TurnView, jobs: ActivityJob[], playingVersion: number | null, version = true): string {
  const mine = turnJobs(jobs, turn.turn_id)
  const voiced = mine.filter((j) => isVoice(j) && j.status === 'done').length
  const failed = mine.filter((j) => isVoice(j) && j.status === 'failed').length
  const render = mine.filter(isRender).filter((j) => j.status === 'done').at(-1)
  const v = render?.detail?.version ?? turn.render?.version ?? null
  const bits: string[] = []
  if (voiced) bits.push(`${voiced} ${voiced === 1 ? 'line' : 'lines'} voiced`)
  if (failed) bits.push(`${failed} failed`)
  if (v && version) bits.push(playingVersion === v ? `v${v} is playing` : `v${v} is ready`)
  const head = turn.status === 'failed' ? 'Stopped.' : 'Done.'
  const money = turn.spent_usd != null && turn.spent_usd > 0 ? ` $${turn.spent_usd.toFixed(2)} spent.` : ''
  return `${head}${bits.length ? ` ${bits.join(', ').replace(/^./, (c) => c.toUpperCase())}.` : ''}${money}`
}

// ── The status strip ─────────────────────────────────────────────────────────

export interface StripState {
  busy: boolean
  text: string
  /** The live, polite announcement (the same words, minus the clock). */
  tone: 'idle' | 'busy' | 'failed' | 'ready'
}

export interface StripFacts {
  jobs: ActivityJob[]
  turn: TurnView | null
  /** The version playing and when it was made; null for the video as shot. */
  playing: { version: number; created_at: string } | null
  /** The edit set changed and nothing has started rendering it. */
  stale: boolean
  /** A render just finished and is playing (for "Ready. v4 is playing"). */
  justReady?: boolean
  now?: number
}

/** One line: "Voicing line 2 of 5 · Jeevan · about 12 s" -> "Checking fit" -> "Rendering preview v4" -> "Ready. v4 is playing"; idle: "Up to date · v4 · 2 min ago". */
export function stripState({ jobs, turn, playing, stale, justReady, now }: StripFacts): StripState {
  const active = jobs.filter(isActive)
  const render = active.find(isRender)
  const voice = active.find((j) => isVoice(j) && j.status === 'running') ?? active.find(isVoice)
  if (voice) {
    const peers = voice.turn_id ? jobs.filter((j) => isVoice(j) && j.turn_id === voice.turn_id && j.status !== 'cancelled') : [voice]
    const settledBefore = peers.filter((j) => !isActive(j)).length
    const of = peers.length > 1 ? ` ${Math.min(peers.length, settledBefore + 1)} of ${peers.length}` : ''
    const eta = aboutEta(voice.eta_s)
    if (voice.status === 'running' && checking(voice)) return { busy: true, tone: 'busy', text: of ? `Checking fit · line${of}` : 'Checking fit' }
    const what = voice.status === 'queued' ? (of ? `Line${of} queued` : 'A line is queued') : of ? `Voicing line${of}` : 'Voicing the line'
    const bits = [what, voice.detail?.voice_name, eta].filter(Boolean)
    return { busy: true, tone: 'busy', text: bits.join(' · ') }
  }
  if (render) {
    const v = render.detail?.version
    const eta = aboutEta(render.eta_s)
    return { busy: true, tone: 'busy', text: [`Rendering ${render.kind === 'export' ? 'export' : 'preview'}${v ? ` v${v}` : ''}`, eta].filter(Boolean).join(' · ') }
  }
  // A1: a "bring up to date" job wraps a turn; while the turn runs, its step says more (A2: so does a check's Fix in all).
  const wraps = (j: ActivityJob) => j.kind === 'brief_update' || j.kind === 'check'
  const other = active.find((j) => !wraps(j))
  if (other) return { busy: true, tone: 'busy', text: [other.step_label || 'Working', aboutEta(other.eta_s)].filter(Boolean).join(' · ') }
  if (turn && (turn.status === 'running' || turn.status === 'stopping')) {
    return { busy: true, tone: 'busy', text: turn.status === 'stopping' ? 'Stopping after this step' : turn.step || 'Thinking' }
  }
  const update = active.find(wraps)
  if (update) return { busy: true, tone: 'busy', text: update.step_label || (update.kind === 'check' ? 'Fixing an issue from the project check' : 'Bringing it up to date with the brief') }
  if (stale) return { busy: false, tone: 'idle', text: 'Changes not in preview yet' }
  if (justReady && playing) return { busy: false, tone: 'ready', text: `Ready. v${playing.version} is playing` }
  if (playing) return { busy: false, tone: 'idle', text: ['Up to date', `v${playing.version}`, ago(playing.created_at, now)].filter(Boolean).join(' · ') }
  return { busy: false, tone: 'idle', text: 'Up to date' }
}

// ── Toasts ───────────────────────────────────────────────────────────────────

export interface Toast { id: string; text: string; tone: 'ok' | 'fail'; action?: { label: string; key: string } }

/** One toast at a time, coalesced: several lines ready in one breath read "3 lines ready". */
export function coalesce(prev: Toast | null, next: Toast): Toast {
  if (!prev) return next
  const lines = (t: Toast) => /^(\d+) lines? ready$/.exec(t.text)?.[1]
  const a = lines(prev), b = lines(next)
  if (a && b) { const n = Number(a) + Number(b); return { ...next, text: `${n} lines ready` } }
  const fails = (t: Toast) => /^(\d+) jobs? failed/.exec(t.text)?.[1] ?? (t.tone === 'fail' && /failed/.test(t.text) ? '1' : null)
  if (prev.tone === 'fail' && next.tone === 'fail' && prev.text !== next.text) {
    const n = Number(fails(prev) ?? 1) + Number(fails(next) ?? 1)
    return { ...next, text: `${n} jobs failed. Open Activity to retry.` }
  }
  // A failure is never hidden by good news, and a question with a button ("v5 ready. Switch now?") by plain news.
  if (prev.tone === 'fail' && next.tone === 'ok') return prev
  if (prev.action && !next.action && next.tone === 'ok') return prev
  return next
}
