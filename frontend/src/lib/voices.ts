import type { Voice } from '../types'

const cap = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** The voices by accent, in the order the accents first appear; one group
 *  (or none known) lists them flat. */
export function byAccent(voices: Voice[]): [string, Voice[]][] {
  const groups = new Map<string, Voice[]>()
  for (const v of voices) {
    const key = v.accent ? cap(v.accent) : 'Other'
    groups.set(key, [...(groups.get(key) ?? []), v])
  }
  return [...groups.entries()]
}
