import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { getOnboarding, updateOnboarding } from '../api'
import type { Onboarding } from '../types'

export const EMPTY_ONBOARDING: Onboarding = { tour: { step: 0, finished: false, skipped: false }, tips: [], checklist: [], checklist_hidden: false }

export interface OnboardingApi {
  onboarding: Onboarding
  /** False until the server has answered (or failed); tips wait for it. */
  loaded: boolean
  markTip: (id: string) => void
  markChecklist: (id: string) => void
  hideChecklist: () => void
  setTour: (tour: Onboarding['tour']) => void
}

const noop = () => {}
const DEFAULT: OnboardingApi = { onboarding: EMPTY_ONBOARDING, loaded: true, markTip: noop, markChecklist: noop, hideChecklist: noop, setTour: noop }
const Ctx = createContext<OnboardingApi>(DEFAULT)

/** What this person has met so far. Without a provider: nothing seen, every call a no-op. */
export const useOnboarding = (): OnboardingApi => useContext(Ctx)

const union = (a: string[], b: string[]) => Array.from(new Set([...a, ...b]))

/** Loads `/me/onboarding` once (quietly falling back to nothing seen) and saves
 *  each change through it, optimistically, batched 300 ms at a time. */
export function OnboardingProvider({ children, debounceMs = 300 }: { children: ReactNode; debounceMs?: number }) {
  const [state, setState] = useState<Onboarding>(EMPTY_ONBOARDING)
  const [loaded, setLoaded] = useState(false)
  const pending = useRef<Partial<Onboarding>>({})
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const touched = useRef(false)

  useEffect(() => {
    let live = true
    getOnboarding()
      .then((server) => {
        if (!live) return
        // Anything marked before the answer came stays marked.
        setState((local) => (touched.current ? {
          tour: pending.current.tour ?? server.tour,
          tips: union(server.tips ?? [], local.tips),
          checklist: union(server.checklist ?? [], local.checklist),
          checklist_hidden: (server.checklist_hidden ?? false) || local.checklist_hidden,
        } : { ...EMPTY_ONBOARDING, ...server }))
      })
      .catch(() => { /* nothing seen yet, as far as this session knows */ })
      .finally(() => { if (live) setLoaded(true) })
    return () => { live = false }
  }, [])

  const flush = useCallback(() => {
    timer.current = null
    const change = pending.current
    pending.current = {}
    if (Object.keys(change).length === 0) return
    updateOnboarding(change).catch(() => { /* kept locally; saved with the next change */ pending.current = { ...change, ...pending.current } })
  }, [])
  useEffect(() => () => { if (timer.current) { clearTimeout(timer.current); flush() } }, [flush])

  const change = useCallback((fn: (s: Onboarding) => Onboarding) => {
    touched.current = true
    setState((s) => {
      const next = fn(s)
      if (next === s) return s
      const p = pending.current
      if (next.tips !== s.tips) p.tips = next.tips
      if (next.checklist !== s.checklist) p.checklist = next.checklist
      if (next.checklist_hidden !== s.checklist_hidden) p.checklist_hidden = next.checklist_hidden
      if (next.tour !== s.tour) p.tour = next.tour
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(flush, debounceMs)
      return next
    })
  }, [flush, debounceMs])

  const markTip = useCallback((id: string) => change((s) => (s.tips.includes(id) ? s : { ...s, tips: [...s.tips, id] })), [change])
  const markChecklist = useCallback((id: string) => change((s) => (s.checklist.includes(id) ? s : { ...s, checklist: [...s.checklist, id] })), [change])
  const hideChecklist = useCallback(() => change((s) => (s.checklist_hidden ? s : { ...s, checklist_hidden: true })), [change])
  const setTour = useCallback((tour: Onboarding['tour']) => change((s) => (
    s.tour.step === tour.step && s.tour.finished === tour.finished && s.tour.skipped === tour.skipped ? s : { ...s, tour }
  )), [change])

  const value = useMemo<OnboardingApi>(() => ({ onboarding: state, loaded, markTip, markChecklist, hideChecklist, setTour }), [state, loaded, markTip, markChecklist, hideChecklist, setTour])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
