import { ApiError } from '../../api'

/** Voice consent V1, step 5: the no-go list and its borderline queue (admins only; others get 404). */
export interface NoGoVoice {
  id: string; name: string; reason: string; added_by: string | null; created_at: string
  model: string; source: 'upload' | 'export' | ''; source_ref: string; seconds: number | null; dims: number
}
export interface NoGoList { voices: NoGoVoice[]; block_at: number; review_from: number; model: string; model_available: boolean }
export interface NoGoHold {
  id: string; owner: string; video_id: string | null; speaker_label: string | null; speaker_name: string | null
  subject: string; no_go_id: string | null; no_go_name: string | null; score: number | null; model: string
  status: 'waiting' | 'approved' | 'rejected' | 'closed'; reason: string; decided_by: string | null; decided_at: string | null
  created_at: string; has_audio: boolean; block_at: number; review_from: number
}
/** The voice to add: a clip, or a reported export (its mark, or the abuse report that names it), with an optional span. */
export interface NoGoAdd { name: string; reason: string; file?: File | null; mark?: string; abuseReportId?: number; start?: number; end?: number }

const BASE = '/api'
const HEADERS = { 'X-Requested-With': 'voltage' }

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...init, headers: { ...HEADERS, ...(init.headers ?? {}) } })
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try { const d = (await res.json())?.detail; if (typeof d === 'string') message = d } catch { /* not JSON */ }
    throw new ApiError(res.status, message)
  }
  return (await res.json()) as T
}
const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const listNoGoVoices = () => call<NoGoList>('/admin/no-go-voices')
export function addNoGoVoice(a: NoGoAdd) {
  const form = new FormData()
  form.set('name', a.name)
  form.set('reason', a.reason)
  if (a.file) form.set('file', a.file)
  if (a.mark) form.set('mark', a.mark)
  if (a.abuseReportId != null) form.set('abuse_report_id', String(a.abuseReportId))
  if (a.start != null) form.set('start', String(a.start))
  if (a.end != null) form.set('end', String(a.end))
  return call<NoGoVoice>('/admin/no-go-voices', { method: 'POST', body: form })
}
export const removeNoGoVoice = (id: string, reason: string) =>
  call<{ removed: string; name: string; holds_closed: number }>(`/admin/no-go-voices/${encodeURIComponent(id)}`, json('DELETE', { reason }))
export const listNoGoHolds = (status: 'waiting' | 'decided' = 'waiting') =>
  call<{ items: NoGoHold[]; waiting: number }>(`/admin/no-go-holds?status=${status}`)
export const decideNoGoHold = (id: string, decision: 'approve' | 'reject', reason: string) =>
  call<NoGoHold>(`/admin/no-go-holds/${encodeURIComponent(id)}`, json('POST', { decision, reason }))
export const noGoHoldAudioUrl = (id: string) => `${BASE}/admin/no-go-holds/${encodeURIComponent(id)}/audio`
