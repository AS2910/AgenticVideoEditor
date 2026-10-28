import type { QueueItem } from '../types'

/** Addendum 3.3: the one place a queued card's state is named. The thread's card, Up next's chip
 *  and anything after them (Pause and Stop, the one-state check) read these words from here. The
 *  server's names are `CARD_STATES` in `backend/app/jobs/queue.py`. */
export type QueueCardState = 'queued' | 'running' | 'paused' | 'done' | 'stopped' | 'failed'
export const QUEUE_CARD_STATES: readonly QueueCardState[] = ['queued', 'running', 'paused', 'done', 'stopped', 'failed']
export const QUEUE_STATE_WORD: Record<QueueCardState, string> = {
  queued: 'Queued', running: 'Running', paused: 'Paused', done: 'Done', stopped: 'Stopped', failed: 'Failed',
}
/** The stamp each state wears (globals.css): waiting and running are live, done is in, stopped is quiet,
 *  paused (addendum 3.5: Resume or Stop) and failed wait on you. */
export const QUEUE_STATE_STAMP: Record<QueueCardState, string> = {
  queued: 'live', running: 'live', paused: 'need', done: 'in', stopped: 'quiet', failed: 'need',
}

export const isCardState = (s: string): s is QueueCardState => (QUEUE_CARD_STATES as readonly string[]).includes(s)

/** The words a card shows: the first few of what was typed, "..." when there were more. */
export function firstWords(text: string, n = 6): string {
  const words = text.trim().split(/\s+/).filter(Boolean)
  return words.length <= n ? words.join(' ') : `${words.slice(0, n).join(' ')}...`
}

/** What was typed (a goal's words), else the label the server gave the change. */
export const queuedText = (item: QueueItem) => (typeof item.payload?.text === 'string' && item.payload.text.trim() ? item.payload.text : item.label)

/** "Queued 1 of 2", counted over what still waits, in the order it will run; otherwise the state's word. */
export function queueStateLabel(item: QueueItem, live: QueueItem[]): string {
  if (item.status !== 'queued') return isCardState(item.status) ? QUEUE_STATE_WORD[item.status] : item.status
  const waiting = live.filter((i) => i.status === 'queued')
  const k = waiting.findIndex((i) => i.id === item.id)
  return k < 0 ? QUEUE_STATE_WORD.queued : `Queued ${k + 1} of ${waiting.length}`
}

/** The whole card label: "Queued 1 of 2: Make the opening warmer", "Running: ...". */
export const queueCardLabel = (item: QueueItem, live: QueueItem[]) => `${queueStateLabel(item, live)}: ${firstWords(queuedText(item))}`
