import { useEffect, useRef, useState } from 'react'
import type { LanguageChip, LanguageGate, LanguageSet } from '../types'
import { getLanguages, makeLanguages, pollJob, PollCancelled, stageHold, syncLanguage } from '../api'
import { StageWarning } from './StageWarning'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { usd } from './fmt'

/** B2 (projects.batch): language versions of a master video.
 *
 *  - LanguageDialog: Make language versions. Pick languages and how they are
 *    voiced; the numbers come first (a dry run), the press after them is the
 *    batch's one gate, and one batch turn writes and voices every line.
 *  - LanguageChips: a master's versions as chips (the stacked card, Home).
 *  - SyncChip: a version whose master moved on: "Out of sync with master"
 *    and Sync this change, which runs a turn for only the changed lines. */

type VoiceHandling = 'same' | 'designed'

/** How often a running sync turn is read; and a beat after it ends, so the
 *  server has moved the version's sync marker before the page reads it again. */
const SYNC_POLL_MS = 1500
const SYNC_SETTLE_MS = 400

const VOICE_WORDS: Record<VoiceHandling, [string, string]> = {
  same: ['Same voice in the new language', 'The speaker\'s own or cloned voice, speaking the new language.'],
  designed: ['A designed voice per language', 'Voltage designs one voice for each language that suits the speaker.'],
}

interface LanguageDialogProps {
  videoId: string
  filename: string
  onClose: () => void
  /** The versions were made and their batch started: the project to look at. */
  onMade: (projectId: string | null) => void
  projectId?: string | null
}

export function LanguageDialog({ videoId, filename, onClose, onMade, projectId }: LanguageDialogProps) {
  const [set, setSet] = useState<LanguageSet | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [voice, setVoice] = useState<VoiceHandling>('same')
  const [gate, setGate] = useState<LanguageGate | null>(null)
  const [gateError, setGateError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)

  const load = () => {
    setLoadError(null)
    getLanguages(videoId).then(setSet).catch((e) => setLoadError(e instanceof Error ? e.message : 'Could not read the languages.'))
  }
  useEffect(load, [videoId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  useEffect(() => { box.current?.querySelector<HTMLElement>('input, button')?.focus() }, [set])
  // The gate's numbers for what is picked, read again on every change.
  useEffect(() => {
    setGate(null)
    setGateError(null)
    if (picked.length === 0 || !set?.in_project) return
    let live = true
    makeLanguages(videoId, { languages: picked, voice, dry_run: true })
      .then((r) => { if (live) setGate(r.gate) })
      .catch((e) => { if (live) setGateError(e instanceof Error ? e.message : 'Could not work out the cost.') })
    return () => { live = false }
  }, [picked, voice, videoId, set?.in_project])

  const toggle = (code: string) => setPicked((p) => (p.includes(code) ? p.filter((c) => c !== code) : [...p, code]))
  const make = async () => {
    setBusy(true)
    setError(null)
    try {
      await makeLanguages(videoId, { languages: picked, voice })
      onMade(projectId ?? null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not make the language versions.')
    } finally { setBusy(false) }
  }

  const facts = gate ? [
    `${gate.videos} ${gate.videos === 1 ? 'version' : 'versions'}`,
    `${gate.lines} ${gate.lines === 1 ? 'line' : 'lines'}`,
    ...(gate.est_usd != null ? [`about ${usd(gate.est_usd)}`] : []),
  ].join(' · ') : null

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/60 p-4" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={box} role="dialog" aria-modal="true" aria-label="Make language versions" className="rise flex max-h-[90dvh] w-full max-w-[560px] flex-col gap-4 overflow-y-auto rounded-xl border-[1.5px] border-ink bg-card p-6 shadow-volt-lg sm:px-7" data-testid="language-dialog">
        <div className="flex flex-col gap-0.5">
          <span className="tag text-faint">Make language versions</span>
          <span className="disp truncate text-[26px] font-bold" title={filename}>{filename}</span>
          <span className="text-muted-foreground">Each language is its own video linked to this one. Voltage translates and voices every line to fit its time; brand names stay as written.</span>
        </div>

        {!set && !loadError && <p className="m-0 text-muted-foreground" role="status">Reading the languages…</p>}
        {loadError && (
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            <span className="flex-1">{loadError}</span><button type="button" className="btn sm" onClick={load}>Try again</button>
          </div>
        )}
        {set && !set.in_project && (
          <p className="m-0 rounded-lg bg-sunk p-3 text-sm" data-testid="language-needs-project">Language versions are made inside a project, so they share its words and brand names. Move this video into a project first.</p>
        )}
        {set && set.in_project && (
          <>
            <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
              <legend className="tag mb-2 text-faint">Languages · this video is in {set.original_label ?? set.original}</legend>
              {set.options.map((o) => (
                <label key={o.code} className={cn('flex min-h-11 items-center gap-3 rounded-[10px] border-[1.5px] px-3.5 py-2.5', o.made ? 'border-line bg-sunk text-muted-foreground' : picked.includes(o.code) ? 'border-ink bg-volt text-ink' : 'border-line2 bg-card hover:border-foreground')}>
                  <input type="checkbox" className="size-4 accent-current focus-visible:ring-[3px] focus-visible:ring-ring/50" checked={picked.includes(o.code)} disabled={o.made} onChange={() => toggle(o.code)} />
                  <span className="flex-1 font-semibold">{o.label}</span>
                  {o.made && <span className="stamp in">Made</span>}
                </label>
              ))}
            </fieldset>
            <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
              <legend className="tag mb-2 text-faint">Voices</legend>
              {(['same', 'designed'] as const).map((v) => (
                <label key={v} className={cn('flex min-h-11 items-start gap-3 rounded-[10px] border-[1.5px] px-3.5 py-2.5', voice === v ? 'border-ink bg-sunk' : 'border-line2 bg-card hover:border-foreground')}>
                  <input type="radio" name="voice-handling" className="mt-1 size-4 accent-current" checked={voice === v} onChange={() => setVoice(v)} />
                  <span className="flex flex-col"><span className="font-semibold">{VOICE_WORDS[v][0]}</span><span className="text-[13px] text-muted-foreground">{VOICE_WORDS[v][1]}</span></span>
                </label>
              ))}
            </fieldset>
            <div className="flex flex-col gap-1 rounded-lg bg-sunk p-3" role="status" data-testid="language-gate">
              {picked.length === 0 && <span className="text-sm text-muted-foreground">Pick a language to see what it costs.</span>}
              {picked.length > 0 && !gate && !gateError && <span className="text-sm text-muted-foreground">Working out the cost…</span>}
              {gateError && <span className="text-sm text-destructive">{gateError}</span>}
              {gate && facts && (
                <>
                  <span className="tnum font-semibold">{facts}</span>
                  <span className="text-[13px] text-muted-foreground">You pay at most {usd(gate.cap_usd)} for all of them. Each new line waits as a proposal until you add it.</span>
                </>
              )}
            </div>
          </>
        )}
        {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</div>}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Not now</button>
          {set?.in_project && (
            <button type="button" className="btn volt" onClick={() => void make()} disabled={busy || picked.length === 0 || !gate}>
              {busy ? 'Starting…' : picked.length === 0 ? 'Make versions' : `Make ${picked.length} ${picked.length === 1 ? 'version' : 'versions'}`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/** A master's versions as chips; each opens its version, an out-of-step one is marked. */
export function LanguageChips({ languages, className }: { languages: LanguageChip[]; className?: string }) {
  if (languages.length === 0) return null
  return (
    <span className={cn('flex flex-wrap gap-1.5', className)} data-testid="language-chips">
      {languages.map((l) => (
        <a key={l.video_id} href={hrefFor({ page: 'editor', projectId: l.video_id })}
          className={cn('stamp whitespace-nowrap no-underline', l.out_of_sync ? 'need' : 'in')}
          title={l.out_of_sync ? `${l.label}: out of sync with master` : `${l.label}: in step with master`}
          aria-label={`${l.label} version${l.out_of_sync ? ', out of sync with master' : ''}`}>
          {l.label}{l.out_of_sync ? ' · Out of sync' : ''}
        </a>
      ))}
    </span>
  )
}

/** A version whose master shipped a change since it last synced. "Syncing the
 *  changed lines…" stays only while the sync turn runs (its job is polled);
 *  when it ends `onSettled` reads the video again, and a failed sync says why. */
export function SyncChip({ videoId, onStarted, onSettled, compact }: { videoId: string; onStarted?: () => void; onSettled?: (ok: boolean) => void; compact?: boolean }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [started, setStarted] = useState(false)
  const gone = useRef(false)
  useEffect(() => { gone.current = false; return () => { gone.current = true } }, [])
  const [hold, setHold] = useState<string | null>(null)
  const sync = async (confirmStage = false) => {
    setBusy(true)
    setError(null)
    setHold(null)
    let jobId: string
    try {
      jobId = (await syncLanguage(videoId, confirmStage)).job_id
      setStarted(true)
      onStarted?.()
    } catch (e) {
      // Decision 0: syncing an Approved version takes it back to Draft; ask once.
      const held = stageHold(e)
      if (held) { setHold(held.message); return }
      setError(e instanceof Error ? e.message : 'Could not start the sync.')
      return
    } finally { setBusy(false) }
    try {
      const done = await pollJob(jobId, { intervalMs: SYNC_POLL_MS, timeoutMs: 60 * 60_000, shouldStop: () => gone.current })
      if (gone.current) return
      if (done.status === 'succeeded') await new Promise((resolve) => setTimeout(resolve, SYNC_SETTLE_MS))
      if (gone.current) return
      setStarted(false)
      if (done.status === 'failed') setError(done.error ? `The sync did not finish. ${done.error}` : 'The sync did not finish. Try again.')
      onSettled?.(done.status === 'succeeded')
    } catch (e) {
      if (e instanceof PollCancelled || gone.current) return
      setStarted(false)
      setError('Lost track of the sync. Reload to see where it stands.')
      onSettled?.(false)
    }
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="out-of-sync" data-tour="out-of-sync">
      <span className="stamp need whitespace-nowrap" title="The master shipped a change since this version last synced">Out of sync with master</span>
      {started ? <span className="tag text-faint" role="status">Syncing the changed lines…</span> : (
        <button type="button" className={cn('btn sm', compact && 'h-7')} onClick={() => void sync()} disabled={busy}>{busy ? 'Starting…' : 'Sync this change'}</button>
      )}
      {error && <span className="text-[13px] text-destructive" role="alert">{error}</span>}
      {hold && <StageWarning message={hold} anyway="Change anyway" busy={busy} onCancel={() => setHold(null)} onAnyway={() => void sync(true)} />}
    </span>
  )
}
