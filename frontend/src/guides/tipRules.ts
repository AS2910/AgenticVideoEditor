/** Run 5 item 3: the rules of the tip queue, kept pure so they are tested on their own.
 *
 *  - At most one tip on screen: `pickTip` returns one id or none.
 *  - At most TIPS_PER_SESSION tips per session: a tip counts once it has been on
 *    screen; one already counted may come back in the same session (after a reload,
 *    or when its page opens again) until Got it puts it away.
 *  - A dismissed tip never comes back (the list lives in `/me/onboarding`).
 *  - A session is a stretch of use in this browser with no gap longer than
 *    SESSION_IDLE_MS: reloads and other tabs inside it share the count (it is kept
 *    in localStorage); the first activity after a longer gap starts a new one. */

export const TIPS_PER_SESSION = 2
export const SESSION_IDLE_MS = 30 * 60 * 1000
export const SESSION_KEY = 'voltage-tip-session'

export interface TipSession {
  /** When the session began (ms since epoch). */
  started: number
  /** The last activity seen (ms); a gap longer than SESSION_IDLE_MS ends the session. */
  last: number
  /** The tips that have been on screen in this session, in order. */
  shown: string[]
}

export interface TipRequest {
  id: string
  /** Order of asking: the earlier request goes first. */
  seq: number
  /** Whether the tip has a place to show (a slot on the page, or inline in a dialog). */
  placeable: boolean
}

export const newSession = (now: number): TipSession => ({ started: now, last: now, shown: [] })

/** The session to carry on with: the saved one while it is fresh, else a new one. */
export function rollSession(saved: TipSession | null, now: number): TipSession {
  if (!saved || !(now - saved.last <= SESSION_IDLE_MS) || saved.last > now + SESSION_IDLE_MS) return newSession(now)
  return { ...saved, last: Math.max(saved.last, now) }
}

/** Whether this tip may be on screen within the session's allowance. */
export const withinAllowance = (session: TipSession, id: string): boolean =>
  session.shown.includes(id) || session.shown.length < TIPS_PER_SESSION

/** The one tip to show now, or null: the earliest request that has a place, is not
 *  dismissed and fits the session. Nothing while `paused` (a tour is running). */
export function pickTip({ requests, dismissed, session, paused = false }: {
  requests: TipRequest[]; dismissed: readonly string[]; session: TipSession; paused?: boolean
}): string | null {
  if (paused) return null
  const ordered = [...requests].sort((a, b) => a.seq - b.seq)
  for (const r of ordered) {
    if (!r.placeable || dismissed.includes(r.id)) continue
    if (withinAllowance(session, r.id)) return r.id
  }
  return null
}

/** The session once `id` has been on screen (unchanged when it already counted). */
export const noteShown = (session: TipSession, id: string): TipSession =>
  session.shown.includes(id) ? session : { ...session, shown: [...session.shown, id] }

/** The saved session, or null when there is none or storage is unavailable. */
export function loadSession(): TipSession | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const s = JSON.parse(raw) as Partial<TipSession>
    if (typeof s.started !== 'number' || typeof s.last !== 'number' || !Array.isArray(s.shown)) return null
    return { started: s.started, last: s.last, shown: s.shown.filter((x): x is string => typeof x === 'string') }
  } catch {
    return null
  }
}

/** Saves the session; quietly does nothing where storage is blocked. */
export function saveSession(s: TipSession): void {
  try { window.localStorage.setItem(SESSION_KEY, JSON.stringify(s)) } catch { /* private mode: this page load only */ }
}
