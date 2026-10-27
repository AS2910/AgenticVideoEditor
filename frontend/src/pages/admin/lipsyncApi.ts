import { ApiError } from '../../api'
import type { OnCamera } from '../../types'

/** Run 5, item 10: the lip-sync review page's calls (admins only; others get 404). */
export interface LipSyncStatus { selected: string; providers: { name: string; available: boolean }[]; handle_seconds: number; measure: 'syncnet' | 'motion' }
export interface LipSyncConfidence { score: number | null; method: 'syncnet' | 'motion' | 'none'; detail: Record<string, unknown> }
export interface LipSyncTrial {
  id: string; at: string; by: string; line: number; provider: string; heard: string
  window: { start: number; end: number; send_start: number; send_end: number }
  original: { sha256: string; confidence: LipSyncConfidence }
  result: { sha256: string; confidence: LipSyncConfidence }
  compare: { verdict: 'pass' | 'below' | 'no_face' | 'no_baseline'; say: string }
  usd: number; notes: string[]; seconds: number
}
export interface LipSyncLine { index: number; start: number; end: number; text: string; on_camera: OnCamera | null; detail: { why?: string; face_share?: number } | null }
export interface LipSyncVideo { video_id: string; filename: string; duration: number; status: string; seconds: number | null; lines: LipSyncLine[]; trials: LipSyncTrial[] }

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

export const getLipSyncStatus = () => call<LipSyncStatus>('/admin/lipsync')
export const getLipSyncVideo = (id: string) => call<LipSyncVideo>(`/admin/lipsync/videos/${encodeURIComponent(id)}`)
export const runLipSyncTrial = (id: string, line: number, provider: string) =>
  call<LipSyncTrial>(`/admin/lipsync/videos/${encodeURIComponent(id)}/trials`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ line, provider }),
  })
export const lipSyncFileUrl = (id: string, sha: string) => `${BASE}/admin/lipsync/videos/${encodeURIComponent(id)}/files/${sha}`
