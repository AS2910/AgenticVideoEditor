import { useRef, useState } from 'react'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { ActivityJob } from '../types'
import { aboutEta } from '../jobs/model'

interface ActivityDrawerProps {
  open: boolean
  onClose: () => void
  jobs: ActivityJob[]
  onRetry: (job: ActivityJob) => void | Promise<unknown>
  /** Times "now", for a running job's clock (tests pin it). */
  now?: number
}

const KIND: Record<ActivityJob['kind'], string> = {
  voice_line: 'Voice a line', design_voice: 'Design a voice', clone: 'Clone a voice', mix: 'Mix', render_preview: 'Render preview', export: 'Export', brief_update: 'Bring up to date with the brief', check: 'Check project', batch: 'Batch', learn: 'Learn your style', import: 'Import from a link', data_export: 'Your data export',
}
const STATUS: Record<ActivityJob['status'], { word: string; tone: string }> = {
  queued: { word: 'Queued', tone: 'live' }, running: { word: 'Running', tone: 'live' }, done: { word: 'Done', tone: 'in' },
  failed: { word: 'Failed', tone: 'need' }, cancelled: { word: 'Cancelled', tone: 'quiet' },
}

/** "4.2 s", "1 min 5 s": how long a job ran (or has been running). */
function took(job: ActivityJob, now: number): string | null {
  const start = job.started_at ? Date.parse(job.started_at) : NaN
  const end = job.finished_at ? Date.parse(job.finished_at) : job.status === 'running' ? now : NaN
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null
  const s = (end - start) / 1000
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`
}

/** What the job was about, in words: the line's words, the version, the voice. */
function about(job: ActivityJob): string | null {
  const d = job.detail ?? {}
  if (job.kind === 'voice_line' && d.text) return `“${d.text}”${d.voice_name ? ` · ${d.voice_name}` : ''}`
  if ((job.kind === 'render_preview' || job.kind === 'export') && d.version) return `v${d.version}${d.mode === 'proposals' ? ' · with proposals' : ''}`
  return d.voice_name ?? null
}

/** Activity (2026-10-20): this video's jobs, newest first, each with its
 *  status, how long it took, what it cost, and Retry on a failed one. */
export function ActivityDrawer({ open, onClose, jobs, onRetry, now = Date.now() }: ActivityDrawerProps) {
  const title = useRef<HTMLHeadingElement>(null)
  const [retrying, setRetrying] = useState<string | null>(null)
  const retry = async (job: ActivityJob) => {
    setRetrying(job.job_id)
    try { await onRetry(job) } finally { setRetrying(null) }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        className="top-0 right-0 left-auto flex h-dvh max-h-dvh w-full max-w-[440px] translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-0 border-l-[1.5px] border-ink bg-card p-0 text-foreground sm:max-w-[440px] data-[state=closed]:zoom-out-100 data-[state=open]:zoom-in-100"
        onOpenAutoFocus={(e) => { e.preventDefault(); title.current?.focus() }}
        data-testid="activity"
      >
        <div className="flex items-center gap-3 border-b-[1.5px] border-foreground px-5 py-4">
          <DialogTitle ref={title} tabIndex={-1} className="disp m-0 text-2xl font-bold outline-none">Activity</DialogTitle>
          <span className="tag text-faint">{jobs.length} {jobs.length === 1 ? 'job' : 'jobs'} · newest first</span>
          <span className="flex-1" />
          <button type="button" className="btn sm" onClick={onClose}>Close</button>
        </div>
        <ol className="slimbar m-0 flex min-h-0 flex-1 list-none flex-col overflow-y-auto overscroll-contain p-0" aria-label="Jobs">
          {jobs.length === 0 && <li className="px-5 py-6 text-sm text-muted-foreground">Nothing has run on this video yet.</li>}
          {jobs.map((j) => {
            const s = STATUS[j.status]
            const what = about(j)
            const time = took(j, now)
            const eta = j.status === 'queued' || j.status === 'running' ? aboutEta(j.eta_s) : null
            return (
              <li key={j.job_id} className="flex flex-col gap-1.5 border-b border-line px-5 py-3.5" data-testid="activity-job" data-status={j.status}>
                <div className="flex min-w-0 items-center gap-2.5">
                  <span className="min-w-0 flex-1 truncate font-medium">{KIND[j.kind] ?? j.kind}{j.detail?.manual ? ' · from the editor' : ''}</span>
                  <span className={cn('stamp', s.tone)}>{s.word}</span>
                </div>
                {what && <span className="min-w-0 truncate text-sm text-muted-foreground" title={what}>{what}</span>}
                <div className="tnum flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-faint">
                  {(j.status === 'running' || j.status === 'queued') && j.step_label && <span className="text-foreground">{j.step_label}</span>}
                  {time && <span>{time}</span>}
                  {eta && <span>{eta} left</span>}
                  {j.cost_usd != null && j.cost_usd > 0 && <span>${j.cost_usd.toFixed(2)}</span>}
                </div>
                {j.status === 'failed' && (
                  <div className="flex flex-wrap items-center gap-2">
                    {j.error_text && <span className="min-w-0 flex-1 text-sm text-needs">{j.error_text}</span>}
                    {j.retryable && (
                      <button type="button" className="btn sm" onClick={() => void retry(j)} disabled={retrying !== null} aria-busy={retrying === j.job_id || undefined}>
                        {retrying === j.job_id ? 'Retrying…' : 'Retry'}
                      </button>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      </DialogContent>
    </Dialog>
  )
}
