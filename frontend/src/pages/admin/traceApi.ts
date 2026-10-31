import { ApiError } from '../../api'

/** Voice consent V1, step 7: Trace and a person's cloning (admins only; others get 404). */
export interface TraceExport {
  mark: string; export_id: string; owner: string; video_id: string; file: string; sha256: string; created_at: string
  export_attestation_id: string | null; ai_voice: boolean; label_on: boolean; voices: string[]; takes: string[]
}
export interface TraceAttestation { id: string; owner: string; video_id: string; voice_id: string | null; speaker_label: string | null; choice: 'my_voice' | 'have_permission'; statement_version: string; created_at: string; ip: string | null; user_agent: string | null }
export interface TraceVoice {
  voice_id: string; owner?: string; kind?: string; scope?: 'video' | 'library'; status?: string; status_reason?: string
  source_video_id?: string | null; speaker_label?: string | null; speaker_name?: string | null; attestations: TraceAttestation[]
}
export interface TraceConfirmation { id: string; export_id: string; owner: string; voices_used: string[]; covers: string[]; statement_version: string; label_on: boolean; created_at: string; ip: string | null }
export interface TraceSynthesis { id: string; owner: string; video_id: string | null; voice_id: string; attestation_id: string | null; line_check_id: string | null; take_id: string | null; cost_usd: number | null; created_at: string }
export interface TraceLineCheck { id: string; voice_id: string | null; text: string | null; verdict: 'pass' | 'block' | 'review'; categories: string[]; model: string; rule_hits: string[]; created_at: string }
export interface CloningSuspension { reason: string; by: string; at: string }
export interface TraceUser { owner: string; emails: string[]; suspended: CloningSuspension | null; limits: { day: number; month: number } }
export interface Trace {
  ref: string; found_by: 'mark' | 'export' | 'confirmation' | 'abuse_report'
  abuse_report: { id: number; location: string; kind: string; details: string; contact: string; created_at: string } | null
  exports: TraceExport[]; export_attestations: TraceConfirmation[]; voices: TraceVoice[]
  synthesis: TraceSynthesis[]; line_checks: TraceLineCheck[]; users: TraceUser[]
}
export interface CloningState {
  owner: string; suspended: CloningSuspension | null; enabled: boolean
  limits: { day: number; month: number }; used: { day: number; month: number }
  voices: { active: number; suspended: number; withdrawn: number }
}

const BASE = '/api'
const HEADERS = { 'X-Requested-With': 'voltage' }

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...init, headers: { ...HEADERS, ...(init.headers ?? {}) } })
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const d = (await res.json())?.detail
      if (typeof d === 'string') message = d
      else if (d && typeof d.message === 'string') message = d.message
    } catch { /* not JSON */ }
    throw new ApiError(res.status, message)
  }
  return (await res.json()) as T
}
const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const who = (owner: string) => `/admin/users/${encodeURIComponent(owner)}`

export const traceExport = (ref: string) => call<Trace>(`/admin/exports/${encodeURIComponent(ref)}/trace`)
export const getCloning = (owner: string) => call<CloningState>(`${who(owner)}/cloning`)
export const suspendCloning = (owner: string, reason: string) =>
  call<{ voices_disabled: number }>(`${who(owner)}/suspend-cloning`, post({ reason }))
export const restoreCloning = (owner: string, reason: string) =>
  call<{ voices_restored: number }>(`${who(owner)}/restore-cloning`, post({ reason }))
export const setCloneLimits = (owner: string, day: number, month: number, reason: string) =>
  call<{ day: number; month: number }>(`${who(owner)}/clone-limits`, post({ day, month, reason }))

/** Open Trace on the admin page for a reference (an abuse report's number, say). */
export const TRACE_EVENT = 'voltage:admin-trace'
export function openTrace(ref: string) {
  window.dispatchEvent(new CustomEvent(TRACE_EVENT, { detail: ref }))
  document.getElementById('admin-trace-s')?.scrollIntoView({ block: 'start' })
}
