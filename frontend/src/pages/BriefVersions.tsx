import { Fragment, useEffect, useRef, useState } from 'react'
import type { BriefChange, BriefUpdateRun, BriefUpdateVideo, BriefVersion, ProjectFolder } from '../types'
import type { Me } from '../api'
import { cancelBatch, diffBriefVersions, getBriefUpdate, goBatch, listBriefVersions, startBriefUpdate } from '../api'
import { BatchGate } from './BatchGate'
import { agoLabel, formatRelative } from '../lib/dates'
import { hrefFor } from '../lib/route'
import { cn } from '@/lib/utils'
import { said } from './fmt'
import { editorName } from '../lib/people'

/** A1: "v4 · edited by you, 2 days ago" with History beside it. Nothing before the first save. */
export function BriefMeta({ project, me, open, onHistory }: { project: ProjectFolder; me: Me | null; open: boolean; onHistory: () => void }) {
  if (!project.brief_version) return <span className="tag text-faint" data-testid="brief-meta">No versions yet</span>
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1" data-testid="brief-meta">
      <span className="tag text-muted-foreground">
        v{project.brief_version}
        {project.brief_edited_at ? ` · edited by ${editorName(project.brief_edited_by, me, project.brief_edited_by_name)}, ${agoLabel(project.brief_edited_at)}` : ''}
      </span>
      <button type="button" className="act" aria-expanded={open} onClick={onHistory} data-tour="brief-history">History</button>
    </span>
  )
}

/** The diff between two versions, word by word: removed words struck, added words highlighted. */
export function BriefDiff({ changes }: { changes: BriefChange[] }) {
  if (!changes.some((c) => c.op !== 'same')) return <p className="m-0 text-sm text-muted-foreground">These two versions say the same thing.</p>
  return (
    <p className="m-0 text-[14.5px] leading-[1.6] whitespace-pre-wrap" data-testid="brief-diff">
      {changes.map((c, k) => (
        <Fragment key={k}>{c.op === 'same' ? c.text : c.op === 'removed' ? <del>{c.text}</del> : <ins>{c.text}</ins>}</Fragment>
      ))}
    </p>
  )
}

/** A1: every version of the brief, newest first, and a word diff between any two. */
export function BriefHistory({ projectId, me, current, onClose }: { projectId: string; me: Me | null; current: number | null | undefined; onClose: () => void }) {
  const [versions, setVersions] = useState<BriefVersion[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pair, setPair] = useState<{ a: number; b: number } | null>(null)
  const [changes, setChanges] = useState<BriefChange[] | null>(null)
  const [diffError, setDiffError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    listBriefVersions(projectId).then((r) => {
      if (!live) return
      setVersions(r.versions)
      const newest = r.versions[0]?.version ?? 0
      if (newest) setPair({ a: Math.max(0, newest - 1), b: newest })
    }).catch((e) => { if (live) setError(said(e, 'Could not read the versions.')) })
    return () => { live = false }
  }, [projectId, current])
  useEffect(() => {
    if (!pair) return
    let live = true
    setChanges(null)
    setDiffError(null)
    diffBriefVersions(projectId, pair.a, pair.b).then((r) => { if (live) setChanges(r.changes) }).catch((e) => { if (live) setDiffError(said(e, 'Could not compare them.')) })
    return () => { live = false }
  }, [projectId, pair])

  const pick = (label: string, value: number, set: (v: number) => void, withNone: boolean) => (
    <label className="flex items-center gap-1.5 text-sm">
      <span className="tag text-faint">{label}</span>
      <select className="h-8 rounded-md border-[1.5px] border-line2 bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={value} onChange={(e) => set(Number(e.target.value))} aria-label={`Compare ${label.toLowerCase()}`}>
        {withNone && <option value={0}>No brief</option>}
        {(versions ?? []).map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
      </select>
    </label>
  )

  return (
    <div className="rise flex flex-col gap-2.5 rounded-lg border-[1.5px] border-line2 bg-background p-3" role="region" aria-label="Brief history" data-testid="brief-history">
      <div className="flex items-center gap-2"><span className="disp text-base font-bold">History</span><span className="flex-1" /><button type="button" className="act" onClick={onClose}>Close</button></div>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {!error && versions === null && <p className="m-0 text-sm text-muted-foreground" role="status">Reading the versions…</p>}
      {versions && versions.length === 0 && <p className="m-0 text-sm text-muted-foreground">No versions yet. The first time the brief is saved, it becomes v1.</p>}
      {versions && versions.length > 0 && (
        <>
          <ol className="m-0 flex max-h-44 list-none flex-col overflow-y-auto p-0">
            {versions.map((v) => (
              <li key={v.version} className="flex items-baseline gap-2 border-t border-line py-1.5 first:border-t-0">
                <span className="tnum w-8 flex-none font-semibold">v{v.version}</span>
                <span className="min-w-0 flex-1 truncate text-[13px]" title={v.text}>{v.text || 'Empty'}</span>
                <span className="tag flex-none text-faint">{editorName(v.created_by, me, v.created_by_name)} · {formatRelative(v.created_at)}</span>
              </li>
            ))}
          </ol>
          {pair && (
            <div className="flex flex-col gap-2 border-t-[1.5px] border-line pt-2.5">
              <div className="flex flex-wrap items-center gap-3">
                {pick('From', pair.a, (a) => setPair((p) => (p ? { ...p, a } : p)), true)}
                {pick('To', pair.b, (b) => setPair((p) => (p ? { ...p, b } : p)), false)}
              </div>
              {diffError && <p className="m-0 text-sm text-destructive" role="alert">{diffError}</p>}
              {!diffError && changes === null && <p className="m-0 text-sm text-muted-foreground" role="status">Comparing…</p>}
              {changes && <BriefDiff changes={changes} />}
            </div>
          )}
        </>
      )}
    </div>
  )
}

const OUTCOME_WORD: Record<NonNullable<BriefUpdateVideo['outcome']>, string> = {
  current: 'Up to date', updated: 'Updated', proposed: 'Ready to review', waiting: 'Waiting on you',
}

function rowStamp(v: BriefUpdateVideo): { word: string; tone: string } {
  if (v.status === 'planned') return { word: 'Planned', tone: 'quiet' }
  if (v.status === 'queued') return { word: 'Queued', tone: 'live' }
  if (v.status === 'running') return { word: v.step || 'Working', tone: 'live' }
  if (v.status === 'failed') return { word: 'Failed', tone: 'need' }
  if (v.status === 'cancelled') return { word: 'Stopped', tone: 'quiet' }
  const word = v.outcome ? OUTCOME_WORD[v.outcome] : 'Done'
  return { word, tone: v.outcome === 'proposed' || v.outcome === 'waiting' ? 'need' : 'in' }
}

/** A1: "N videos made with an older brief · Bring up to date", and the run
 *  once it starts: one row per video, oldest brief first, each saying how it
 *  ended and why. Each video is its own Activity job; until the batch turn
 *  (F4) exists they run one after another. `onChanged` reloads the page when
 *  a run finishes, so the cards' chips follow. */
export function StaleLine({ projectId, count, version, onChanged }: { projectId: string; count: number; version: number | null | undefined; onChanged: () => void }) {
  const [run, setRun] = useState<BriefUpdateRun | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)
  // Read again (and poll while running) after a run starts.
  const [tick, setTick] = useState(0)
  const wasRunning = useRef(false)

  useEffect(() => {
    let live = true
    let timer: ReturnType<typeof setTimeout> | null = null
    const read = () => getBriefUpdate(projectId).then((r) => {
      if (!live) return
      setRun(r.run)
      setLoaded(true)
      const running = r.run?.status === 'running'
      if (wasRunning.current && !running) onChanged()
      wasRunning.current = running
      if (running) timer = setTimeout(read, 1500)
    }).catch(() => { if (live) setLoaded(true) })
    void read()
    return () => { live = false; if (timer) clearTimeout(timer) }
  }, [projectId, tick]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setError(null)
    setStarting(true)
    try {
      const r = await startBriefUpdate(projectId)
      setRun(r.run)
      setDismissed(null)
      setTick((t) => t + 1)
    } catch (e) { setError(said(e, 'Could not start bringing them up to date.')) } finally { setStarting(false) }
  }

  // Decision 0: the press opens the normal batch gate; Go runs it, Not yet drops it.
  const [gateBusy, setGateBusy] = useState<'go' | 'cancel' | null>(null)
  const atGate = run?.status === 'gate' && run.gate ? run.gate : null
  const answerGate = async (how: 'go' | 'cancel') => {
    if (!run?.batch_id) return
    setError(null)
    setGateBusy(how)
    try {
      await (how === 'go' ? goBatch(projectId, run.batch_id) : cancelBatch(projectId, run.batch_id))
      if (how === 'cancel') setDismissed(run.run_id)
      setTick((t) => t + 1)
    } catch (e) { setError(said(e, how === 'go' ? 'Could not start bringing them up to date.' : 'Could not drop it.')) } finally { setGateBusy(null) }
  }

  const running = run?.status === 'running'
  const showRun = run && !atGate && (running || dismissed !== run.run_id) && (running || run.to === version)
  if (!loaded && count === 0) return null
  if (!showRun && count === 0) return null
  return (
    <div className="rise flex flex-col gap-2.5 rounded-xl border-[1.5px] border-foreground bg-card p-4" data-testid="stale-line" data-tour="stale-line">
      {atGate && (
        <BatchGate batch={atGate} busy={gateBusy !== null} going={gateBusy === 'go'}
          onGo={() => void answerGate('go')} onCancel={() => void answerGate('cancel')} />
      )}
      {!running && !atGate && count > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="stamp need">Brief changed</span>
          <span className="min-w-0 flex-1 text-sm">
            <strong>{count} {count === 1 ? 'video' : 'videos'}</strong> made with an older brief. Voltage changes only the lines the change touches; a video it does not touch is marked current for free.
          </span>
          <button type="button" className="btn volt sm" onClick={() => void start()} disabled={starting}>{starting ? 'Starting…' : 'Bring up to date'}</button>
        </div>
      )}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {showRun && run && (
        <div className="flex flex-col gap-1.5" role="status" aria-live="polite" data-testid="brief-run">
          <div className="flex items-center gap-2">
            <span className="disp text-base font-bold">{running ? `Bringing ${run.videos.length} ${run.videos.length === 1 ? 'video' : 'videos'} up to v${run.to}` : `Brought up to v${run.to}`}</span>
            <span className="flex-1" />
            {!running && <button type="button" className="act" onClick={() => setDismissed(run.run_id)}>Done</button>}
          </div>
          {run.videos.map((v) => {
            const s = rowStamp(v)
            return (
              <div key={v.video_id} className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 border-t border-line py-1.5" data-testid="brief-run-video">
                <span className={cn('stamp', s.tone)}>{s.word}</span>
                <a className="min-w-0 truncate font-semibold text-foreground" href={hrefFor({ page: 'editor', projectId: v.video_id })}>{v.filename}</a>
                <span className="tag text-faint">from v{v.from}</span>
                {v.why && <span className="w-full text-[13px] text-muted-foreground">{v.why}</span>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
