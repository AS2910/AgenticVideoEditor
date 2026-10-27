import type { Batch } from '../types'
import { gateLine } from '../lib/batch'
import { usd } from './fmt'

/** F4: the one gate before a batch runs (videos, lines, cost, cap), with Not
 *  yet and Go (the next action, last). Shared by Ask Voltage about all videos
 *  (B1), Fix in all (A2) and Bring up to date (A1, decision 0). Says how many
 *  Approved videos adding would take back to Draft. */
export function BatchGate({ batch, note, busy, going, onGo, onCancel }: {
  batch: Batch; note?: string | null; busy: boolean; going: boolean; onGo: () => void; onCancel: () => void
}) {
  const what = batch.source === 'fix' ? `Fix: ${batch.goal}` : batch.source === 'brief' ? batch.goal : `“${batch.goal}”`
  return (
    <div className="gate" data-testid="batch-gate" role="group" aria-label="Your go is needed">
      <span className="tag text-volt">⚡ Your go is needed</span>
      <span className="text-sm">{what}</span>
      <span className="disp text-lg font-bold" data-testid="batch-totals">{gateLine(batch.totals)}</span>
      <span className="pm text-[13px]" data-testid="batch-cap">
        {`You pay at most ${usd(batch.totals.cap_usd)} for all of it. Voltage works on 3 videos at a time, and nothing is added to a video until you add it.`}
      </span>
      {batch.approved_note && <span className="text-[13px] text-warn" data-testid="batch-approved">{batch.approved_note}</span>}
      <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
        {batch.rows.map((r) => (
          <li key={r.video_id} className="flex items-baseline gap-2 text-[13px]">
            <span className="min-w-0 flex-1 truncate">{r.filename}</span>
            <span className="pm tnum">{r.lines === null ? 'Voltage will look' : r.lines === 0 ? 'nothing to change' : `${r.lines} ${r.lines === 1 ? 'line' : 'lines'} to change`}</span>
          </li>
        ))}
      </ul>
      {note && <p className="m-0 text-sm text-volt" role="alert">{note}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" className="btn ghost sm" disabled={busy} onClick={onCancel}>Not yet</button>
        <button type="button" className="btn volt sm shine" disabled={busy} onClick={onGo}>{going ? 'Starting…' : `Go · ${batch.totals.videos} ${batch.totals.videos === 1 ? 'video' : 'videos'}`}</button>
      </div>
    </div>
  )
}
