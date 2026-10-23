import { useEffect, useState } from 'react'
import { getMyFlags } from '../api'

/** The phase flags (Step 0, FLAGS). Later features gate on these names. */
export type Flag =
  | 'projects.consistency'
  | 'projects.batch'
  | 'projects.review'
  | 'projects.reuse'
  | 'projects.check'
  | 'voices.cloning'
  | `golive.${string}`

export interface Flags {
  /** True when the flag is on for you. False while the list is loading or failed. */
  enabled: (flag: Flag) => boolean
  loading: boolean
}

// One read per page load, shared by every component that asks.
let cached: Promise<Set<string>> | null = null

function load(): Promise<Set<string>> {
  if (!cached) {
    cached = getMyFlags().then(
      (names) => new Set(names),
      () => {
        // A failed read means everything stays off; the next mount asks again.
        cached = null
        return new Set<string>()
      },
    )
  }
  return cached
}

/** Whether a flag is on, outside React (G7's track() asks before posting). */
export async function flagOn(flag: Flag): Promise<boolean> {
  return (await load()).has(flag)
}

/** Forget the cached list (tests, and after sign-in changes who you are). */
export function resetFlags(): void {
  cached = null
}

/** Which feature flags are on for the caller, from GET /me/flags. */
export function useFlags(): Flags {
  const [on, setOn] = useState<Set<string> | null>(null)
  useEffect(() => {
    let live = true
    void load().then((names) => {
      if (live) setOn(names)
    })
    return () => {
      live = false
    }
  }, [])
  return { enabled: (flag) => on?.has(flag) ?? false, loading: on === null }
}
