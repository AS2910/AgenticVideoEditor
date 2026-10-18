import type {
  MyVoice, UserSettings, UsageReport, MadeVoice, CloneableSpeaker, DesignedPreview, Receipt,
  Project, ExportManifest, Job, ProjectSummary, ProjectDetail, Usage, Voice, Speaker,
  ProjectSettings, Autonomy, Effort, Plan, Mix, Selection, Candidate, Reading, Sight, ChatMessage,
} from './types'

const BASE = '/api'
// Phase 9c: a state-changing request says it came from Voltage; a cross-site
// form cannot set this header, which is the CSRF check when sign-in is on.
const FROM_VOLTAGE = { 'X-Requested-With': 'voltage' }

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Pulls FastAPI's `{detail: "..."}` out of an error body so rejection
 *  reasons ("That file has no video track.") reach the user intact. */
async function failure(res: Response): Promise<never> {
  const raw = await res.text()
  let message = raw
  try {
    const parsed = JSON.parse(raw)
    if (typeof parsed?.detail === 'string') message = parsed.detail
  } catch {
    // Not JSON — use the raw body.
  }
  throw new ApiError(res.status, message)
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...FROM_VOLTAGE },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) return failure(res)
  return (await res.json()) as T
}

/**
 * Uploads the real video. No Content-Type header — the browser sets the
 * multipart boundary itself.
 *
 * `consent` records the uploader's confirmation that they may edit and clone
 * this speaker. The backend refuses to generate without it.
 */
export async function createProject(file: File, consent: boolean, onProgress?: (share: number) => void): Promise<Project> {
  const body = new FormData()
  body.append('file', file)
  body.append('consent', String(consent))
  if (onProgress && typeof XMLHttpRequest !== 'undefined') return uploadWithProgress(body, onProgress)
  const res = await fetch(`${BASE}/projects`, { method: 'POST', headers: FROM_VOLTAGE, body })
  if (!res.ok) return failure(res)
  return (await res.json()) as Project
}

/** The same POST through XMLHttpRequest, which is the only way a browser
 *  reports upload progress (UX-6): `onProgress` gets 0..1 as the bytes go. */
function uploadWithProgress(body: FormData, onProgress: (share: number) => void): Promise<Project> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/projects`)
    for (const [k, v] of Object.entries(FROM_VOLTAGE)) xhr.setRequestHeader(k, v)
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && e.total > 0) onProgress(Math.min(1, e.loaded / e.total)) }
    xhr.onerror = () => reject(new ApiError(0, 'The upload did not reach the server.'))
    xhr.onload = () => {
      let parsed: unknown = null
      try { parsed = JSON.parse(xhr.responseText) } catch { parsed = null }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(parsed as Project)
      const detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? (parsed as { detail: unknown }).detail : null
      reject(new ApiError(xhr.status, typeof detail === 'string' ? detail : `Request failed (${xhr.status})`))
    }
    xhr.send(body)
  })
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) return failure(res)
  return (await res.json()) as T
}

/** The caller's projects, newest first. */
export const listProjects = async () =>
  (await get<{ projects: ProjectSummary[] }>('/projects')).projects

/** Everything needed to reopen a project. */
export const getProject = (id: string) => get<ProjectDetail>(`/projects/${id}`)

export const listVoices = () => get<{ default: string; voices: Voice[]; mine?: MyVoice[]; slots?: { used: number; limit: number } | null }>('/voices')

/** 20i: your own voice, uploaded under a name; the server clones it once. */
export async function uploadMyVoice(name: string, file: File): Promise<MyVoice> {
  const body = new FormData()
  body.append('name', name)
  body.append('consent', 'true')
  body.append('file', file)
  const res = await fetch(`${BASE}/voices/mine`, { method: 'POST', headers: FROM_VOLTAGE, body })
  if (!res.ok) return failure(res)
  return (await res.json()) as MyVoice
}
export async function deleteMyVoice(voiceId: string): Promise<void> {
  const res = await fetch(`${BASE}/voices/mine/${voiceId}`, { method: 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
}

/** Rename a speaker or set their voice; `voice_id: null` with `clear_voice`
 *  returns them to the chat's voice. */
export async function updateSpeaker(
  id: string, label: string, change: { name?: string; voice_id?: string; clear_voice?: boolean },
): Promise<Speaker[]> {
  const res = await fetch(`${BASE}/projects/${id}/speakers/${label}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...FROM_VOLTAGE },
    body: JSON.stringify(change),
  })
  if (!res.ok) return failure(res)
  return ((await res.json()) as { speakers: Speaker[] }).speakers
}

/** Finds who speaks when, for a project transcribed before speakers existed. */
export const detectSpeakers = (id: string) => post<Project>(`/projects/${id}/speakers/detect`)

export const getUsage = (id: string) => get<Usage>(`/projects/${id}/usage`)

/** Deletes the project and all its media — also how consent is withdrawn. */
export async function deleteProject(id: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${id}`, { method: 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
}

/** URL the browser can play a stored artifact from; supports range requests. */
export const artifactUrl = (projectId: string, sha256: string) =>
  `${BASE}/projects/${projectId}/artifacts/${sha256}`

export async function getJob(jobId: string): Promise<Job> {
  const res = await fetch(`${BASE}/jobs/${jobId}`)
  if (!res.ok) return failure(res)
  return (await res.json()) as Job
}

export class PollCancelled extends Error {}

/**
 * Polls a job until it finishes. `onUpdate` fires on every tick so the UI can
 * show progress; `shouldStop` lets a newer request abandon an older poll.
 */
export async function pollJob(
  jobId: string,
  { onUpdate, shouldStop, intervalMs = 300, timeoutMs = 300_000 }: {
    onUpdate?: (job: Job) => void
    shouldStop?: () => boolean
    intervalMs?: number
    timeoutMs?: number
  } = {},
): Promise<Job> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    if (shouldStop?.()) throw new PollCancelled('superseded')
    const job = await getJob(jobId)
    onUpdate?.(job)
    if (job.status === 'succeeded' || job.status === 'failed') return job
    if (Date.now() > deadline) throw new Error('Generation timed out.')
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

/** Renders the video: the added lines only, or (20e) with the proposals mixed in for "With proposals" playback. */
export const exportProject = (id: string, withProposals = false) =>
  post<ExportManifest>(`/projects/${id}/export`, withProposals ? { with_proposals: true } : undefined)

/** 20g: a line mixed louder or softer, nothing voiced again. BACKGROUND_DB is the level under the words. */
export const BACKGROUND_DB = -12
export const setEditLevel = (id: string, editId: string, levelDb: number) =>
  post<{ edit_id: string; reverted: string; candidate: Candidate }>(`/projects/${id}/edits/${editId}/level`, { level_db: levelDb })
export const setCandidateLevel = (id: string, candidateId: string, levelDb: number) =>
  post<Candidate>(`/projects/${id}/candidates/${candidateId}/level`, { level_db: levelDb })

/** Discard a proposal (20e): it leaves the plan. */
export const dismissItem = (id: string, planId: string, itemId: string) =>
  post<Plan>(`/projects/${id}/plans/${planId}/items/${itemId}/dismiss`)

/** Undoes an approved edit. The edit is kept and marked; the render skips it. */
export const revertEdit = (id: string, editId: string) =>
  post<{ edit_id: string; reverted: boolean }>(`/projects/${id}/edits/${editId}/revert`)

/** Remembers what Voltage may do in this project: how much on its own, how
 *  much a turn may spend, and how hard it thinks. */
export async function updateSettings(
  id: string, change: { autonomy?: Autonomy; turn_usd?: number; effort?: Effort },
): Promise<ProjectSettings> {
  const res = await fetch(`${BASE}/projects/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...FROM_VOLTAGE },
    body: JSON.stringify(change),
  })
  if (!res.ok) return failure(res)
  return ((await res.json()) as { settings: ProjectSettings }).settings
}

/** The same take placed somewhere else on the timeline; nothing is voiced again. */
export const moveCandidate = (id: string, candidateId: string, req: { start: number; mix?: Mix }) =>
  post<Candidate>(`/projects/${id}/candidates/${candidateId}/move`, req)

/** A kept line placed somewhere else: reverted and re-kept at the new place in one step. */
export const moveEdit = (id: string, editId: string, req: { start: number; mix?: Mix }) =>
  post<{ edit_id: string; reverted: string; candidate: Candidate }>(`/projects/${id}/edits/${editId}/move`, req)

/** Proposes taking a line out (20e): a plan item whose take is the room's own sound; Add it makes it so. */
export const removeLine = (id: string, span: { start: number; end: number }) =>
  post<{ item_id: string; candidate_id: string; selection: Selection; mix: Mix; plan: Plan }>(`/projects/${id}/lines/remove`, span)

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...FROM_VOLTAGE },
    body: JSON.stringify(body),
  })
  if (!res.ok) return failure(res)
  return (await res.json()) as T
}

export const getPlan = (id: string, planId: string) => get<Plan>(`/projects/${id}/plans/${planId}`)

/** UX-5: confirm the place Voltage guessed, or name the real one; empty clears it. */
export const confirmPlace = (id: string, place: string) => put<Sight>(`/projects/${id}/sight`, { place })

/** A frame of the picture (UX-5), for a clip with no speech. */
export const frameUrl = (projectId: string, index: number) => `${BASE}/projects/${projectId}/frames/${index}`

export interface PlanApproval {
  approved: { item_id: string; edit_id: string; overridden: boolean }[]
  skipped: { item_id: string; reason: string }[]
  export: ExportManifest | null
  plan: Plan
}

/** Approves the ready items named (every one, by default) and renders: Ship,
 *  and Keep on one line. */
export const approvePlan = (id: string, planId: string, req: { items?: string[]; override?: boolean } = {}) =>
  post<PlanApproval>(`/projects/${id}/plans/${planId}/approve`, req)

/** Voltage's first look at the clip (UX-2): an opening line and each speaker's
 *  role. Saved with the project; read once unless `again`. */
export const readProject = (id: string, again = false) =>
  post<Reading>(`/projects/${id}/reading`, again ? { again } : {})

/** Phase 20: one turn of Voltage with tools. Returns the job; its result is
 *  `{plan, reply, question}`. `approve` is the user's yes to what it asked. */
export const postTurn = (id: string, text: string, approve = false) =>
  post<Job>(`/projects/${id}/turns`, approve ? { text, approve } : { text })

/** The thread after a message (by seq): what Voltage said and did. */
export const getMessages = (id: string, after = 0) => get<ChatMessage[]>(`/projects/${id}/messages?after=${after}`)

/** Confirms the rights for a project uploaded without them — asked once, the
 *  first time a voice is about to be made (UX-3). */
export const grantConsent = (id: string) =>
  post<{ project_id: string; consent: { granted_at: string } }>(`/projects/${id}/consent`)

/** A variant: the same clip as a new project, with the plan as a draft. */
export const createVariant = (id: string) => post<Project>(`/projects/${id}/variants`)

/** Phase 9c: whether sign-in is on, and who is signed in. */
export interface Me { mode: 'off' | 'google'; user: { sub: string; email: string | null; name: string | null; picture: string | null } | null }
export const getMe = () => get<Me>('/auth/me')
/** Where the browser goes to sign in (a redirect to Google). */
export const loginUrl = `${BASE}/auth/login`
export const logout = () => post<{ signed_out: boolean }>('/auth/logout')

/** Moves a line of the original speech to another time, as spoken: room tone
 *  where it was, the words over the picture from `to`. Two edits, paired. */
export const shiftLine = (id: string, req: { start: number; end: number; to: number }) =>
  post<{ edit_id: string; removed_edit_id: string; candidate: Candidate; from: Selection; selection: Selection; mix: Mix }>(`/projects/${id}/lines/shift`, req)

// ── Volt (2026-10-18): the account pages ─────────────────────────────────────

/** Your defaults for new projects, and what still asks under Just do it. */
export const getUserSettings = () => get<UserSettings>('/me/settings')
export const updateUserSettings = (change: Partial<UserSettings>) => put<UserSettings>('/me/settings', change)
/** Everything of yours: every project, take and voice, and the consent records. */
export async function deleteAccount(): Promise<void> {
  const res = await fetch(`${BASE}/account`, { method: 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
}
/** Spend across your projects for a period. */
export const getUsageReport = (period: 'week' | 'month' | 'all' = 'month') => get<UsageReport>(`/usage?period=${period}`)
/** What went into a project's file. */
export const getReceipt = (id: string) => get<Receipt>(`/projects/${id}/receipt`)

// Voices: made in projects, kept, from a speaker, designed from words.
export const listMadeVoices = () => get<{ voices: MadeVoice[] }>('/voices/made')
export const keepVoice = (voiceId: string, name?: string) => post<MyVoice>('/voices/mine/keep', { voice_id: voiceId, ...(name ? { name } : {}) })
export const listCloneableSpeakers = () => get<{ speakers: CloneableSpeaker[] }>('/voices/speakers')
export const cloneSpeakerToMine = (projectId: string, label: string, name: string) =>
  post<MyVoice>('/voices/mine/from-speaker', { project_id: projectId, label, name, consent: true })
export const designVoicePreviews = (description: string) => post<{ previews: DesignedPreview[] }>('/voices/design', { description })
export const keepDesignedVoice = (generatedVoiceId: string, name: string, sha256: string, description: string) =>
  post<MyVoice>('/voices/mine/from-preview', { generated_voice_id: generatedVoiceId, name, sha256, description, consent: true })
/** A sample of one of your voices, or a designed preview, playable. */
export const voiceSampleUrl = (sha256: string) => `${BASE}/voices/sample/${sha256}`
