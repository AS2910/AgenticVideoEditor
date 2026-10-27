import { useEffect, useRef, useState } from 'react'
import type { BatchExport as BatchExportRun, ExportFile, ExportPreset, Preflight } from '../types'
import { exportFileUrl, exportZipUrl, getExportPreflight, listBatchExports, revokeShare, shareBatchExport, startBatchExport } from '../api'
import { hrefFor } from '../lib/route'
import { formatDate } from '../lib/dates'
import { cn } from '@/lib/utils'
import { said } from './fmt'
import { FillBar } from './bits'
import { Tip } from '../guides/Tip'
import { fileSize } from '../lib/exports'

const STAMP: Record<ExportFile['state'], string> = { queued: 'live', rendering: 'live', retrying: 'need', ready: 'in', failed: 'need' }

/** The export's link to its files: Copy link, when it expires, Turn off. */
function ShareLine({ projectId, run, onChange }: { projectId: string; run: BatchExportRun; onChange: () => void }) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const share = run.share
  const act = async (fn: () => Promise<unknown>, fallback: string) => {
    setBusy(true)
    setNote(null)
    try { await fn(); onChange() } catch (e) { setNote(said(e, fallback)) } finally { setBusy(false) }
  }
  const copy = async (url: string) => {
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1800) } catch { setNote('Could not copy. Select the link and copy it.') }
  }
  return (
    <div className="flex flex-col gap-1.5" data-testid="export-share">
      {share ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <input readOnly className="tnum h-8 min-w-0 flex-[1_1_220px] rounded-md border-[1.5px] border-line2 bg-background px-2 text-xs outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" value={share.url} aria-label="Share link" onFocus={(e) => e.currentTarget.select()} />
            <button type="button" className="btn sm" onClick={() => void copy(share.url)}>{copied ? 'Copied' : 'Copy link'}</button>
          </div>
          <span className="text-[13px] text-muted-foreground">
            Anyone with the link can watch and download these files, no account needed, until {formatDate(share.expires_at)}.{' '}
            <button type="button" className="act inline p-0" disabled={busy} onClick={() => void act(() => revokeShare(projectId, share.share_id), 'Could not turn the link off.')}>{busy ? 'Turning off…' : 'Turn off the link'}</button>
          </span>
        </>
      ) : (
        <button type="button" className="btn sm self-start" disabled={busy || run.counts.ready === 0} onClick={() => void act(() => shareBatchExport(projectId, run.export_id), 'Could not make a link.')}>{busy ? 'Making a link…' : 'Share link'}</button>
      )}
      {note && <p className="m-0 text-sm text-destructive" role="alert">{note}</p>}
    </div>
  )
}

/** One file: its state, the preset and video, then the file name and Download, or why it failed. */
function FileRow({ projectId, exportId, f }: { projectId: string; exportId: string; f: ExportFile }) {
  return (
    <li className="flex flex-col gap-0.5 border-t border-line py-2 first:border-t-0" data-testid="export-file" data-state={f.state}>
      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
        <span className={cn('stamp', STAMP[f.state])}>{f.label}</span>
        <span className="min-w-0 flex-1 truncate text-sm"><span className="font-semibold">{f.preset.name}</span> · <a className="text-foreground" href={hrefFor({ page: 'editor', projectId: f.video_id })}>{f.filename}</a></span>
        {!f.approved && <span className="stamp need" title="Not Approved when it was exported">Not approved</span>}
        {f.file && <a className="act" href={exportFileUrl(projectId, exportId, f.index, true)} download={f.file.name} aria-label={`Download ${f.file.name}`}>Download</a>}
      </div>
      {f.file && <span className="tnum truncate text-xs text-faint" title={f.file.name}>{f.file.name} · {fileSize(f.file.size)} · {f.file.report.framing}</span>}
      {f.why && <span className="text-[13px] text-muted-foreground">{f.why}</span>}
    </li>
  )
}

/** B3 (projects.batch): export videos with presets. Pick videos (Approved
 *  ticked by default; others can be picked and are flagged Not approved)
 *  and presets, see the project check's warnings (never a block), Export;
 *  then one row per file, a bar for the whole export, Download all (.zip)
 *  and a share link. `presets` comes from the Presets section. */
export function BatchExport({ projectId, presets }: { projectId: string; presets: ExportPreset[] | null }) {
  const [pre, setPre] = useState<Preflight | null>(null)
  const [run, setRun] = useState<BatchExportRun | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [videos, setVideos] = useState<Set<string> | null>(null)
  const [chosen, setChosen] = useState<Set<number> | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const live = useRef(true)

  useEffect(() => {
    live.current = true
    let timer: ReturnType<typeof setTimeout> | null = null
    const read = () => Promise.all([getExportPreflight(projectId), listBatchExports(projectId)]).then(([p, r]) => {
      if (!live.current) return
      setPre({ videos: p.videos ?? [], warnings: p.warnings ?? [] })
      const latest = r.exports?.[0] ?? null
      setRun(latest)
      setLoaded(true)
      setError(null)
      if (latest?.phase === 'running') timer = setTimeout(read, 1500)
    }).catch((e) => { if (live.current) { setLoaded(true); setError(said(e, 'Could not read the exports.')) } })
    void read()
    return () => { live.current = false; if (timer) clearTimeout(timer) }
  }, [projectId, tick])

  const all = pre?.videos ?? []
  const picked = videos ?? new Set(all.filter((v) => v.approved).map((v) => v.video_id))
  const list = presets ?? []
  const using = chosen ?? new Set(list.slice(0, 1).map((p) => p.preset_id))
  const usable = list.filter((p) => using.has(p.preset_id))
  const flip = <T,>(set: Set<T>, x: T) => { const next = new Set(set); if (next.has(x)) next.delete(x); else next.add(x); return next }
  const notApproved = all.filter((v) => picked.has(v.video_id) && !v.approved)
  const files = picked.size * usable.length

  const start = async () => {
    setBusy(true)
    setNote(null)
    try {
      const made = await startBatchExport(projectId, { video_ids: all.filter((v) => picked.has(v.video_id)).map((v) => v.video_id), preset_ids: usable.map((p) => p.preset_id) })
      setRun(made)
      setDismissed(null)
      setTick((t) => t + 1)
    } catch (e) { setNote(said(e, 'Could not start the export.')) } finally { setBusy(false) }
  }

  const showing = run && dismissed !== run.export_id ? run : null
  const running = showing?.phase === 'running'

  return (
    <section aria-label="Export videos" className="rise flex flex-col gap-3 rounded-xl border-[1.5px] border-foreground bg-card p-[18px]" data-testid="batch-export" data-tour="batch-export">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="disp m-0 text-xl font-bold">Export videos</h2>
        <span className="tag text-faint">A file per video and preset</span>
      </div>
      {error && (
        <div className="flex items-center gap-3 text-sm text-destructive" role="alert">
          <span className="flex-1">{error}</span><button type="button" className="btn sm" onClick={() => setTick((t) => t + 1)}>Try again</button>
        </div>
      )}
      {!error && !loaded && <p className="m-0 text-sm text-muted-foreground" role="status">Reading the exports…</p>}

      {loaded && pre && !showing && (all.length === 0 ? <p className="m-0 text-[13px] text-muted-foreground" data-testid="export-empty">Add videos to this project, then export them here.</p> : (
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); void start() }} data-testid="export-pick">
          <fieldset className="m-0 flex flex-col gap-0.5 border-0 p-0">
            <legend className="tag mb-1 text-faint">{picked.size} of {all.length} videos · Approved ones are picked</legend>
            {all.map((v) => (
              <label key={v.video_id} className="flex cursor-pointer items-center gap-2.5 rounded-md px-1.5 py-1 hover:bg-sunk" data-testid="export-video">
                <input type="checkbox" className="size-4 accent-volt" checked={picked.has(v.video_id)} onChange={() => setVideos(flip(picked, v.video_id))} />
                <span className="min-w-0 flex-1 truncate text-sm">{v.filename}</span>
                {v.approved ? <span className="tag text-muted-foreground">{v.stage_label}</span> : <span className="stamp need" title={`Stage: ${v.stage_label}`}>Not approved</span>}
              </label>
            ))}
          </fieldset>
          <div className="flex flex-col gap-1">
            <span className="tag text-faint" id="export-presets-pick">Presets</span>
            {list.length === 0 ? <span className="text-[13px] text-muted-foreground">Add a preset first.</span> : (
              <div className="flex flex-wrap gap-2" role="group" aria-labelledby="export-presets-pick">
                {list.map((p) => <button key={p.preset_id} type="button" className="pill" aria-pressed={using.has(p.preset_id)} onClick={() => setChosen(flip(using, p.preset_id))}>{p.name}</button>)}
              </div>
            )}
          </div>
          {(pre.warnings.length > 0 || notApproved.length > 0) && (
            <div className="flex flex-col gap-1 rounded-lg border-[1.5px] border-dashed border-warn bg-sunk p-2.5" data-testid="export-warnings">
              <span className="text-sm font-semibold">Before you export</span>
              {notApproved.length > 0 && <span className="text-[13px]">{notApproved.length === 1 ? `${notApproved[0].filename} is not approved yet.` : `${notApproved.length} videos are not approved yet.`}</span>}
              {pre.warnings.map((w) => <span key={w.fingerprint} className="text-[13px]" data-testid="export-warning">{w.message}</span>)}
              <span className="text-[13px] text-muted-foreground">These are warnings. You can still export.</span>
            </div>
          )}
          {note && <p className="m-0 text-sm text-destructive" role="alert">{note}</p>}
          <button type="submit" className="btn volt sm self-end" disabled={busy || files === 0}>{busy ? 'Starting…' : `Export ${files} ${files === 1 ? 'file' : 'files'}`}</button>
        </form>
      ))}

      {showing && (
        <div className="flex flex-col gap-2" data-testid="export-run" role="status" aria-live="polite">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="disp text-base font-bold">{running ? `Exporting ${showing.counts.total} ${showing.counts.total === 1 ? 'file' : 'files'}` : 'Export finished'}</span>
            <span className="tnum text-[13px] text-muted-foreground" data-testid="export-step">{showing.step ?? ''}</span>
          </div>
          <FillBar share={running ? showing.progress : 1} height={8} strong label={`${showing.counts.ready} of ${showing.counts.total} files ready`} />
          <ul className="m-0 flex list-none flex-col p-0">
            {showing.files.map((f) => <FileRow key={f.index} projectId={projectId} exportId={showing.export_id} f={f} />)}
          </ul>
          {!running && <Tip id="first-batch-export" />}
          {!running && showing.counts.ready > 0 && <ShareLine projectId={projectId} run={showing} onChange={() => setTick((t) => t + 1)} />}
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-2">
            {!running && <button type="button" className="act" onClick={() => setDismissed(showing.export_id)}>Export again</button>}
            {showing.counts.ready > 0 && !running && <a className="btn volt sm" href={exportZipUrl(projectId, showing.export_id)} download>Download all (.zip)</a>}
          </div>
        </div>
      )}
    </section>
  )
}
