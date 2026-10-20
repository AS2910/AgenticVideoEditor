import type { ProjectTemplate } from '../types'
import { usdShort } from '../pages/fmt'

/** "Priya, a voice that belongs to Diwali 2026" (or "voices that belong"). */
export const belongsTo = (voices: { name: string }[], project: string) =>
  `${voices.map((v) => v.name).join(', ')}, ${voices.length === 1 ? 'a voice that belongs' : 'voices that belong'} to ${project}`

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** What a template carries, as one plain line: "3 rules (1 word) · 2 presets · 1 voice · $20 ceiling". */
export function templateFacts(t: ProjectTemplate): string {
  const s = t.summary
  const parts = [s.brief ? 'Brief' : 'No brief', `${plural(s.rules, 'rule')}${s.words ? ` (${plural(s.words, 'word')})` : ''}`, plural(s.presets, 'preset')]
  if (s.voices) parts.push(plural(s.voices, 'voice'))
  if (s.ceiling_usd) parts.push(`${usdShort(s.ceiling_usd)} ceiling`)
  return parts.join(' · ')
}

