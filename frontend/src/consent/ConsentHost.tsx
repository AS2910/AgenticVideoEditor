import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { getVoiceScopes, listNotifications, setConsentAsker } from '../api'
import { useFlags } from '../flags/useFlags'
import type { NotificationItem } from '../types'
import { AttestationModal } from './AttestationModal'
import { ExportReminder } from './ExportReminder'
import type { ConsentAsk, VoiceScope } from './types'

import { CLEARED, ConsentContext, HELD_POLL_MS, OFF, type ConsentState } from './context'

/** Voice consent V1 step 6: everything the consent screens share, mounted
 *  once around the app. While `voices.cloning_verified` is on it answers the
 *  guard's 409s from any request (the attestation modal, the export reminder:
 *  one at a time, the request tried again once it is confirmed), and reads
 *  the notifications while a held line waits. With the flag off nothing is
 *  installed and nothing shows. */
export function ConsentHost({ children, forceOn }: { children: ReactNode; forceOn?: boolean }) {
  const flags = useFlags()
  const on = forceOn ?? flags.enabled('voices.cloning_verified')
  const [asking, setAsking] = useState<{ ask: ConsentAsk; resolve: (ok: boolean) => void } | null>(null)
  const queue = useRef<{ ask: ConsentAsk; resolve: (ok: boolean) => void }[]>([])
  const [decided, setDecided] = useState<NotificationItem[]>([])
  const [watchers, setWatchers] = useState(0)
  const [scopes, setScopes] = useState<Map<string, VoiceScope>>(new Map())
  const [scopeRound, setScopeRound] = useState(0)
  useEffect(() => {
    if (!on) return
    let live = true
    getVoiceScopes().then((all) => { if (live) setScopes(new Map(all.map((v) => [v.voice_id, v]))) }, () => {})
    return () => { live = false }
  }, [on, scopeRound])
  const scopeOf = useCallback((voiceId: string | null | undefined) => (voiceId ? scopes.get(voiceId) ?? null : null), [scopes])
  const refreshScopes = useCallback(() => setScopeRound((n) => n + 1), [])

  const next = useCallback(() => setAsking(queue.current.shift() ?? null), [])
  useEffect(() => {
    if (!on) return
    setConsentAsker((ask) => new Promise<boolean>((resolve) => {
      queue.current.push({ ask, resolve })
      setAsking((now) => now ?? queue.current.shift() ?? null)
    }))
    const waiting = queue.current
    return () => {
      setConsentAsker(null)
      for (const q of waiting.splice(0)) q.resolve(false)
    }
  }, [on])
  const answer = (ok: boolean) => {
    asking?.resolve(ok)
    next()
  }

  // Held lines: read the notifications now and every so often, while any is on screen.
  useEffect(() => {
    if (!on || watchers === 0) return
    let live = true
    const read = () => {
      listNotifications().then(
        (r) => { if (live) setDecided(r.items.filter((n) => n.kind === 'line_decided')) },
        () => {},   // the bell is off, or the read failed: the line stays held until the next read
      )
    }
    read()
    const timer = window.setInterval(read, HELD_POLL_MS)
    return () => { live = false; window.clearInterval(timer) }
  }, [on, watchers])

  const watchHeld = useCallback(() => {
    setWatchers((n) => n + 1)
    return () => setWatchers((n) => Math.max(0, n - 1))
  }, [])
  const decisionFor = useCallback((videoId: string | null | undefined, text: string | null | undefined) => {
    const words = (text ?? '').trim()
    if (!videoId || !words) return null
    const hit = decided.find((n) => n.video_id === videoId && n.body.trim() === words.slice(0, 300))
    return hit ? { cleared: hit.title.startsWith(CLEARED), title: hit.title } : null
  }, [decided])
  const value = useMemo<ConsentState>(() => (on ? { on, decisionFor, watchHeld, scopeOf, refreshScopes } : OFF), [on, decisionFor, watchHeld, scopeOf, refreshScopes])

  return (
    <ConsentContext.Provider value={value}>
      {children}
      {on && asking?.ask.kind === 'attestation' && (
        <AttestationModal key={asking.ask.facts.voice} facts={asking.ask.facts} onDone={() => answer(true)} onCancel={() => answer(false)} />
      )}
      {on && asking?.ask.kind === 'export' && (
        <ExportReminder key={asking.ask.facts.export_ref} facts={asking.ask.facts} onDone={() => answer(true)} onBack={() => answer(false)} />
      )}
    </ConsentContext.Provider>
  )
}
