import type { Arrangement } from './transcript/arrange'
import type {
  Role,
  MyVoice, UserSettings, UsageReport, SpendSummary, MadeVoice, CloneableSpeaker, DesignedPreview, Receipt,
  Project, ExportManifest, Job, ProjectSummary, ProjectDetail, Usage, Voice, Speaker,
  ProjectSettings, Autonomy, Effort, Plan, Mix, Selection, Candidate, Reading, Sight, ChatMessage,
  ProjectFolder, ProjectDetailFolder, ProjectFile, HelpArticle, Onboarding, ProjectVoice,
} from './types'

const BASE = '/api'
// Phase 9c: a state-changing request says it came from Voltage; a cross-site
// form cannot set this header, which is the CSRF check when sign-in is on.
const FROM_VOLTAGE = { 'X-Requested-With': 'voltage' }

export class ApiError extends Error {
  status: number
  /** The parsed error body, when it was JSON (a 409 on a move carries the voices in use). */
  body: unknown

  constructor(status: number, message: string, body: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

/** Pulls FastAPI's `{detail: "..."}` out of an error body so rejection
 *  reasons ("That file has no video track.") reach the user intact. */
async function failure(res: Response): Promise<never> {
  const raw = await res.text()
  let message = raw
  let parsed: unknown = null
  try {
    parsed = JSON.parse(raw)
    const detail = (parsed as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string') message = detail
  } catch {
    // Not JSON — use the raw body.
  }
  throw new ApiError(res.status, message, parsed)
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
export async function createProject(file: File, consent: boolean, onProgress?: (share: number) => void, projectId: string | null = null): Promise<Project> {
  const body = new FormData()
  body.append('file', file)
  body.append('consent', String(consent))
  if (projectId) body.append('project_id', projectId)
  if (onProgress && typeof XMLHttpRequest !== 'undefined') return uploadWithProgress(body, onProgress)
  const res = await fetch(`${BASE}/videos`, { method: 'POST', headers: FROM_VOLTAGE, body })
  if (!res.ok) return failure(res)
  return (await res.json()) as Project
}

/** The same POST through XMLHttpRequest, which is the only way a browser
 *  reports upload progress (UX-6): `onProgress` gets 0..1 as the bytes go. */
function uploadWithProgress(body: FormData, onProgress: (share: number) => void): Promise<Project> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/videos`)
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

/** The caller's videos, newest first (folders, 2026-10-19): all, the standalone ones, or one project's. */
export const listVideos = async (filter: { project?: 'none' | string; recent?: number } = {}) => {
  const q = new URLSearchParams()
  if (filter.project) q.set('project', filter.project)
  if (filter.recent) q.set('recent', String(filter.recent))
  const qs = q.toString()
  return (await get<{ videos: ProjectSummary[] }>(`/videos${qs ? `?${qs}` : ''}`)).videos
}
/** @deprecated use listVideos */
export const listProjects = () => listVideos()

/** Everything needed to reopen a video. */
export const getProject = (id: string) => get<ProjectDetail>(`/videos/${id}`)
export const getVideo = getProject

/** Move a video into a project, or out to standalone. A 409 carries the project voices in use; answer with `voice`. */
export const moveVideo = (id: string, projectId: string | null, voice?: 'copy' | 'keep') =>
  patch<Project>(`/videos/${id}`, { project_id: projectId, ...(voice ? { voice } : {}) })

/** Folders. */
export const listFolders = async () => (await get<{ projects: ProjectFolder[] }>('/projects')).projects
export const createFolder = (name: string, brief = '') => post<ProjectFolder>('/projects', { name, brief })
export const getFolder = (id: string) => get<ProjectDetailFolder>(`/projects/${id}`)
export const updateFolder = (id: string, change: Partial<Pick<ProjectFolder, 'name' | 'brief' | 'settings' | 'ceiling_usd'>>) => patch<ProjectFolder>(`/projects/${id}`, change)
export const deleteFolder = (id: string, videos: 'delete' | 'keep') => del(`/projects/${id}?videos=${videos}`)
export async function uploadFolderFile(id: string, file: File): Promise<ProjectFile> {
  const body = new FormData()
  body.append('file', file)
  return request<ProjectFile>(`/projects/${id}/files`, { method: 'POST', body })
}
export const deleteFolderFile = (id: string, sha: string) => del(`/projects/${id}/files/${sha}`)
export const folderFileUrl = (id: string, sha: string) => `${BASE}/videos/${id}/files/${sha}`
export const shareVoice = (id: string, voiceId: string) => post<ProjectDetailFolder['voices']>(`/projects/${id}/voices`, { voice_id: voiceId })
export const unshareVoice = (id: string, voiceId: string) => del(`/projects/${id}/voices/${voiceId}`)
export const answerSuggestion = (id: string, sid: string, answer: 'accept' | 'dismiss') => post<ProjectDetailFolder>(`/projects/${id}/suggestions/${sid}/${answer}`, {})

/** Help and onboarding (2026-10-19). */
export const listHelp = async () => (await get<{ articles: HelpArticle[] }>('/help')).articles
export const searchHelp = async (q: string) => (await get<{ articles: HelpArticle[] }>(`/help/search?q=${encodeURIComponent(q)}`)).articles
export const getOnboarding = () => get<Onboarding>('/me/onboarding')
export const updateOnboarding = (change: Partial<Onboarding>) => put<Onboarding>('/me/onboarding', change)
/** The guided run: the sample ad as a tutorial video whose turns replay a recording; nothing is spent. */
export const startTutorial = () => post<Project>('/tutorial', {})

export const listVoices = () => get<{ default: string; voices: Voice[]; mine?: MyVoice[]; project?: ProjectVoice[]; slots?: { used: number; limit: number } | null }>('/voices')

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
  const res = await fetch(`${BASE}/videos/${id}/speakers/${label}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...FROM_VOLTAGE },
    body: JSON.stringify(change),
  })
  if (!res.ok) return failure(res)
  return ((await res.json()) as { speakers: Speaker[] }).speakers
}

/** Finds who speaks when, for a project transcribed before speakers existed. */
export const detectSpeakers = (id: string) => post<Project>(`/videos/${id}/speakers/detect`)

export const getUsage = (id: string) => get<Usage>(`/videos/${id}/usage`)

/** Deletes the project and all its media — also how consent is withdrawn. */
export async function deleteProject(id: string): Promise<void> {
  const res = await fetch(`${BASE}/videos/${id}`, { method: 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
}

/** URL the browser can play a stored artifact from; supports range requests. */
export const artifactUrl = (projectId: string, sha256: string) =>
  `${BASE}/videos/${projectId}/artifacts/${sha256}`

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
/** A render of the video as it is now (Final), or with the proposals mixed in. `requestId` comes back
 *  on the answer so the caller can keep only its latest request (bug 1, 2026-10-19). */
export const exportProject = (id: string, withProposals = false, requestId?: number) =>
  post<ExportManifest>(`/videos/${id}/export`, { ...(withProposals ? { with_proposals: true } : {}), ...(requestId !== undefined ? { request_id: requestId } : {}) })

/** 2026-10-20: a line's role in the mix and its fine-tune, nothing voiced again. The only
 *  speech in its span answers 409 with a question (RoleQuestion) unless `confirm`. */
export interface RoleChange { role: Role; offset_db?: number; confirm?: boolean }
export interface RoleQuestion { question: string; options: { label: string; detail?: string; role: Role; offset_db: number; confirm?: boolean }[] }
export const setEditRole = (id: string, editId: string, change: RoleChange) =>
  post<{ edit_id: string; reverted: string; candidate: Candidate }>(`/videos/${id}/edits/${editId}/role`, change)
export const setCandidateRole = (id: string, candidateId: string, change: RoleChange) =>
  post<Candidate>(`/videos/${id}/candidates/${candidateId}/role`, change)
/** The question in a 409 from a role change, if that is what it was. */
export const roleQuestion = (e: unknown): RoleQuestion | null => {
  const detail = e instanceof ApiError && e.status === 409 ? (e.body as { detail?: unknown } | null)?.detail : null
  return detail && typeof detail === 'object' && 'question' in detail ? detail as RoleQuestion : null
}

/** Discard a proposal (20e): it leaves the plan. */
export const dismissItem = (id: string, planId: string, itemId: string) =>
  post<Plan>(`/videos/${id}/plans/${planId}/items/${itemId}/dismiss`)

/** Undoes an approved edit. The edit is kept and marked; the render skips it. */
export const revertEdit = (id: string, editId: string) =>
  post<{ edit_id: string; reverted: boolean }>(`/videos/${id}/edits/${editId}/revert`)

/** Remembers what Voltage may do in this project: how much on its own, how
 *  much a turn may spend, and how hard it thinks. */
export async function updateSettings(
  id: string, change: { autonomy?: Autonomy; turn_usd?: number; effort?: Effort },
): Promise<ProjectSettings> {
  const res = await fetch(`${BASE}/videos/${id}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...FROM_VOLTAGE },
    body: JSON.stringify(change),
  })
  if (!res.ok) return failure(res)
  return ((await res.json()) as { settings: ProjectSettings }).settings
}

/** The same take placed somewhere else on the timeline; nothing is voiced again. */
export const moveCandidate = (id: string, candidateId: string, req: { start: number; mix?: Mix }) =>
  post<Candidate>(`/videos/${id}/candidates/${candidateId}/move`, req)

/** A kept line placed somewhere else: reverted and re-kept at the new place in one step. */
export const moveEdit = (id: string, editId: string, req: { start: number; mix?: Mix }) =>
  post<{ edit_id: string; reverted: string; candidate: Candidate }>(`/videos/${id}/edits/${editId}/move`, req)

/** Proposes taking a line out (20e): a plan item whose take is the room's own sound; Add it makes it so. */
export const removeLine = (id: string, span: { start: number; end: number }) =>
  post<{ item_id: string; candidate_id: string; selection: Selection; mix: Mix; plan: Plan }>(`/videos/${id}/lines/remove`, span)

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...FROM_VOLTAGE }, body: JSON.stringify(body) })
  if (!res.ok) return failure(res)
  return (await res.json()) as T
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
}

/** A multipart request (a file goes up); the browser sets the boundary. */
async function request<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...init, headers: { ...FROM_VOLTAGE, ...(init.headers ?? {}) } })
  if (!res.ok) return failure(res)
  return (await res.json()) as T
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...FROM_VOLTAGE },
    body: JSON.stringify(body),
  })
  if (!res.ok) return failure(res)
  return (await res.json()) as T
}

export const getPlan = (id: string, planId: string) => get<Plan>(`/videos/${id}/plans/${planId}`)

/** UX-5: confirm the place Voltage guessed, or name the real one; empty clears it. */
export const confirmPlace = (id: string, place: string) => put<Sight>(`/videos/${id}/sight`, { place })

/** A frame of the picture (UX-5), for a clip with no speech. */
export const frameUrl = (projectId: string, index: number) => `${BASE}/videos/${projectId}/frames/${index}`

export interface PlanApproval {
  approved: { item_id: string; edit_id: string; overridden: boolean }[]
  skipped: { item_id: string; reason: string }[]
  export: ExportManifest | null
  plan: Plan
}

/** Approves the ready items named (every one, by default) and renders: Ship,
 *  and Keep on one line. */
export const approvePlan = (id: string, planId: string, req: { items?: string[]; override?: boolean } = {}) =>
  post<PlanApproval>(`/videos/${id}/plans/${planId}/approve`, req)

/** Voltage's first look at the clip (UX-2): an opening line and each speaker's
 *  role. Saved with the project; read once unless `again`. */
export const readProject = (id: string, again = false) =>
  post<Reading>(`/videos/${id}/reading`, again ? { again } : {})

/** Phase 20: one turn of Voltage with tools. Returns the job; its result is
 *  `{plan, reply, question}`. `approve` is the user's yes to what it asked. */
export const postTurn = (id: string, text: string, approve = false) =>
  post<Job>(`/videos/${id}/turns`, approve ? { text, approve } : { text })

/** The thread after a message (by seq): what Voltage said and did. */
export const getMessages = (id: string, after = 0) => get<ChatMessage[]>(`/videos/${id}/messages?after=${after}`)

/** Confirms the rights for a project uploaded without them — asked once, the
 *  first time a voice is about to be made (UX-3). */
export const grantConsent = (id: string) =>
  post<{ video_id: string; consent_granted_at: string | null }>(`/videos/${id}/consent`)

/** A variant: the same clip as a new project, with the plan as a draft. */
export const createVariant = (id: string) => post<Project>(`/videos/${id}/variants`)

/** Phase 9c: whether sign-in is on, and who is signed in. */
export interface Me { mode: 'off' | 'google'; user: { sub: string; email: string | null; name: string | null; picture: string | null } | null }
export const getMe = () => get<Me>('/auth/me')
/** Where the browser goes to sign in (a redirect to Google). */
export const loginUrl = `${BASE}/auth/login`
export const logout = () => post<{ signed_out: boolean }>('/auth/logout')

// ── The arrangement (2026-10-19): the transcript's order is the playback order ──

/** One spoken line where it plays now, with what placed it there. */
export interface ArrangedLine {
  key: string
  /** 1-based, as the transcript numbers lines. */
  index: number
  text: string
  speaker: string | null
  orig_start: number
  orig_end: number
  length: number
  gap: number
  start: number
  end: number
  pinned: boolean
  /** The pinned line's start this one was pushed after, if it was. */
  pushed_after: number | null
  moved: boolean
  /** The replacement that travels with the line, if it has one. */
  replaced_by: string | null
}
export interface ArrangementView {
  arrangement: Arrangement
  duration: number
  lines: ArrangedLine[]
  /** Seconds the lines run past the end of the clip (0 when they fit). */
  overrun: number
  /** Whether the picture may hold its last frame that long. */
  ease_ok: boolean
  min_gap_default: number
  can_undo: boolean
}
export const getArrangement = (id: string) => get<ArrangementView>(`/videos/${id}/arrangement`)
/** The whole arrangement, as one action (one undo). */
export const putArrangement = (id: string, arrangement: Arrangement) => put<ArrangementView>(`/videos/${id}/arrangement`, arrangement)
export const undoArrangement = (id: string) => post<ArrangementView>(`/videos/${id}/arrangement/undo`)

// ── Volt (2026-10-18): the account pages ─────────────────────────────────────

/** Your defaults for new projects, and what still asks under Just do it. */
export const getUserSettings = () => get<UserSettings>('/me/settings')
export const updateUserSettings = (change: Partial<UserSettings>) => put<UserSettings>('/me/settings', change)
/** Everything of yours: every project, take and voice, and the consent records. */
export async function deleteAccount(): Promise<void> {
  const res = await fetch(`${BASE}/account`, { method: 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
}
/** Spend across your projects for a period; `scope` picks the totals: all, `none` (standalone), a project `f3` or a video `v:p2`. */
export const getUsageReport = (period: 'week' | 'month' | 'all' = 'month', scope: string = 'all') =>
  get<UsageReport>(`/usage?period=${period}${scope !== 'all' ? `&scope=${encodeURIComponent(scope)}` : ''}`)
/** Spend scopes: every scope for a video, a project, or (neither) the month, with the binding one. */
export const getSpend = (context: { video?: string; project?: string } = {}) =>
  get<SpendSummary>(context.video ? `/spend?video=${context.video}` : context.project ? `/spend?project=${context.project}` : '/spend')
/** What went into a project's file. */
export const getReceipt = (id: string) => get<Receipt>(`/videos/${id}/receipt`)

// Voices: made in projects, kept, from a speaker, designed from words.
export const listMadeVoices = () => get<{ voices: MadeVoice[] }>('/voices/made')
export const keepVoice = (voiceId: string, name?: string) => post<MyVoice>('/voices/mine/keep', { voice_id: voiceId, ...(name ? { name } : {}) })
export const listCloneableSpeakers = () => get<{ speakers: CloneableSpeaker[] }>('/voices/speakers')
export const cloneSpeakerToMine = (projectId: string, label: string, name: string) =>
  post<MyVoice>('/voices/mine/from-speaker', { video_id: projectId, label, name, consent: true })
export const designVoicePreviews = (description: string) => post<{ previews: DesignedPreview[] }>('/voices/design', { description })
export const keepDesignedVoice = (generatedVoiceId: string, name: string, sha256: string, description: string) =>
  post<MyVoice>('/voices/mine/from-preview', { generated_voice_id: generatedVoiceId, name, sha256, description, consent: true })
/** A sample of one of your voices, or a designed preview, playable. */
export const voiceSampleUrl = (sha256: string) => `${BASE}/voices/sample/${sha256}`
