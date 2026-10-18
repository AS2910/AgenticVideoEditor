import type { Candidate } from '../types'

/** One fact about a take, for the card's grid and its measured line. */
export interface Fact { label: string; value: string; tone?: 'ok' | 'needs' | 'muted' }

// The sound check's own bars (backend `continuity/measured.py`): what each score wants.
const WANTS = { voice_match: 0.75, naturalness: 3.0, prosody: 0.8, audio_integration: 0.8 } as const
const NAMES = { voice_match: 'SIM-o', naturalness: 'UTMOS', prosody: 'Prosody', audio_integration: 'Room' } as const
const MODELS: Record<string, string> = { eleven_multilingual_v2: 'v2', eleven_v3: 'v3', eleven_v4: 'v4', eleven_v4_turbo: 'v4 turbo' }

const pct = (factor: number) => `${factor >= 1 ? '+' : '−'}${Math.round(Math.abs(factor - 1) * 100)}%`

/** The facts a proposal's card shows (UX-9): the grid — voice and model, the
 *  dials, the fit, the picture — and the measured line, each score against
 *  what it wants, with the reason when the check flagged the take. Only what
 *  was recorded or measured appears; nothing is invented. */
export function takeFacts(c: Candidate, voiceName?: string | null): { grid: Fact[]; measured: Fact[]; flagged: string | null } {
  const plan = c.plan
  const model = plan.model ? (MODELS[plan.model] ?? plan.model) : null
  const dials = plan.voice_settings
    ? Object.entries(plan.voice_settings).map(([k, v]) => `${k === 'similarity_boost' ? 'similarity' : k} ${Number(v).toFixed(2)}`).join(' · ')
    : plan.delivery ? plan.delivery : 'as voiced'
  const fitNotes = (c.fit_notes ?? []).filter((n) => !n.startsWith('nearest') && !n.startsWith('moved') && !n.startsWith('level'))
  const picture = plan.flex && Math.abs(plan.flex - 1) > 0.005 ? `${pct(plan.flex)} flexed` : 'as shot'
  const level = plan.level_db && plan.level_db < 0 ? ` · ${Math.round(plan.level_db)} dB` : ''
  const grid: Fact[] = [
    { label: 'Voice', value: [voiceName ?? null, model].filter(Boolean).join(' · ') || 'the default' },
    { label: 'Dials', value: dials },
    { label: 'Fit', value: fitNotes.length ? fitNotes.join(', ').replace(/^./, (ch) => ch.toUpperCase()) : plan.fit === 'stretch' ? 'Tempo only' : 'Pauses first' },
    { label: 'Picture', value: picture + level },
  ]
  const r = c.continuity
  const measured: Fact[] = (['voice_match', 'naturalness', 'prosody', 'audio_integration'] as const).flatMap((k) => {
    const v = (r as unknown as Record<string, number | null | undefined>)[k]
    if (v == null || !r.measured.includes(k)) return []
    const wants = WANTS[k]
    const digits = k === 'naturalness' ? 1 : 2
    return [{ label: NAMES[k], value: `${NAMES[k]} ${v.toFixed(digits)} · wants ${wants.toFixed(digits)}`, tone: v >= wants ? 'ok' as const : 'needs' as const }]
  })
  const flagged = r.passed ? null : (r.warnings.find((w) => !w.startsWith('Stock voice') && !w.startsWith('Regenerated')) ?? 'Did not pass its check').replace(/\.$/, '')
  return { grid, measured, flagged }
}
