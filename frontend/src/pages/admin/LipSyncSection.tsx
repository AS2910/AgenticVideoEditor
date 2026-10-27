import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { clock } from '../../transcript/format'
import { said } from '../fmt'
import { field } from './ui'
import type { LipSyncConfidence, LipSyncStatus, LipSyncTrial, LipSyncVideo } from './lipsyncApi'
import { getLipSyncStatus, getLipSyncVideo, lipSyncFileUrl, runLipSyncTrial } from './lipsyncApi'

const STATE_WORD = { on_camera: 'On camera', off_camera: 'Off camera', unsure: 'Unsure' } as const
const VERDICT_STAMP = { pass: 'stamp', below: 'stamp need', no_face: 'stamp quiet', no_baseline: 'stamp quiet' } as const
const VERDICT_WORD = { pass: 'Pass', below: 'Below', no_face: 'No face', no_baseline: 'No baseline' } as const
const score = (c: LipSyncConfidence) => (c.score == null ? 'no face to judge' : `${c.score.toFixed(2)} (${c.method === 'syncnet' ? 'SyncNet' : 'mouth motion'})`)

/** Run 5, item 10: the lip-sync review. Pick a video, see which lines have the speaker on
 *  camera, run one line's span (plus its handles) through a provider, and compare the
 *  original window with the result side by side, each with its confidence score. */
export function LipSyncSection({ card }: { card: string }) {
  const [status, setStatus] = useState<LipSyncStatus | null>(null)
  const [id, setId] = useState('')
  const [video, setVideo] = useState<LipSyncVideo | null>(null)
  const [provider, setProvider] = useState('fake')
  const [busy, setBusy] = useState<number | 'load' | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { getLipSyncStatus().then((r) => setStatus(Array.isArray(r?.providers) ? r : null)).catch(() => setStatus(null)) }, [])
  const load = async () => {
    setBusy('load'); setError(null)
    try { const v = await getLipSyncVideo(id.trim()); setVideo(Array.isArray(v?.lines) ? v : null) } catch (e) { setVideo(null); setError(said(e, 'That video could not be read.')) } finally { setBusy(null) }
  }
  const run = async (line: number) => {
    if (!video) return
    setBusy(line); setError(null)
    try { await runLipSyncTrial(video.video_id, line, provider); setVideo(await getLipSyncVideo(video.video_id)) } catch (e) { setError(said(e, 'That did not run.')) } finally { setBusy(null) }
  }
  const usable = status?.providers.filter((p) => p.available) ?? []
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="lipsync-h" data-testid="admin-lipsync">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id="lipsync-h" className="disp m-0 text-[22px] font-bold">Lip-sync review</h2>
        <span className="text-sm text-faint">one line at a time, original beside the result</span>
      </div>
      {status && (
        <p className="m-0 text-sm text-muted-foreground" data-testid="lipsync-status">
          Provider in the product: {status.selected === 'off' ? 'none yet' : status.selected}. Each span is sent with {status.handle_seconds} s either side. Scored by {status.measure === 'syncnet' ? 'SyncNet' : 'mouth motion'}.
        </p>
      )}
      <form className="flex flex-wrap items-end gap-2.5" onSubmit={(e) => { e.preventDefault(); void load() }}>
        <label className="flex min-w-0 flex-[1_1_160px] flex-col gap-1"><span className="font-semibold">Video id</span>
          <input className={field} value={id} onChange={(e) => setId(e.target.value)} placeholder="p12" />
        </label>
        <label className="flex min-w-0 flex-col gap-1"><span className="font-semibold">Provider</span>
          <select className={field} value={provider} onChange={(e) => setProvider(e.target.value)}>
            {(usable.length ? usable : [{ name: 'fake', available: true }]).map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </label>
        <button type="submit" className="btn ink sm" disabled={!id.trim() || busy !== null}>{busy === 'load' ? 'Loading…' : 'Load'}</button>
      </form>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {video && (
        <>
          <p className="m-0 text-sm text-muted-foreground" role="status">
            {video.filename}: {video.lines.length} {video.lines.length === 1 ? 'line' : 'lines'}, {video.status === 'running' ? 'still being looked at' : video.status === 'none' ? 'not looked at' : `looked at in ${video.seconds ?? 0} s`}.
          </p>
          <ol className="m-0 flex list-none flex-col p-0">
            {video.lines.map((ln) => (
              <li key={ln.index} className="flex flex-wrap items-baseline gap-2 border-t border-line py-2 text-[13px]" data-testid="lipsync-line">
                <span className="tnum text-muted-foreground">{clock(ln.start)}</span>
                <span className={cn(ln.on_camera === 'on_camera' ? 'stamp need' : ln.on_camera === 'unsure' ? 'stamp inkd' : 'stamp quiet')}>{ln.on_camera ? STATE_WORD[ln.on_camera] : 'Not looked at'}</span>
                <span className="min-w-0 flex-[1_1_200px]">{ln.text}<span className="block text-faint">{ln.detail?.why}</span></span>
                <button type="button" className="btn sm" disabled={busy !== null} aria-busy={busy === ln.index || undefined} onClick={() => void run(ln.index)}>
                  {busy === ln.index ? 'Running…' : `Try line ${ln.index}`}
                </button>
              </li>
            ))}
          </ol>
          {video.trials.map((t) => <Trial key={t.id} videoId={video.video_id} t={t} />)}
        </>
      )}
    </section>
  )
}

function Trial({ videoId, t }: { videoId: string; t: LipSyncTrial }) {
  return (
    <article className="flex flex-col gap-2 border-t border-line py-3 text-[13px]" data-testid="lipsync-trial" aria-label={`Line ${t.line} through ${t.provider}`}>
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={VERDICT_STAMP[t.compare.verdict]}>{VERDICT_WORD[t.compare.verdict]}</span>
        <span>{t.compare.say}</span>
        <span className="tnum text-muted-foreground">Line {t.line} · {t.provider} · sent {clock(t.window.send_start)} to {clock(t.window.send_end)} · ${t.usd.toFixed(2)} · {t.seconds} s</span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <figure className="m-0 flex min-w-0 flex-col gap-1">
          <figcaption className="font-semibold">Original</figcaption>
          <video controls preload="metadata" src={lipSyncFileUrl(videoId, t.original.sha256)} className="w-full rounded-md bg-pic" aria-label={`Line ${t.line} as shot`} />
          <span className="tnum text-muted-foreground">Confidence {score(t.original.confidence)}</span>
        </figure>
        <figure className="m-0 flex min-w-0 flex-col gap-1">
          <figcaption className="font-semibold">Result, with {t.heard}</figcaption>
          <video controls preload="metadata" src={lipSyncFileUrl(videoId, t.result.sha256)} className="w-full rounded-md bg-pic" aria-label={`Line ${t.line} through ${t.provider}`} />
          <span className="tnum text-muted-foreground">Confidence {score(t.result.confidence)}</span>
        </figure>
      </div>
      {t.notes.map((n) => <p key={n} className="m-0 text-faint">{n}</p>)}
    </article>
  )
}
