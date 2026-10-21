import { useCallback, useEffect, useState } from 'react'
import type { DataRequest } from '../api'
import { dataExportUrl, listDataRequests, startDataExport } from '../api'
import { said } from './fmt'

/** G6: your data. Download everything as a zip (an Activity job; the zip holds JSON and a list
 *  of your media), or delete it all with the account's own Delete everything below. */
export function YourData({ onDelete }: { onDelete: () => void }) {
  const [requests, setRequests] = useState<DataRequest[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => {
    listDataRequests().then((r) => setRequests(r.requests)).catch((e) => setError(said(e, 'Your data requests could not be read.')))
  }, [])
  useEffect(() => { load() }, [load])
  const running = (requests ?? []).find((r) => r.kind === 'export' && r.job && !['done', 'failed', 'cancelled'].includes(r.job.status))
  useEffect(() => {
    if (!running) return
    const t = window.setInterval(load, 1500)
    return () => window.clearInterval(t)
  }, [running, load])
  const latest = (requests ?? []).find((r) => r.kind === 'export') ?? null
  const start = async () => {
    setBusy(true); setError(null)
    try { await startDataExport(); load() } catch (e) { setError(said(e, 'The export did not start. Try again.')) } finally { setBusy(false) }
  }
  return (
    <div className="flex flex-col gap-2.5" data-testid="your-data">
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 flex-1 text-sm text-muted-foreground">
          {running ? `Making your zip… ${running.job?.step_label ?? ''}`.trim()
            : latest?.job?.status === 'done' ? 'Your zip is ready: every record as JSON, and a list of your media.'
            : latest?.job?.status === 'failed' ? `The last export failed. ${latest.job.error_text ?? ''}`.trim()
            : 'A zip of every record of yours as JSON, with a list of your media files.'}
        </span>
        {latest?.job?.status === 'done' && latest.job_id && <a className="act" href={dataExportUrl(latest.job_id)} download>Download zip</a>}
        <button type="button" className="btn sm" onClick={() => void start()} disabled={busy || !!running}>{running ? 'Working…' : 'Download my data'}</button>
      </div>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 flex-1 text-sm text-muted-foreground">To delete your data, delete your account: everything goes at once, and consent records are kept as the law asks.</span>
        <button type="button" className="act" onClick={onDelete}>Delete my data</button>
      </div>
    </div>
  )
}
