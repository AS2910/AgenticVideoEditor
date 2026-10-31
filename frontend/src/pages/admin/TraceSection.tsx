import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { formatDate } from '../../lib/dates'
import { hrefFor } from '../../lib/route'
import { said } from '../fmt'
import { field } from './ui'
import type { Trace, TraceVoice } from './traceApi'
import { TRACE_EVENT, traceExport } from './traceApi'

const CHOICE: Record<string, string> = { my_voice: 'This is my voice', have_permission: 'I have permission from this person' }
const FOUND_BY: Record<Trace['found_by'], string> = {
  mark: 'Found by its mark', export: 'Found by its export id', confirmation: 'Found by its export reminder', abuse_report: 'Found from the abuse report',
}
const VERDICT: Record<string, [string, string]> = { pass: ['stamp quiet', 'Passed'], block: ['stamp inkd', 'Blocked'], review: ['stamp need', 'Held'] }

function Part({ title, children, testid }: { title: string; children: ReactNode; testid?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5 rounded-[10px] border border-line2 p-3.5 text-[13px]" data-testid={testid}>
      <h3 className="tag m-0 text-faint">{title}</h3>
      {children}
    </div>
  )
}

const VideoLink = ({ id }: { id: string | null | undefined }) =>
  id ? <a href={hrefFor({ page: 'editor', projectId: id })} className="underline">video {id}</a> : <span>no video</span>

const voiceName = (v: TraceVoice) =>
  v.speaker_name || (v.speaker_label && v.speaker_label !== '_' ? `Speaker ${v.speaker_label}` : v.voice_id)

/** Voice consent V1, step 7: Trace. Paste an export id, a provenance mark or an abuse report's
 *  number; see the voices behind that export, the attestations given for them, the export
 *  reminder's confirmation, each line voiced with its check, and who made it. Every Trace is in
 *  the audit trail (it reads personal data). An abuse report's Trace link fills it in. */
export function TraceSection({ card }: { card: string }) {
  const [ref, setRef] = useState('')
  const [trace, setTrace] = useState<Trace | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async (value: string) => {
    if (!value.trim()) return
    setBusy(true); setError(null); setTrace(null)
    try { setTrace(await traceExport(value.trim())) } catch (e) { setError(said(e, 'Trace did not work.')) } finally { setBusy(false) }
  }, [])
  useEffect(() => {
    const on = (e: Event) => { const value = String((e as CustomEvent).detail ?? ''); setRef(value); void run(value) }
    window.addEventListener(TRACE_EVENT, on)
    return () => window.removeEventListener(TRACE_EVENT, on)
  }, [run])
  const submit = (e: FormEvent) => { e.preventDefault(); void run(ref) }
  return (
    <section className={`${card} flex flex-col gap-3`} aria-labelledby="trace-h" data-testid="admin-trace">
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id="trace-h" className="disp m-0 text-[22px] font-bold">Trace</h2>
        <span className="tag text-faint">the voices, attestations, line checks and person behind an export</span>
      </div>
      <form className="flex flex-wrap items-end gap-2.5" role="search" aria-label="Trace an export" onSubmit={submit}>
        <label className="flex min-w-0 flex-[1_1_260px] flex-col gap-1"><span className="text-[13px] font-semibold">Export id, mark or abuse report number</span>
          <input className={field} value={ref} onChange={(e) => setRef(e.target.value)} maxLength={80} autoComplete="off" placeholder="ve_…, a 16-letter mark, or 42" />
        </label>
        <button type="submit" className="btn sm pointer-coarse:min-h-11" disabled={busy || !ref.trim()}>{busy ? 'Tracing…' : 'Trace'}</button>
      </form>
      <p className="m-0 text-[13px] text-muted-foreground">Each Trace is kept in the audit trail, since it shows personal data.</p>
      {error && <p className="m-0 text-sm text-destructive" role="alert">{error}</p>}
      {trace && <TraceView t={trace} />}
    </section>
  )
}

function TraceView({ t }: { t: Trace }) {
  const checks = new Map(t.line_checks.map((c) => [c.id, c]))
  return (
    <article className="flex flex-col gap-3 border-t-[1.5px] border-foreground pt-4" aria-label={`Trace of ${t.ref}`} data-testid="trace-result">
      <p className="m-0 text-sm"><span className="font-semibold">{FOUND_BY[t.found_by]}</span> <span className="tnum text-muted-foreground [overflow-wrap:anywhere]">{t.ref}</span></p>
      {t.abuse_report && (
        <Part title={`Abuse report #${t.abuse_report.id}`} testid="trace-report">
          <span><span className="stamp need">{t.abuse_report.kind.replace('_', ' ')}</span> <span className="[overflow-wrap:anywhere]">{t.abuse_report.location}</span></span>
          {t.abuse_report.details && <span>{t.abuse_report.details}</span>}
          {t.exports.length === 0 && <span className="text-muted-foreground">The report names no export of ours. Ask the reporter for the file, or paste its mark here.</span>}
        </Part>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Part title="Who made it" testid="trace-users">
          {t.users.length === 0 ? <span className="text-muted-foreground">No one found.</span> : t.users.map((u) => (
            <div key={u.owner} className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">{u.emails[0] ?? u.owner}</span>
              <span className="tnum text-muted-foreground [overflow-wrap:anywhere]">{u.owner}</span>
              {u.suspended
                ? <span><span className="stamp need">Cloning suspended</span> {formatDate(u.suspended.at)} by {u.suspended.by}: {u.suspended.reason}</span>
                : <span className="text-muted-foreground">Cloning allowed · {u.limits.day} a day, {u.limits.month} in 30 days</span>}
            </div>
          ))}
        </Part>
        <Part title="Files" testid="trace-exports">
          {t.exports.length === 0 ? <span className="text-muted-foreground">No exported file carries this.</span> : t.exports.map((e) => (
            <div key={e.mark} className="flex flex-col gap-0.5">
              <span className="[overflow-wrap:anywhere]">{e.file} · <VideoLink id={e.video_id} /></span>
              <span className="tnum text-muted-foreground [overflow-wrap:anywhere]">{e.export_id || 'no export id'} · mark {e.mark} · {formatDate(e.created_at)}</span>
              <span>{e.ai_voice ? <span className="stamp">AI voice</span> : <span className="stamp quiet">No cloned voice</span>} {e.ai_voice && (e.label_on ? 'Label on' : 'Label switched off')}</span>
            </div>
          ))}
        </Part>
      </div>
      <Part title="Voices and their attestations" testid="trace-voices">
        {t.voices.length === 0 ? <span className="text-muted-foreground">No cloned voice in this export.</span> : t.voices.map((v) => (
          <div key={v.voice_id} className="flex flex-col gap-0.5 border-t border-line pt-2 first:border-t-0 first:pt-0">
            <span className="text-sm font-medium">{voiceName(v)} <span className="tnum text-[13px] font-normal text-muted-foreground">{v.voice_id}</span></span>
            <span className="text-muted-foreground">{v.scope === 'video' ? 'This video only' : v.scope === 'library' ? 'In My voices' : 'No record'}{v.source_video_id && <> · from <VideoLink id={v.source_video_id} /></>}{v.status && v.status !== 'active' ? ` · ${v.status}` : ''}</span>
            {v.attestations.length === 0 ? <span className="text-destructive">No attestation found.</span> : v.attestations.map((a) => (
              <span key={a.id}>{CHOICE[a.choice] ?? a.choice} · statement {a.statement_version} · <span className="tnum">{formatDate(a.created_at)}</span>{a.ip ? ` · ${a.ip}` : ''}</span>
            ))}
          </div>
        ))}
      </Part>
      <Part title="Export reminder" testid="trace-confirmations">
        {t.export_attestations.length === 0 ? <span className="text-muted-foreground">No confirmation: the export had no cloned voice.</span> : t.export_attestations.map((c) => (
          <span key={c.id}>Confirmed <span className="tnum">{formatDate(c.created_at)}</span> · {c.voices_used.length} {c.voices_used.length === 1 ? 'voice' : 'voices'} · label {c.label_on ? 'on' : 'off'} · statement {c.statement_version}{c.ip ? ` · ${c.ip}` : ''}</span>
        ))}
      </Part>
      <Part title="Lines voiced and their checks" testid="trace-lines">
        {t.synthesis.length === 0 ? <span className="text-muted-foreground">No voiced line on record for this export.</span> : t.synthesis.map((s) => {
          const c = s.line_check_id ? checks.get(s.line_check_id) : undefined
          const [cls, word] = VERDICT[c?.verdict ?? ''] ?? ['stamp quiet', 'No check']
          return (
            <div key={s.id} className="flex flex-col gap-0.5 border-t border-line pt-2 first:border-t-0 first:pt-0" data-testid="trace-line">
              <span><span className={cls}>{word}</span> take {s.take_id ?? 'unknown'} · <span className="tnum">{formatDate(s.created_at)}</span>{s.cost_usd != null && <> · <span className="tnum">${s.cost_usd.toFixed(3)}</span></>}</span>
              {c?.text && <span className="text-sm">{c.text}</span>}
              {c && c.categories.length > 0 && <span className="text-muted-foreground">{c.categories.join(', ')}</span>}
              {c && <span className="truncate text-faint" title={[c.model, ...c.rule_hits].join(' · ')}>{c.model || 'rules only'}</span>}
            </div>
          )
        })}
      </Part>
    </article>
  )
}
