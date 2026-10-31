import { ApiError } from '../../api'

/** Voice consent V1, step 4: the Voice safety tab's calls (admins only). Step 5 adds its queue's calls here. */
export type HeldCategory = 'fraud' | 'impersonation' | 'political' | 'sexual' | 'minors' | 'hate' | 'claims' | 'unclear'
export type HeldState = 'waiting' | 'approved' | 'rejected' | 'expired'
export interface HeldLine {
  id: string; owner: string; video_id: string | null; voice_id: string | null; text: string | null
  categories: HeldCategory[]; category_words: string[]; rule_hits: string[]; model: string; reason: string
  review_state: HeldState; reviewed_by: string | null; reviewed_at: string | null; review_reason: string
  created_at: string; due_at: string
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

export const listHeldLines = (state: 'waiting' | 'decided' = 'waiting') =>
  call<{ items: HeldLine[]; waiting: number }>(`/admin/line-checks?verdict=review&state=${state}`)
export const decideHeldLine = (id: string, decision: 'approve' | 'reject', reason: string) =>
  call<HeldLine>(`/admin/line-checks/${encodeURIComponent(id)}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, reason }),
  })
