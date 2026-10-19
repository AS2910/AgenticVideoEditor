import type { Me } from '../api'

/** Money as the pages print it: two places, always. */
export const usd = (n: number) => `$${n.toFixed(2)}`
/** Money in a tag: "$10" when whole, "$2.50" otherwise. */
export const usdShort = (n: number) => (Number.isInteger(n) ? `$${n}` : usd(n))

/** m:ss.t — a time with tenths, as a receipt shows it. */
export function clockTenths(t: number): string {
  const tenths = Math.round(Math.max(0, t) * 10)
  const m = Math.floor(tenths / 600)
  const rest = tenths - m * 600
  return `${m}:${String(Math.floor(rest / 10)).padStart(2, '0')}.${rest % 10}`
}

/** Dates live in one module (bug 2): these names stay for the pages that import them from here. */
export { formatRelative as whenLabel, monthShort, monthLong } from '../lib/dates'

export const greeting = (hour: number) => (hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening')

/** The person's first name, or the part of their email before the @; null when sign-in is off. */
export function firstName(me: Me | null): string | null {
  const n = me?.user?.name?.trim()
  if (n) return n.split(/\s+/)[0]
  const e = me?.user?.email
  return e ? e.split('@')[0] : null
}
export const initialOf = (me: Me | null) => (firstName(me)?.[0] ?? 'V').toUpperCase()

/** One sentence from an API failure, or the fallback. */
export const said = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback)

/** 24 bar heights from the voice id: the same voice always draws the same shape. Decorative. */
export function barsFor(id: string): number[] {
  let seed = 0
  for (let i = 0; i < id.length; i++) seed = (seed * 31 + id.charCodeAt(i)) % 9973
  const k = 0.5 + (seed % 200) / 100
  return Array.from({ length: 24 }, (_, i) => 8 + Math.round(Math.abs(Math.sin((i + 1) * k)) * 26))
}
