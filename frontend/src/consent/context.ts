import { createContext, useContext } from 'react'
import type { VoiceScope } from './types'

/** What a held line's notification decided (`line_decided`, its body is the line's words). */
export interface HeldDecision { cleared: boolean; title: string }

export interface ConsentState {
  /** `voices.cloning_verified` is on for this person: the consent screens show. */
  on: boolean
  /** The newest decision on a held line of this video with these words, once its notification has come. */
  decisionFor: (videoId: string | null | undefined, text: string | null | undefined) => HeldDecision | null
  /** A held line is on screen: watch the notifications until it is decided. Returns the stop. */
  watchHeld: () => () => void
  /** A voice's scope (GET /voices/scopes), for the "This video only" tag; null for a stock voice. */
  scopeOf: (voiceId: string | null | undefined) => VoiceScope | null
  /** Read the scopes again (after Save to My voices). */
  refreshScopes: () => void
}

export const OFF: ConsentState = { on: false, decisionFor: () => null, watchHeld: () => () => {}, scopeOf: () => null, refreshScopes: () => {} }
export const ConsentContext = createContext<ConsentState>(OFF)

/** Whether the consent screens show, and the held lines' decisions. Off outside a ConsentHost. */
export const useConsent = () => useContext(ConsentContext)

export const CLEARED = 'Your held line was cleared.'
// How often the notifications are read while a held line is on screen.
export const HELD_POLL_MS = 15_000

