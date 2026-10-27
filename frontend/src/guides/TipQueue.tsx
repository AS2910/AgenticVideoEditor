import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { useOnboarding } from './onboarding'
import { loadSession, noteShown, pickTip, rollSession, saveSession, SESSION_KEY } from './tipRules'
import type { TipSession } from './tipRules'

/** Run 5 item 3: every first-time tip asks this queue before it shows. One tip at a
 *  time, at most two a session, never one Got it has put away, nothing while a tour
 *  runs. A tip shows in a slot: in Voltage's pane in the editor, under the top bar
 *  on the other pages, so it never covers the transcript or the player and never
 *  sits over a control (it takes its own room in the flow). */

export type SlotName = 'pane' | 'top'

export interface TipQueueApi {
  /** The one tip on screen now, or null. */
  active: string | null
  /** Where a tip that is not inline renders: the pane's slot, else the top bar's. */
  slot: HTMLElement | null
  /** Ask for a tip; returns the call that withdraws the ask. */
  request: (id: string, inline: boolean) => () => void
  setSlot: (name: SlotName, el: HTMLElement | null) => void
}

const Ctx = createContext<TipQueueApi | null>(null)

/** The queue, or null outside one (a component rendered on its own in a test). */
export const useTipQueue = (): TipQueueApi | null => useContext(Ctx)

interface Ask { token: number; id: string; inline: boolean }

const ACTIVITY_EVERY_MS = 60_000

export function TipQueueProvider({ children, paused = false }: { children: ReactNode; paused?: boolean }) {
  const { onboarding, loaded } = useOnboarding()
  const counter = useRef(0)
  const [asks, setAsks] = useState<Ask[]>([])
  const [slots, setSlots] = useState<Record<SlotName, HTMLElement | null>>({ pane: null, top: null })
  const [session, setSession] = useState<TipSession>(() => rollSession(loadSession(), Date.now()))

  useEffect(() => { saveSession(session) }, [session])

  // Activity keeps the session going; a gap longer than its idle limit starts a new one.
  useEffect(() => {
    const touch = () => setSession((s) => {
      const now = Date.now()
      const next = rollSession(s, now)
      return next.started === s.started && now - s.last < ACTIVITY_EVERY_MS ? s : next
    })
    const onVisible = () => { if (document.visibilityState === 'visible') touch() }
    // Another tab of the same session counted a tip: take its count.
    const onStorage = (e: StorageEvent) => {
      if (e.key !== SESSION_KEY) return
      const theirs = loadSession()
      if (!theirs) return
      setSession((s) => (theirs.started === s.started
        ? { ...s, last: Math.max(s.last, theirs.last), shown: Array.from(new Set([...s.shown, ...theirs.shown])) }
        : theirs.started > s.started ? theirs : s))
    }
    window.addEventListener('pointerdown', touch, true)
    window.addEventListener('keydown', touch, true)
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener('pointerdown', touch, true)
      window.removeEventListener('keydown', touch, true)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  const request = useCallback((id: string, inline: boolean) => {
    const token = ++counter.current
    setAsks((a) => [...a, { token, id, inline }])
    return () => setAsks((a) => a.filter((x) => x.token !== token))
  }, [])
  const setSlot = useCallback((name: SlotName, el: HTMLElement | null) => {
    setSlots((s) => (s[name] === el ? s : { ...s, [name]: el }))
  }, [])

  const slot = slots.pane ?? slots.top
  const active = loaded
    ? pickTip({ requests: asks.map((a) => ({ id: a.id, seq: a.token, placeable: a.inline || slot !== null })), dismissed: onboarding.tips, session, paused })
    : null

  // A tip counts against the session once it is on screen.
  useEffect(() => {
    if (active) setSession((s) => noteShown(s, active))
  }, [active])

  const value = useMemo<TipQueueApi>(() => ({ active, slot, request, setSlot }), [active, slot, request, setSlot])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** Where tips show: `pane` in Voltage's pane, `top` under the top bar. Takes no
 *  room while empty. */
export function TipSlot({ name, className }: { name: SlotName; className?: string }) {
  const q = useTipQueue()
  const setSlot = q?.setSlot
  const ref = useCallback((el: HTMLDivElement | null) => { setSlot?.(name, el) }, [setSlot, name])
  return <div ref={ref} data-tip-slot={name} className={cn('empty:hidden', className)} />
}
