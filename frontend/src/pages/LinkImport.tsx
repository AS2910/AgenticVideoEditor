import { useEffect, useRef, useState } from 'react'
import type { ActivityJob, ImportSource } from '../types'
import { ApiError, getImport, getImportSources, startImport } from '../api'
import { FillBar } from './bits'

const POLL_MS = 1000

function sizeWords(n: number): string {
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1024 ** 2))} MB`
}

/** G1: import a video from a share link (Google Drive, Dropbox). The import
 *  is an Activity job: this shows its step, how much has come down, and a
 *  failure's sentence; when it is done the new video opens. */
export function LinkImport({ projectId, disabled, onDone }: {
  projectId: string | null
  disabled?: boolean
  onDone: (videoId: string) => void
}) {
  const [url, setUrl] = useState('')
  const [job, setJob] = useState<ActivityJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [sources, setSources] = useState<ImportSource[] | null>(null)
  const done = useRef(onDone)
  done.current = onDone

  useEffect(() => {
    let live = true
    getImportSources().then((s) => { if (live) setSources(s.sources) }).catch(() => { /* the line just stays generic */ })
    return () => { live = false }
  }, [])

  // Follow the job until it ends.
  const jobId = job && (job.status === 'queued' || job.status === 'running') ? job.job_id : null
  useEffect(() => {
    if (!jobId) return
    let live = true
    const timer = window.setInterval(() => {
      getImport(jobId).then((j) => { if (live) setJob(j) }).catch(() => { /* the next tick asks again */ })
    }, POLL_MS)
    return () => { live = false; window.clearInterval(timer) }
  }, [jobId])
  useEffect(() => {
    if (!job) return
    if (job.status === 'done' && typeof job.detail?.video_id === 'string') done.current(job.detail?.video_id)
    if (job.status === 'failed') setError(job.error_text || 'The import stopped.')
  }, [job])

  const busy = sending || jobId !== null
  const submit = async () => {
    const link = url.trim()
    if (!link || busy) return
    setError(null)
    setSending(true)
    try {
      setJob(await startImport(link, projectId))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start the import.')
    } finally {
      setSending(false)
    }
  }

  const got = typeof job?.detail?.bytes === 'number' ? job.detail?.bytes : null
  const total = typeof job?.detail?.total_bytes === 'number' ? job.detail?.total_bytes : null
  const off = sources?.filter((s) => !s.enabled) ?? []
  return (
    <form className="flex flex-col gap-2" aria-label="Import from a link" data-testid="link-import" data-tour="link-import"
      onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <label htmlFor="import-url" className="tag text-faint">Or paste a link</label>
      <div className="flex flex-wrap items-center gap-2.5">
        <input id="import-url" type="url" inputMode="url" autoComplete="off" spellCheck={false}
          className="box-border h-10 min-w-0 flex-[1_1_280px] rounded-lg border-[1.5px] border-foreground bg-card px-2.5 text-base text-foreground outline-none placeholder:text-faint focus-visible:ring-[3px] focus-visible:ring-volt"
          placeholder="A Google Drive or Dropbox share link" value={url} disabled={busy || disabled}
          aria-describedby="import-note" aria-invalid={error ? true : undefined}
          onChange={(e) => { setUrl(e.target.value); if (error) setError(null) }} />
        <button type="submit" className="btn" disabled={!url.trim() || busy || disabled} aria-busy={busy || undefined}>
          {busy ? 'Importing…' : 'Import'}
        </button>
      </div>
      <span id="import-note" className="text-[13px] text-muted-foreground">
        Shared with anyone who has the link, up to 2 GB and 3 minutes.{off.length > 0 ? ` ${off.map((s) => s.label).join(', ')} is not available yet.` : ''}
      </span>
      {jobId && job && (
        <div className="flex items-center gap-3" role="status" data-testid="import-progress">
          <FillBar share={job.progress > 0 ? job.progress : 1} height={8} strong className={job.progress > 0 ? 'w-32' : 'w-32 animate-pulse'} />
          <span className="text-[13px] text-muted-foreground">
            {job.step_label}{got !== null ? `, ${sizeWords(got)}${total ? ` of ${sizeWords(total)}` : ''}` : ''}.
          </span>
        </div>
      )}
      {error && <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</div>}
    </form>
  )
}
