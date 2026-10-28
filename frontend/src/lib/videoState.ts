import type { VideoLock } from '../types'
import { usd } from './money'

/** Addendum 3, items 4 and 5: one state per video, the names every surface reads. The server's
 *  are `VIDEO_STATES` in `backend/app/jobs/pause.py`; a lock held by `pause:<turn>` is Paused. */
export type VideoState = 'ready' | 'working' | 'paused'
export const VIDEO_STATES: readonly VideoState[] = ['ready', 'working', 'paused']
export const VIDEO_STATE_WORD: Record<VideoState, string> = { ready: 'Ready', working: 'Working', paused: 'Paused' }

export const videoState = (lock: VideoLock | null | undefined): VideoState =>
  !lock ? 'ready' : lock.paused || lock.holder.startsWith('pause:') ? 'paused' : 'working'

/** The owner's words (BRIEF2, addendum 3, item 5), with the amount filled in. Cost honesty: both
 *  Pause and Stop say what was spent and that it is still charged, before and after. */
export const spentSoFar = (amount: number) => `Spent so far: ${usd(amount)}`
export const pausedWords = (amount: number) => `Paused. ${usd(amount)} spent so far is still charged. Resume to finish.`
export const stoppedWords = (amount: number) => `Stopped. Nothing in your video changed. ${usd(amount)} spent is still charged.`
