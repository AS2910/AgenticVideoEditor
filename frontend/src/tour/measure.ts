import { useEffect, useState } from 'react'

/** A box in viewport pixels: what the spotlight ring and a tip are placed against. */
export interface Box { left: number; top: number; width: number; height: number }

/** Every element that carries one of the `data-tour` names. */
export function findTargets(names: string[]): HTMLElement[] {
  if (typeof document === 'undefined' || names.length === 0) return []
  const sel = names.map((n) => `[data-tour~="${n}"]`).join(',')
  return Array.from(document.querySelectorAll<HTMLElement>(sel))
}

/** The union of the targets' boxes, padded; null when none is on the page. */
export function measure(names: string[], pad = 6): Box | null {
  const els = findTargets(names)
  if (els.length === 0) return null
  let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity
  for (const el of els) {
    const q = el.getBoundingClientRect()
    if (q.width === 0 && q.height === 0) continue
    l = Math.min(l, q.left); t = Math.min(t, q.top); r = Math.max(r, q.right); b = Math.max(b, q.bottom)
  }
  if (!Number.isFinite(l)) return null
  return { left: l - pad, top: t - pad, width: r - l + pad * 2, height: b - t + pad * 2 }
}

const same = (a: Box | null, b: Box | null) =>
  a === b || (!!a && !!b && a.left === b.left && a.top === b.top && a.width === b.width && a.height === b.height)

/** The targets' box, kept fresh: on resize, on any scroll, and on a cheap
 *  300 ms tick while `active` (the page under a tour keeps changing shape). */
export function useTargetBox(names: string[], active: boolean, pad = 6): Box | null {
  const key = names.join('|')
  const [box, setBox] = useState<Box | null>(() => (active ? measure(names, pad) : null))
  useEffect(() => {
    if (!active) { setBox(null); return }
    const list = key ? key.split('|') : []
    const tick = () => setBox((prev) => { const next = measure(list, pad); return same(prev, next) ? prev : next })
    tick()
    window.addEventListener('resize', tick)
    window.addEventListener('scroll', tick, true)
    const id = window.setInterval(tick, 300)
    return () => { window.removeEventListener('resize', tick); window.removeEventListener('scroll', tick, true); window.clearInterval(id) }
  }, [key, active, pad])
  return box
}

export const reducedMotion = () =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Brings the first target into view before the ring is drawn around it. */
export function revealTargets(names: string[]): void {
  const el = findTargets(names)[0]
  el?.scrollIntoView?.({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'nearest', inline: 'nearest' })
}
