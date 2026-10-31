import { useCallback, useEffect, useId, useState } from 'react'
import { formatDate } from '../../lib/dates'
import { cn } from '@/lib/utils'
import { said } from '../fmt'
import type { NoGoList, NoGoVoice } from './noGoApi'
import { addNoGoVoice, listNoGoVoices, removeNoGoVoice } from './noGoApi'
import { field } from './ui'

const seconds = (x: string) => (x.trim() === '' ? undefined : Number(x))

/** Voice consent V1, step 5: the voices Voltage does not clone. Add one from a clip or from a
 *  reported export (only its voice print is kept, never the audio), or take one off with a
 *  reason. Every change goes to the audit trail. A part of the Voice safety tab. */
export function NoGoVoicesList({ onChange }: { onChange?: () => void }) {
  const [data, setData] = useState<NoGoList | null>(null)
  const [unread, setUnread] = useState(false)
  const load = useCallback(() => {
    setUnread(false)
    listNoGoVoices().then((r) => { if (Array.isArray(r?.voices)) setData(r) }).catch(() => setUnread(true))
  }, [])
  useEffect(load, [load])
  const changed = () => { load(); onChange?.() }
  return (
    <section className="flex flex-col gap-3" aria-labelledby="nogo-list-h" data-testid="admin-no-go-voices">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h3 id="nogo-list-h" className="disp m-0 text-[18px] font-bold">No-go voices</h3>
        <span className="tag text-faint">voices Voltage does not clone</span>
      </div>
      <p className="m-0 max-w-[640px] text-[13px] text-muted-foreground">
        A clone that sounds like one of these at {(data?.block_at ?? 0.92).toFixed(2)} or more is blocked. From {(data?.review_from ?? 0.84).toFixed(2)} it
        waits for a person, below. Only the voice print is kept, never the clip.
      </p>
      {data && !data.model_available && (
        <p className="m-0 rounded-md border border-line px-3 py-2 text-[13px]" role="note">
          The speaker model is not available here, so voices cannot be added, and every clone waits for a person while the list has voices.
        </p>
      )}
      {unread && <p className="m-0 text-sm text-muted-foreground">The list could not be read.</p>}
      {!unread && !data && <p className="m-0 text-muted-foreground" role="status" aria-busy="true">Reading the list…</p>}
      {data && data.voices.length === 0 && <p className="m-0 text-muted-foreground">The list is empty. Add a voice when an abuse report names a public figure.</p>}
      {data && data.voices.map((v) => <VoiceRow key={v.id} v={v} onDone={changed} />)}
      <AddVoice onDone={changed} />
    </section>
  )
}

function from(v: NoGoVoice): string {
  const what = v.source === 'export' ? `From ${v.source_ref}` : v.source === 'upload' ? `From the clip ${v.source_ref}` : 'Added'
  return `${what}${v.seconds != null ? `, ${v.seconds.toFixed(1)} s` : ''}`
}

function VoiceRow({ v, onDone }: { v: NoGoVoice; onDone: () => void }) {
  const [removing, setRemoving] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const remove = async () => {
    setBusy(true); setError(null)
    try { await removeNoGoVoice(v.id, reason.trim()); onDone() } catch (e) { setError(said(e, 'That did not save.')) } finally { setBusy(false) }
  }
  return (
    <article className="flex flex-col gap-1.5 border-t border-line py-3 text-[13px]" data-testid="no-go-voice" aria-label={`No-go voice ${v.name}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="min-w-0 text-sm font-medium [overflow-wrap:anywhere]">{v.name}</span>
        {!removing && <button type="button" className="act" onClick={() => setRemoving(true)}>Remove</button>}
      </div>
      {v.reason && <p className="m-0 [overflow-wrap:anywhere]">{v.reason}</p>}
      <p className="tnum m-0 text-muted-foreground [overflow-wrap:anywhere]">{from(v)} · {v.added_by ?? 'an admin'} · {formatDate(v.created_at)}</p>
      {removing && (
        <div className="flex flex-wrap items-end gap-2.5">
          <label className="flex min-w-0 flex-[1_1_220px] flex-col gap-1"><span className="font-semibold">Why remove it</span>
            <input className={field} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="kept in the audit trail" />
          </label>
          <button type="button" className="btn sm" disabled={busy} onClick={() => { setRemoving(false); setReason('') }}>Keep it</button>
          <button type="button" className="btn ink sm" disabled={busy || reason.trim().length < 3} onClick={() => void remove()}>{busy ? 'Removing…' : 'Remove'}</button>
        </div>
      )}
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
    </article>
  )
}

function AddVoice({ onDone }: { onDone: () => void }) {
  const id = useId()
  const [kind, setKind] = useState<'clip' | 'export'>('clip')
  const [name, setName] = useState('')
  const [reason, setReason] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [ref, setRef] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [added, setAdded] = useState<string | null>(null)
  const [fileKey, setFileKey] = useState(0)
  const report = /^\d+$/.test(ref.trim())
  const ready = name.trim() !== '' && reason.trim().length >= 3 && (kind === 'clip' ? !!file : ref.trim() !== '')
  const add = async () => {
    setBusy(true); setError(null); setAdded(null)
    try {
      const made = await addNoGoVoice({
        name: name.trim(), reason: reason.trim(), start: seconds(start), end: seconds(end),
        ...(kind === 'clip' ? { file } : report ? { abuseReportId: Number(ref.trim()) } : { mark: ref.trim() }),
      })
      setAdded(made.name); setName(''); setReason(''); setFile(null); setRef(''); setStart(''); setEnd(''); setFileKey((k) => k + 1)
      onDone()
    } catch (e) { setError(said(e, 'That voice was not added.')) } finally { setBusy(false) }
  }
  return (
    <form className="flex flex-col gap-2.5 border-t border-line pt-3 text-[13px]" aria-labelledby={`${id}-h`} onSubmit={(e) => { e.preventDefault(); if (ready && !busy) void add() }}>
      <h4 id={`${id}-h`} className="m-0 text-sm font-semibold">Add a voice</h4>
      <div className="grid gap-2.5 sm:grid-cols-2">
        <label className="flex min-w-0 flex-col gap-1"><span className="font-semibold">Whose voice</span>
          <input className={field} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="the person's name" />
        </label>
        <label className="flex min-w-0 flex-col gap-1"><span className="font-semibold">Why</span>
          <input className={field} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="kept in the audit trail" />
        </label>
      </div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="The voice comes from">
        <button type="button" className={cn('pill', kind === 'clip' && 'on')} aria-pressed={kind === 'clip'} onClick={() => setKind('clip')}>A clip</button>
        <button type="button" className={cn('pill', kind === 'export' && 'on')} aria-pressed={kind === 'export'} onClick={() => setKind('export')}>A reported export</button>
      </div>
      {kind === 'clip' ? (
        <div className="flex min-w-0 flex-col gap-1">
          <label className="flex min-w-0 flex-col gap-1"><span className="font-semibold">The clip</span>
            <input key={fileKey} type="file" accept="audio/*,video/*" className="text-sm" aria-describedby={`${id}-clip`} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <span id={`${id}-clip`} className="text-muted-foreground">Three seconds or more of only this voice. The clip is not kept.</span>
        </div>
      ) : (
        <label className="flex min-w-0 flex-col gap-1"><span className="font-semibold">Export mark or abuse report number</span>
          <input className={field} value={ref} onChange={(e) => setRef(e.target.value)} maxLength={40} placeholder="0123456789abcdef, or 42" />
        </label>
      )}
      <div className="flex flex-wrap items-end gap-2.5">
        <label className="flex w-[120px] flex-col gap-1"><span className="font-semibold">From (s)</span>
          <input className={field} inputMode="decimal" value={start} onChange={(e) => setStart(e.target.value)} placeholder="optional" />
        </label>
        <label className="flex w-[120px] flex-col gap-1"><span className="font-semibold">To (s)</span>
          <input className={field} inputMode="decimal" value={end} onChange={(e) => setEnd(e.target.value)} placeholder="optional" />
        </label>
      </div>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {added && <p className="m-0 text-sm" role="status">{added} is on the list.</p>}
      <div><button type="submit" className="btn volt sm" disabled={busy || !ready}>{busy ? 'Adding…' : 'Add to the list'}</button></div>
    </form>
  )
}
