import { useEffect, useRef, useState } from 'react'
import type { CheckFixVideo, CheckIssue, CheckIssueKind, CheckPage } from '../types'
import { fixCheckIssue, fixCheckIssueEverywhere, getProjectCheck, ignoreCheckIssue, startProjectCheck } from '../api'
import { agoLabel } from '../lib/dates'
import { go, hrefFor } from '../lib/route'
import { clock } from '../transcript/format'
import { cn } from '@/lib/utils'
import { said } from './fmt'
import { costWord } from '../lib/check'
import { Tip } from '../guides/Tip'

const KIND_WORD: Record<CheckIssueKind, string> = {
  fact: 'Facts', offer: 'Offer names', voice: 'Voices', pronounce: 'Pronunciation', banned: 'Banned word', required_line: 'Required line', loudness: 'Loudness',
}
const FIX_WORD: Record<NonNullable<CheckFixVideo['outcome']>, string> = { updated: 'Fixed', proposed: 'Ready to review', waiting: 'Waiting on you', current: 'Nothing to change' }

function fixStamp(v: CheckFixVideo): { word: string; tone: string } {
  if (v.status === 'queued') return { word: 'Queued', tone: 'live' }
  if (v.status === 'running') return { word: v.step || 'Working', tone: 'live' }
  if (v.status === 'failed') return { word: 'Failed', tone: 'need' }
  if (v.status === 'cancelled') return { word: 'Stopped', tone: 'quiet' }
  return { word: v.outcome ? FIX_WORD[v.outcome] : 'Done', tone: v.outcome === 'proposed' || v.outcome === 'waiting' ? 'need' : 'in' }
}

/** One issue: what disagrees, where (each place opens the editor at its
 *  time, with Fix in this video), then Ignore and Fix in all last. */
function Issue({ issue, busy, onFix, onFixAll, onIgnore }: { issue: CheckIssue; busy: string | null; onFix: (videoId: string) => void; onFixAll: () => void; onIgnore: () => void }) {
  const videos = new Set(issue.places.map((p) => p.video_id))
  return (
    <li className="flex flex-col gap-2 border-t border-line py-3 first:border-t-0 first:pt-1" data-testid="check-issue">
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <span className="stamp need">{KIND_WORD[issue.kind] ?? issue.kind}</span>
        <span className="min-w-0 flex-1 text-sm">{issue.message}</span>
      </div>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {issue.places.map((p, k) => (
          <li key={`${p.video_id}-${k}`} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-md bg-sunk px-2.5 py-1.5" data-testid="check-place">
            <a className="min-w-0 truncate font-semibold text-foreground" href={hrefFor({ page: 'editor', projectId: p.video_id, t: p.t })} title={`Open ${p.filename}${p.t !== null ? ` at ${clock(p.t)}` : ''}`}>
              {p.filename}{p.t !== null && <span className="tnum font-normal text-muted-foreground"> · {clock(p.t)}</span>}
            </a>
            {p.text && <span className="min-w-0 flex-1 truncate text-[13px] text-muted-foreground" title={p.text}>“{p.text}”</span>}
            {!p.text && <span className="flex-1" />}
            <button type="button" className="act" onClick={() => onFix(p.video_id)} disabled={busy !== null} aria-label={`Fix in ${p.filename}`}>
              {busy === `fix-${issue.issue_id}-${p.video_id}` ? 'Starting…' : 'Fix in this video'}
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <button type="button" className="act" onClick={onIgnore} disabled={busy !== null}>{busy === `ignore-${issue.issue_id}` ? 'Ignoring…' : 'Ignore'}</button>
        {videos.size > 1 && <button type="button" className="btn sm" onClick={onFixAll} disabled={busy !== null}>{busy === `all-${issue.issue_id}` ? 'Starting…' : `Fix in all ${videos.size}`}</button>}
      </div>
    </li>
  )
}

/** A2 (projects.consistency): the project check on the project page. "Check
 *  project" with the text pass's price beside it and a free Rules only; the
 *  run is an Activity job (kind "check"), read here while it works; then the
 *  Issues: each names its videos and times, with Fix in this video, Fix in
 *  all (one video after another; with projects.batch, `onFixAll` hands it to
 *  the batch panel, B1) and Ignore.
 *  `briefVersion` reads it again after a brief change (which runs the free
 *  checks on the server). */
export function ProjectCheck({ projectId, briefVersion, onFixAll }: { projectId: string; briefVersion?: number | null; onFixAll?: (issue: CheckIssue) => void }) {
  const [page, setPage] = useState<CheckPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [showIgnored, setShowIgnored] = useState(false)
  const [fixDismissed, setFixDismissed] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const live = useRef(true)

  useEffect(() => {
    live.current = true
    let timer: ReturnType<typeof setTimeout> | null = null
    const read = () => getProjectCheck(projectId).then((p) => {
      if (!live.current) return
      setPage(p)
      setError(null)
      if (p.check?.status === 'running' || p.fix_run?.status === 'running') timer = setTimeout(read, 1500)
    }).catch((e) => { if (live.current) setError(said(e, 'Could not read the project check.')) })
    void read()
    return () => { live.current = false; if (timer) clearTimeout(timer) }
  }, [projectId, briefVersion, tick])

  const act = async (key: string, work: () => Promise<CheckPage | void>, fallback: string) => {
    setBusy(key)
    setNote(null)
    try {
      const next = await work()
      if (next) setPage(next)
      setTick((t) => t + 1)
    } catch (e) { setNote(said(e, fallback)) } finally { setBusy(null) }
  }
  const run = (mode: 'full' | 'rules') => act(`run-${mode}`, () => startProjectCheck(projectId, mode), 'Could not start the check.')
  const ignore = (issue: CheckIssue) => act(`ignore-${issue.issue_id}`, () => ignoreCheckIssue(projectId, issue.issue_id), 'Could not ignore that issue.')
  // B1 (projects.batch): Fix in all opens the batch's gate on the project page instead.
  const fixAll = (issue: CheckIssue) => onFixAll ? onFixAll(issue) : act(`all-${issue.issue_id}`, () => fixCheckIssueEverywhere(projectId, issue.issue_id), 'Could not start fixing it in every video.')
  const fix = async (issue: CheckIssue, videoId: string) => {
    setBusy(`fix-${issue.issue_id}-${videoId}`)
    setNote(null)
    try {
      const r = await fixCheckIssue(projectId, issue.issue_id, videoId)
      go({ page: 'editor', projectId: r.video_id, t: r.t })
    } catch (e) { setNote(said(e, 'Could not start Voltage on that video.')) } finally { setBusy(null) }
  }

  const check = page?.check ?? null
  const running = check?.status === 'running'
  const est = page?.estimate
  const full = est?.available ?? false
  const issues = page?.issues ?? []
  const open = issues.filter((i) => !i.ignored)
  const ignored = issues.filter((i) => i.ignored)
  const fixRun = page?.fix_run ?? null
  const showFix = fixRun && (fixRun.status === 'running' || fixDismissed !== fixRun.run_id)
  const lastAt = running ? check?.previous_finished_at : check?.finished_at

  return (
    <section aria-label="Project check" className="rise flex flex-col gap-3 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="project-check" data-tour="project-check">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="disp m-0 text-xl font-bold">Project check</h2>
        <span className="tag text-faint">Facts, voices, words and loudness across every video</span>
      </div>

      {error && (
        <div className="flex items-center gap-3 text-sm text-destructive" role="alert">
          <span className="flex-1">{error}</span><button type="button" className="btn sm" onClick={() => setTick((t) => t + 1)}>Try again</button>
        </div>
      )}
      {!error && page === null && <p className="m-0 text-sm text-muted-foreground" role="status">Reading the last check…</p>}

      {page && (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="check-run">
            <span className="min-w-0 flex-[1_1_220px] text-[13px] text-muted-foreground" data-testid="check-cost">
              {page.videos === 0 ? 'Add a video to check it.'
                : full ? `The rule checks are free; the text pass reads the transcripts for ${est?.label ?? 'a few cents'}.`
                  : 'Rule checks only, free. No Claude key is set for the text pass.'}
            </span>
            {full && <button type="button" className="btn sm" onClick={() => void run('rules')} disabled={running || busy !== null || page.videos === 0}>{busy === 'run-rules' ? 'Starting…' : 'Rules only'}</button>}
            <button type="button" className="btn volt sm" onClick={() => void run(full ? 'full' : 'rules')} disabled={running || busy !== null || page.videos === 0}>
              {busy === 'run-full' || (busy === 'run-rules' && !full) ? 'Starting…' : full ? `Check project · ${est?.label}` : 'Check project'}
            </button>
          </div>
          {note && <p className="m-0 text-sm text-destructive" role="alert">{note}</p>}

          {running && (
            <div className="flex items-center gap-2.5" role="status" aria-live="polite" data-testid="check-running">
              <span className="stamp live">Checking</span>
              <span className="text-sm">{check?.job?.step_label && check.job.step_label !== 'Queued' ? check.job.step_label : 'Starting the check'}</span>
            </div>
          )}
          {check?.status === 'failed' && (
            <div className="flex items-center gap-3 text-sm text-destructive" role="alert">
              <span className="flex-1">{check.job?.error_text ?? check.error ?? 'The check stopped.'}</span>
              <button type="button" className="btn sm" onClick={() => void run(full && check.mode === 'full' ? 'full' : 'rules')} disabled={busy !== null}>Try again</button>
            </div>
          )}
          {!check && page.videos > 0 && <p className="m-0 text-sm text-muted-foreground">Not checked yet. The check compares what every video says now, from transcripts and added lines, with no new audio.</p>}

          {check && (check.status === 'done' || (running && lastAt)) && (
            <div className={cn('flex flex-col gap-1', running && 'opacity-60')} data-testid="check-issues">
              {open.length === 0 ? (
                <p className="m-0 flex flex-wrap items-baseline gap-x-2" role="status">
                  <span className="disp text-base font-bold">No issues found</span>
                  {lastAt && <span className="text-[13px] text-muted-foreground" data-testid="check-when">{`Checked ${agoLabel(lastAt)}${!running ? `, ${costWord(check.mode, check.cost_usd)}` : ''}.`}</span>}
                </p>
              ) : (
                <>
                  <p className="m-0 flex flex-wrap items-baseline gap-x-2">
                    <span className="disp text-base font-bold">{open.length} {open.length === 1 ? 'issue' : 'issues'}</span>
                    {lastAt && <span className="text-[13px] text-muted-foreground" data-testid="check-when">{`Checked ${agoLabel(lastAt)}${!running ? `, ${costWord(check.mode, check.cost_usd)}` : ''}.`}</span>}
                  </p>
                  {!running && <Tip id="first-project-check" target="project-check" />}
                  <ul className="m-0 flex list-none flex-col p-0">
                    {open.map((i) => <Issue key={i.issue_id} issue={i} busy={busy} onFix={(v) => void fix(i, v)} onFixAll={() => void fixAll(i)} onIgnore={() => void ignore(i)} />)}
                  </ul>
                </>
              )}
              {!running && check.notes.map((n) => <p key={n} className="m-0 text-[13px] text-muted-foreground">{n}</p>)}
              {ignored.length > 0 && (
                <div className="flex flex-col gap-1 border-t border-line pt-2">
                  <button type="button" className="act self-start" aria-expanded={showIgnored} onClick={() => setShowIgnored((s) => !s)}>
                    {ignored.length} ignored {ignored.length === 1 ? 'issue' : 'issues'} · {showIgnored ? 'Hide' : 'Show'}
                  </button>
                  {showIgnored && ignored.map((i) => (
                    <p key={i.issue_id} className="m-0 text-[13px] text-muted-foreground" data-testid="check-ignored">{KIND_WORD[i.kind]}: {i.message} It comes back if these words change.</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {showFix && fixRun && (
            <div className="flex flex-col gap-1.5 border-t-[1.5px] border-line pt-3" role="status" aria-live="polite" data-testid="check-fix-run">
              <div className="flex items-center gap-2">
                <span className="disp text-base font-bold">{fixRun.status === 'running' ? `Fixing in ${fixRun.videos.length} ${fixRun.videos.length === 1 ? 'video' : 'videos'}` : 'Fix in all finished'}</span>
                <span className="flex-1" />
                {fixRun.status !== 'running' && <button type="button" className="act" onClick={() => setFixDismissed(fixRun.run_id)}>Done</button>}
              </div>
              <span className="text-[13px] text-muted-foreground">{fixRun.message}</span>
              {fixRun.videos.map((v) => {
                const s = fixStamp(v)
                return (
                  <div key={v.video_id} className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 border-t border-line py-1.5" data-testid="check-fix-video">
                    <span className={cn('stamp', s.tone)}>{s.word}</span>
                    <a className="min-w-0 truncate font-semibold text-foreground" href={hrefFor({ page: 'editor', projectId: v.video_id })}>{v.filename}</a>
                    {v.why && <span className="w-full text-[13px] text-muted-foreground">{v.why}</span>}
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}
    </section>
  )
}
