import { useCallback, useEffect, useState } from 'react'
import type { Me, VoiceAbMethod, VoiceAbPage, VoiceAbScores, VoiceAbTrial } from '../api'
import { getVoiceAb, voiceAbClipUrl, voteVoiceAb } from '../api'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { Shell, SideNav } from './Shell'
import { said } from './fmt'
import { card } from './admin/ui'

const NAME: Record<VoiceAbMethod, string> = { old: 'the old way', new: 'the new way' }
const fixed = (x: number | null | undefined, digits: number, unit = '') => (x == null ? 'not measured' : `${x.toFixed(digits)}${unit}`)

/** Run 5 item 7: blind listening for the voice tone work (`#admin/voice-ab`). Each line: the
 *  original, then A and B, one voiced the old way and one the new, in an order of your own.
 *  Which was which, and the measured scores, show only once you have voted. */
export function AdminVoiceAb({ me }: { me: Me | null }) {
  const [page, setPage] = useState<VoiceAbPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback((run?: string) => {
    setError(null)
    getVoiceAb(run).then(setPage).catch((e) => setError(said(e, 'The trials could not be read.')))
  }, [])
  useEffect(() => { load() }, [load])
  const run = page?.run ?? null

  return (
    <Shell active="settings" me={me} mainClassName="mx-auto flex w-full max-w-[1200px] flex-col gap-8 px-4 pt-10 pb-20 sm:flex-row sm:gap-12 sm:px-6 sm:pt-12">
      <SideNav active="admin" />
      <div className="flex min-w-0 flex-1 flex-col gap-[22px]" data-testid="admin-voice-ab">
        <div className="flex flex-wrap items-baseline gap-3">
          <h1 className="disp rise m-0 text-[40px] leading-none font-bold">Voice A/B</h1>
          <span className="stamp quiet">Internal</span>
        </div>
        <p className="m-0 max-w-[640px] text-muted-foreground">
          Hear the original line, then A and B. One was voiced the old way, one the new way; which is which stays hidden until you vote.{' '}
          <a href={hrefFor({ page: 'admin' })} className="act">Back to Admin</a>
        </p>
        {error && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {error}<button type="button" className="btn sm" onClick={() => load(run ?? undefined)}>Try again</button>
          </div>
        )}
        {!error && !page && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading the trials…</p>}
        {page && !run && <p className="m-0 text-muted-foreground">No trials yet. Run the voice tone eval to make some.</p>}
        {page && run && (
          <>
            <section className={`${card} flex flex-col gap-3`} aria-labelledby="ab-tally-h" data-testid="voice-ab-tally">
              <div className="flex flex-wrap items-baseline gap-2.5">
                <h2 id="ab-tally-h" className="disp m-0 text-[22px] font-bold">Votes so far</h2>
                <span className="tnum text-faint">{run}</span>
              </div>
              <p className="m-0 tnum">
                New way {page.tally.new} · Old way {page.tally.old} · Same {page.tally.same} · from {page.voters} {page.voters === 1 ? 'person' : 'people'}
              </p>
              {page.runs.length > 1 && (
                <div className="flex flex-wrap gap-1.5" role="group" aria-label="Which run">
                  {page.runs.map((r) => (
                    <button key={r} type="button" className={cn('pill', r === run && 'on')} aria-pressed={r === run} onClick={() => load(r)}>{r}</button>
                  ))}
                </div>
              )}
            </section>
            {page.trials.map((t, i) => <Trial key={t.id} run={run} t={t} n={i + 1} onVoted={setPage} />)}
          </>
        )}
      </div>
    </Shell>
  )
}

function Trial({ run, t, n, onVoted }: { run: string; t: VoiceAbTrial; n: number; onVoted: (p: VoiceAbPage) => void }) {
  const [busy, setBusy] = useState<'a' | 'b' | 'same' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const vote = async (choice: 'a' | 'b' | 'same') => {
    setBusy(choice); setError(null)
    try { onVoted(await voteVoiceAb(run, t.id, choice)) } catch (e) { setError(said(e, 'That vote did not save.')) } finally { setBusy(null) }
  }
  const other = (m: VoiceAbMethod): VoiceAbMethod => (m === 'old' ? 'new' : 'old')
  const players: [string, 'original' | 'a' | 'b'][] = [['The original', 'original'], ['A', 'a'], ['B', 'b']]
  return (
    <article className={`${card} flex flex-col gap-3`} aria-labelledby={`ab-${t.id}`} data-testid="voice-ab-trial">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 id={`ab-${t.id}`} className="disp m-0 text-[20px] font-bold">Line {n}</h2>
        {t.voted && <span className="stamp">Voted</span>}
        <span className="tnum text-faint">{t.start.toFixed(2)} to {t.end.toFixed(2)} s</span>
      </div>
      <p className="m-0"><span className="text-muted-foreground">Was:</span> {t.before}</p>
      <p className="m-0"><span className="text-muted-foreground">Now:</span> {t.after}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        {players.map(([label, clip]) => (
          <div key={clip} className="flex min-w-0 flex-col gap-1">
            <span className="font-semibold">{label}</span>
            <audio controls preload="none" src={voiceAbClipUrl(run, t.id, clip)} className="w-full" aria-label={`Line ${n}: ${label === 'The original' ? 'the original' : label}`} />
          </div>
        ))}
      </div>
      {t.voted && t.a_is && t.scores && (
        <div className="flex flex-col gap-2" data-testid="voice-ab-reveal">
          <p className="m-0">A was {NAME[t.a_is]}, B was {NAME[other(t.a_is)]}. You picked {t.choice === 'same' ? 'neither' : t.choice === 'a' ? `A (${NAME[t.a_is]})` : `B (${NAME[other(t.a_is)]})`}.</p>
          <Scores scores={t.scores} />
        </div>
      )}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      <div className="flex flex-wrap items-center gap-2.5" role="group" aria-label={`Line ${n}: which sounds more like the speaker`}>
        <span className="text-muted-foreground">Which sounds more like the speaker, in the same room?</span>
        {(['a', 'b'] as const).map((c) => (
          <button key={c} type="button" className={cn('btn sm', t.choice === c ? 'ink' : 'volt')} aria-pressed={t.choice === c} disabled={!!busy}
            onClick={() => void vote(c)}>{busy === c ? 'Saving…' : c.toUpperCase()}</button>
        ))}
        <button type="button" className={cn('btn sm', t.choice === 'same' && 'ink')} aria-pressed={t.choice === 'same'} disabled={!!busy}
          onClick={() => void vote('same')}>{busy === 'same' ? 'Saving…' : 'Can’t tell'}</button>
      </div>
    </article>
  )
}

function Scores({ scores }: { scores: Record<VoiceAbMethod, VoiceAbScores> }) {
  const rows: [string, (s: VoiceAbScores) => string][] = [
    ['Voice match (SIM-o, higher is closer)', (s) => fixed(s.sim_o, 2)],
    ['Natural (UTMOS, of 5)', (s) => fixed(s.utmos, 2)],
    ['Delivery off the original (lower is closer)', (s) => fixed(s.prosody_distance, 2)],
    ['Loudness off the lines around it', (s) => fixed(s.loudness_delta_db, 1, ' dB')],
    ['Length off the original', (s) => fixed(s.duration_error_s, 2, ' s')],
  ]
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] border-collapse text-[13px]">
        <thead><tr className="text-left text-muted-foreground"><th className="py-1 pr-3 font-normal">Measured</th><th className="py-1 pr-3 font-normal">Old way</th><th className="py-1 font-normal">New way</th></tr></thead>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="border-t border-line"><td className="py-1 pr-3">{label}</td><td className="tnum py-1 pr-3">{value(scores.old)}</td><td className="tnum py-1">{value(scores.new)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
