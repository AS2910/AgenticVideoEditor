import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Bolt } from '../pages/Shell'
import { findTargets, revealTargets, useTargetBox } from './measure'
import type { Box } from './measure'
import { stepTargets } from './types'
import type { Tour, TourCard, TourPhase, TourProgress, TourStep } from './types'

/* ---------- state ---------- */

interface TourState { tour: Tour; phase: TourPhase; index: number; failed: boolean }

export interface TourApi {
  /** The tour on screen, or null. */
  tour: Tour | null
  phase: TourPhase | null
  /** The step on screen (0-based), when the phase is 'step'. */
  index: number
  current: TourStep | null
  /** The host said this step cannot complete: the card offers "Skip this step". */
  failed: boolean
  /** Opens a tour on its welcome card, or at a step (0-based) when it has none or `at` is given. */
  start: (tour: Tour, at?: number) => void
  next: () => void
  back: () => void
  /** Leaves the tour and shows the "Tour skipped" toast. Escape does this. */
  skip: () => void
  /** Closes the done card. */
  finish: () => void
  /** Leaves without a word (the host navigates away). */
  stop: () => void
  /** The host reports an app event; the step waiting on it moves on. */
  notify: (event: string) => void
  fail: () => void
  /** True while the step on screen points at this `data-tour` name. */
  isTarget: (name: string) => boolean
}

const noop = () => {}
const DEFAULT: TourApi = {
  tour: null, phase: null, index: 0, current: null, failed: false,
  start: noop, next: noop, back: noop, skip: noop, finish: noop, stop: noop, notify: noop, fail: noop, isTarget: () => false,
}
const Ctx = createContext<TourApi>(DEFAULT)

/** The tour's state, for the page and for `<TourLayer />`. Without a provider every call is a no-op. */
export const useTour = (): TourApi => useContext(Ctx)

/** The spec's numbering: 0 the welcome card, 1…N the steps, N+1 the done card. */
const progressOf = (s: TourState): TourProgress => ({
  step: s.phase === 'welcome' ? 0 : s.phase === 'done' ? s.tour.steps.length + 1 : s.index + 1,
  finished: s.phase === 'done',
  skipped: s.phase === 'skipped',
})

interface TourProviderProps {
  children: ReactNode
  /** Called as a remembered tour moves (the guided run): save it through onboarding. */
  onProgress?: (p: TourProgress) => void
  /** How long the "Tour skipped" toast stays, in ms. */
  toastMs?: number
}

export function TourProvider({ children, onProgress, toastMs = 6000 }: TourProviderProps) {
  const [state, setState] = useState<TourState | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  const progress = useRef(onProgress)
  progress.current = onProgress

  // The tour reports where it is; the host persists the remembered one.
  const lastReported = useRef<string>('')
  useEffect(() => {
    if (!state?.tour.remember) return
    const p = progressOf(state)
    const key = `${state.tour.id}:${p.step}:${p.finished}:${p.skipped}`
    if (key === lastReported.current) return
    lastReported.current = key
    progress.current?.(p)
  }, [state])

  // Focus goes back to whatever opened the tour once it is gone.
  const wasOn = useRef(false)
  useEffect(() => {
    const on = state !== null && state.phase !== 'skipped'
    if (wasOn.current && !on) { opener.current?.focus?.(); opener.current = null }
    wasOn.current = on
  }, [state])

  // The skipped toast goes by itself.
  useEffect(() => {
    if (state?.phase !== 'skipped') return
    const id = window.setTimeout(() => setState((s) => (s?.phase === 'skipped' ? null : s)), toastMs)
    return () => window.clearTimeout(id)
  }, [state?.phase, toastMs])

  const start = useCallback((tour: Tour, at?: number) => {
    if (typeof document !== 'undefined') opener.current = document.activeElement as HTMLElement | null
    const steps = tour.steps.length
    if (at === undefined && tour.welcome) { setState({ tour, phase: 'welcome', index: 0, failed: false }); return }
    const index = Math.max(0, Math.min(steps - 1, at ?? 0))
    setState(steps ? { tour, phase: 'step', index, failed: false } : tour.done ? { tour, phase: 'done', index: 0, failed: false } : null)
  }, [])
  const next = useCallback(() => setState((s) => {
    if (!s) return s
    if (s.phase === 'welcome') return s.tour.steps.length ? { ...s, phase: 'step', index: 0, failed: false } : s.tour.done ? { ...s, phase: 'done' } : null
    if (s.phase !== 'step') return s
    if (s.index + 1 < s.tour.steps.length) return { ...s, index: s.index + 1, failed: false }
    return s.tour.done ? { ...s, phase: 'done', failed: false } : null
  }), [])
  const back = useCallback(() => setState((s) => {
    if (!s || s.phase !== 'step') return s
    if (s.index > 0) return { ...s, index: s.index - 1, failed: false }
    return s.tour.welcome ? { ...s, phase: 'welcome', failed: false } : s
  }), [])
  const skip = useCallback(() => setState((s) => (s && s.phase !== 'skipped' ? { ...s, phase: 'skipped' } : s)), [])
  const finish = useCallback(() => setState(null), [])
  const stop = useCallback(() => setState(null), [])
  const fail = useCallback(() => setState((s) => (s?.phase === 'step' ? { ...s, failed: true } : s)), [])
  const notify = useCallback((event: string) => {
    if (event === 'failed') { fail(); return }
    setState((s) => {
      if (!s || s.phase !== 'step') return s
      const on = s.tour.steps[s.index]?.advanceOn
      if (typeof on !== 'object' || on.event !== event) return s
      if (s.index + 1 < s.tour.steps.length) return { ...s, index: s.index + 1, failed: false }
      return s.tour.done ? { ...s, phase: 'done', failed: false } : null
    })
  }, [fail])

  const current = state?.phase === 'step' ? (state.tour.steps[state.index] ?? null) : null
  const targets = useMemo(() => stepTargets(current), [current])
  const value = useMemo<TourApi>(() => ({
    tour: state?.tour ?? null, phase: state?.phase ?? null, index: state?.index ?? 0, current, failed: state?.failed ?? false,
    start, next, back, skip, finish, stop, notify, fail, isTarget: (name) => targets.includes(name),
  }), [state, current, targets, start, next, back, skip, finish, stop, notify, fail])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/* ---------- the layer ---------- */

const focusables = (root: HTMLElement) =>
  Array.from(root.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'))

/** Tab stays inside a modal card. */
function trapTab(e: ReactKeyboardEvent<HTMLElement>) {
  if (e.key !== 'Tab') return
  const list = focusables(e.currentTarget)
  if (list.length === 0) return
  const first = list[0], last = list[list.length - 1]
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
}

const Mark = ({ text }: { text: string }) => <span className="rounded-md bg-volt px-2 text-ink">{text}</span>

/** The welcome and done cards: a real modal over a dimmed page. */
function ModalCard({ card, label, onPrimary, primaryHref, onSecondary, bolt }: {
  card: TourCard; label: string; onPrimary: () => void; primaryHref?: string; onSecondary?: () => void; bolt?: boolean
}) {
  const primary = useRef<HTMLButtonElement & HTMLAnchorElement>(null)
  useEffect(() => { primary.current?.focus() }, [])
  const primaryCls = 'btn volt'
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-ink/60 p-4">
      <div role="dialog" aria-modal="true" aria-label={label} onKeyDown={trapTab} className="rise flex w-full max-w-[520px] flex-col gap-4 rounded-xl border-[1.5px] border-ink bg-card p-6 text-foreground shadow-volt-lg sm:p-8">
        {card.tag
          ? <span className="tag text-faint">{card.tag}</span>
          : <span className="wave" aria-hidden="true" style={{ height: 36 }}><i style={{ height: 36 }} /><i style={{ height: 36 }} /><i style={{ height: 36 }} /><i style={{ height: 36 }} /><i style={{ height: 36 }} /></span>}
        <h2 className="disp m-0 text-[32px] leading-[1.02] font-bold sm:text-[40px]">{card.title} {card.mark && <Mark text={card.mark} />}</h2>
        <p className="m-0 text-base text-muted-foreground">{card.body}</p>
        <div className="mt-1.5 flex flex-wrap gap-2.5">
          {primaryHref
            ? <a ref={primary} href={primaryHref} className={primaryCls} onClick={onPrimary}>{bolt && <Bolt />}{card.primary}</a>
            : <button ref={primary} type="button" className={primaryCls} onClick={onPrimary}>{bolt && <Bolt />}{card.primary}</button>}
          {card.secondary && onSecondary && <button type="button" className="btn" onClick={onSecondary}>{card.secondary}</button>}
        </div>
      </div>
    </div>
  )
}

const CARD_W = 340, GAP = 14, EDGE = 16

/** Where the coach card sits against the ring: under it, else over it, else beside it; a sheet on a phone. */
function placeCard(box: Box | null, cardH: number, vw: number, vh: number): CSSProperties {
  if (vw < 640) return { left: EDGE, right: EDGE, bottom: EDGE, width: 'auto' }
  if (!box) return { left: Math.max(EDGE, (vw - CARD_W) / 2), top: Math.max(EDGE, (vh - cardH) / 2), width: CARD_W }
  const clampX = (x: number) => Math.max(EDGE, Math.min(vw - CARD_W - EDGE, x))
  const below = box.top + box.height + GAP
  if (below + cardH <= vh - EDGE) return { left: clampX(box.left), top: below, width: CARD_W }
  const above = box.top - GAP - cardH
  if (above >= EDGE) return { left: clampX(box.left), top: above, width: CARD_W }
  const y = Math.max(EDGE, Math.min(vh - cardH - EDGE, box.top))
  if (box.left + box.width + GAP + CARD_W <= vw - EDGE) return { left: box.left + box.width + GAP, top: y, width: CARD_W }
  if (box.left - GAP - CARD_W >= EDGE) return { left: box.left - GAP - CARD_W, top: y, width: CARD_W }
  return { left: clampX(box.left), bottom: EDGE, width: CARD_W }
}

/** The element the coach card's action presses for the user: a `data-tour-action`
 *  named for the target, else the target itself when it is a control. */
function actionElement(targets: string[]): HTMLElement | null {
  if (typeof document === 'undefined' || targets.length === 0) return null
  for (const t of targets) {
    const named = document.querySelector<HTMLElement>(`[data-tour-action~="${t}"]`)
    if (named) return named
  }
  const el = findTargets(targets)[0]
  return el && (el.matches('button, a[href], input, [role="button"]') ) ? el : null
}

/** The spotlight ring and the dimmed page around it, the coach card, the
 *  welcome and done cards, and the "Tour skipped" toast. Put it once, high in
 *  the tree, inside `<TourProvider>`. */
export function TourLayer() {
  const tour = useTour()
  const { phase, index, current, failed } = tour
  const steps = tour.tour?.steps ?? []
  const targets = useMemo(() => stepTargets(current), [current])
  const box = useTargetBox(targets, phase === 'step')
  const card = useRef<HTMLDivElement>(null)
  const action = useRef<HTMLButtonElement>(null)
  const [pos, setPos] = useState<CSSProperties>({ left: EDGE, bottom: EDGE, width: CARD_W })
  const [actionEl, setActionEl] = useState<HTMLElement | null>(null)

  // Escape leaves. A key the page already handled is left alone.
  useEffect(() => {
    if (!phase) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      e.preventDefault()
      if (phase === 'done') tour.finish()
      else if (phase === 'skipped') tour.stop()
      else tour.skip()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase, tour])

  // Each step: bring its target into view, find what the action presses, move focus to the card.
  useEffect(() => {
    if (phase !== 'step') return
    revealTargets(targets)
    setActionEl(actionElement(targets))
    const id = window.requestAnimationFrame(() => {
      const a = action.current
      if (a && !a.disabled) a.focus()
      else card.current?.focus()
    })
    return () => window.cancelAnimationFrame(id)
  }, [phase, index, targets])
  // The action's element can arrive after the step did (the gate card appears).
  useEffect(() => { if (phase === 'step') setActionEl(actionElement(targets)) }, [phase, targets, box])

  useLayoutEffect(() => {
    if (phase !== 'step') return
    const h = card.current?.offsetHeight ?? 240
    setPos(placeCard(box, h, window.innerWidth, window.innerHeight))
  }, [phase, index, box])

  const t = tour.tour
  if (!phase || !t) return null

  if (phase === 'welcome' && t.welcome) {
    return <ModalCard card={t.welcome} label="Welcome" onPrimary={tour.next} onSecondary={tour.skip} bolt />
  }
  if (phase === 'done' && t.done) {
    const d = t.done
    return <ModalCard card={d} label="Tour finished" primaryHref={d.primaryHref} onPrimary={tour.finish} onSecondary={() => tour.start(t)} />
  }
  if (phase === 'skipped') {
    return (
      <div role="status" className="rise fixed bottom-7 left-1/2 z-50 flex max-w-[calc(100vw-32px)] -translate-x-1/2 flex-wrap items-center gap-3.5 rounded-[10px] border-[1.5px] border-ink bg-ink px-4 py-3 text-ptext shadow-volt">
        <span>Tour skipped. Replay it any time from Help.</span>
        <button type="button" className="btn volt sm" onClick={() => tour.start(t)}>Replay now</button>
        <button type="button" className="act text-pmuted" onClick={tour.stop}>Dismiss</button>
      </div>
    )
  }
  if (phase !== 'step' || !current) return null

  const n = index + 1, total = steps.length
  const waits = typeof current.advanceOn === 'object'
  const actionDisabled = waits && !actionEl
  const onAction = () => {
    if (!waits) { tour.next(); return }
    actionEl?.click()
  }
  const words = [`Step ${n} of ${total}.`, current.title + '.', current.body, current.hint ?? ''].filter(Boolean).join(' ')
  const dim = 'pointer-events-none fixed bg-ink/60'
  const transition = 'transition-[left,top,width,height] duration-[450ms] ease-[cubic-bezier(.2,.8,.2,1)]'

  return (
    <>
      {box && (
        <div aria-hidden="true" className="z-40" data-testid="tour-dim">
          <div className={cn(dim, transition)} style={{ left: 0, top: 0, width: '100vw', height: Math.max(0, box.top) }} />
          <div className={cn(dim, transition)} style={{ left: 0, top: box.top + box.height, width: '100vw', bottom: 0 }} />
          <div className={cn(dim, transition)} style={{ left: 0, top: box.top, width: Math.max(0, box.left), height: box.height }} />
          <div className={cn(dim, transition)} style={{ left: box.left + box.width, top: box.top, right: 0, height: box.height }} />
          <div data-testid="tour-ring" className={cn('rec pointer-events-none fixed z-40 rounded-xl border-2 border-volt', transition)} style={{ left: box.left, top: box.top, width: box.width, height: box.height }} />
        </div>
      )}
      <div role="status" aria-live="polite" className="sr-only">{words}</div>
      <div
        ref={card} role="dialog" aria-label={`Tutorial step ${n} of ${total}`}
        className={cn('fixed z-50 flex flex-col gap-2.5 rounded-xl border-[1.5px] border-ink bg-card p-[18px] text-foreground shadow-volt-lg outline-none', transition)}
        tabIndex={-1}
        style={pos}
      >
        <div className="flex items-center gap-2">
          <span className="tag text-faint">Step {n} of {total}</span>
          <span className="flex-1" />
          <button type="button" className="act h-[26px]" onClick={tour.skip}>Skip tour</button>
        </div>
        <h2 className="disp m-0 text-[22px] leading-[1.15] font-bold">{current.title}</h2>
        <p className="m-0 text-sm text-muted-foreground">{current.body}</p>
        {current.hint && <span className="tag text-foreground">{current.hint}</span>}
        {failed && <p className="m-0 text-sm text-muted-foreground" role="alert">This step did not finish. You can skip it and carry on.</p>}
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <div className="flex gap-1" aria-hidden="true">
            {steps.map((_, i) => <span key={i} className={cn('h-1.5 rounded-[3px] transition-[width] duration-300', i === index ? 'w-[18px] bg-volt' : i < index ? 'w-1.5 bg-volt' : 'w-1.5 bg-line2')} />)}
          </div>
          <span className="flex-1" />
          {(index > 0 || t.welcome) && <button type="button" className="act" onClick={tour.back}>Back</button>}
          {(failed || (waits && !actionEl)) && <button type="button" className="btn sm" onClick={tour.next}>Skip this step</button>}
          <button ref={action} type="button" className="btn volt sm" disabled={actionDisabled} aria-disabled={actionDisabled || undefined} onClick={onAction}>{current.action}</button>
        </div>
      </div>
    </>
  )
}
