/** Every date the app shows (bug 2, 2026-10-19): one module, the viewer's
 *  time zone, and "Not recorded" for anything that is not a moment. The API
 *  sends ISO 8601 UTC strings or null; a number (seconds by mistake, or ms),
 *  a boolean, zero or garbage is never turned into 1 Jan 1970. */

export const NOT_RECORDED = 'Not recorded'

/** A moment from whatever arrived, or null when it is not one. */
export function toDate(value: unknown): Date | null {
  if (value === null || value === undefined || typeof value === 'boolean') return null
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null
    // Seconds by mistake: anything below 1e11 cannot be milliseconds of a real date (that is March 1973).
    return new Date(value < 1e11 ? value * 1000 : value)
  }
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value !== 'string' || value.trim() === '') return null
  const t = Date.parse(value)
  return Number.isNaN(t) ? null : new Date(t)
}

interface Opts { timeZone?: string }

/** The calendar parts of a moment in a time zone (the viewer's by default). */
function parts(d: Date, timeZone?: string) {
  const p = new Intl.DateTimeFormat('en-GB', { timeZone, year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
    .formatToParts(d)
  const get = (t: string) => p.find((x) => x.type === t)?.value ?? ''
  return { day: Number(get('day')), month: get('month').replace('.', ''), year: Number(get('year')), hour: get('hour'), minute: get('minute') }
}

/** "19 Oct 2026", or "Not recorded". */
export function formatDate(value: unknown, opts: Opts = {}): string {
  const d = toDate(value)
  if (!d) return NOT_RECORDED
  const p = parts(d, opts.timeZone)
  return `${p.day} ${p.month} ${p.year}`
}

/** "Today · 11:40", "Yesterday", "12 Oct", "4 Mar 2025" — or "Not recorded". */
export function formatRelative(value: unknown, now: Date = new Date(), opts: Opts = {}): string {
  const d = toDate(value)
  if (!d) return NOT_RECORDED
  const p = parts(d, opts.timeZone)
  const n = parts(now, opts.timeZone)
  const dayNumber = (x: { year: number; month: string; day: number }) => Date.UTC(x.year, MONTHS.indexOf(x.month), x.day) / 86_400_000
  const diff = Math.round(dayNumber(n) - dayNumber(p))
  if (diff === 0) return `Today · ${Number(p.hour)}:${p.minute}`
  if (diff === 1) return 'Yesterday'
  return p.year === n.year ? `${p.day} ${p.month}` : `${p.day} ${p.month} ${p.year}`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const LONG_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

/** This month's short and long names, for "of $10 · Oct" and the Usage period. */
export const monthShort = (now: Date = new Date(), opts: Opts = {}) => parts(now, opts.timeZone).month
export const monthLong = (now: Date = new Date(), opts: Opts = {}) => LONG_MONTHS[MONTHS.indexOf(parts(now, opts.timeZone).month)]
