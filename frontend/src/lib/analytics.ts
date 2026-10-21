/** G7: the browser's events. `track(name, props)` posts one client-side event to
 *  `POST /analytics/events` when `golive.g7` is on for you; the names are an allow-list
 *  (the server keeps the same list and refuses any other). It never throws and never
 *  waits: an event is never worth a broken click. Off in unit tests unless a test turns it on. */
import { flagOn } from '../flags/useFlags'

export const CLIENT_EVENTS = [
  'line.banned_word_warned',
  'board.opened', 'board.card_moved', 'stage.add_anyway', 'stage.add_cancelled', 'feed.older_loaded',
  'review.link_copied', 'review.turn_started', 'review.page_opened',
  'bin.opened', 'bin.restored',
  'search.opened', 'search.result_opened', 'pin.added', 'pin.removed', 'home.sorted', 'home.filtered',
  'template.dialog_opened', 'template.start_from_picked', 'templates.opened',
  'proposal.discard_reason_given', 'learned.card_opened',
  'import.link_pasted', 'members.opened', 'invite.opened', 'signin.email_requested',
  'bell.opened', 'bell.item_opened',
  'admin.opened', 'billing.opened',
] as const
export type ClientEvent = (typeof CLIENT_EVENTS)[number]

let inTests = false
/** Unit tests: let track() post (it is silent under vitest otherwise). */
export function trackInTests(on: boolean): void { inTests = on }

export function track(name: ClientEvent, props: Record<string, unknown> = {}): void {
  if (import.meta.env.MODE === 'test' && !inTests) return
  if (!(CLIENT_EVENTS as readonly string[]).includes(name)) return
  void (async () => {
    try {
      if (!(await flagOn('golive.g7'))) return
      await fetch('/api/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'voltage' },
        body: JSON.stringify({ name, props }),
        keepalive: true,
      })
    } catch {
      // An event that does not land is dropped.
    }
  })()
}
