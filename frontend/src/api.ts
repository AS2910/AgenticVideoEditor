import { signed } from './lib/media'
import type { Arrangement } from './transcript/arrange'
import type {
  LanguageSet, LanguagesMade, SyncStarted, Stage, StageMoved, EventPage,
  Suggestion, SuggestionKind, Understanding,
  Role,
  MyVoice, UserSettings, UsageReport, SpendSummary, MadeVoice, CloneableSpeaker, DesignedPreview, Receipt,
  Project, ExportManifest, Job, ProjectSummary, ProjectDetail, Usage, Voice, Speaker,
  ProjectSettings, Autonomy, Effort, Plan, Mix, Selection, Candidate, Reading, Sight, ChatMessage,
  ProjectFolder, ProjectDetailFolder, ProjectFile, HelpArticle, Onboarding, ProjectVoice,
  ActivityJob, TurnView, RenderState, BriefVersion, BriefChange, BriefUpdateRun, ProjectRule, RuleKind, RuleData, CheckPage, Batch, ExportPreset, ExportPresetPage, ExportPresetChange, Preflight, BatchExport, ShareLink, PublicShare,
  PublicComment, ReviewAnswer, ReviewComment, ReviewLinkRequest, BinItem, BinKind, BinRestored, Pin, SearchResult, ProjectTemplate, LearnedPage, ImportSource, MembersPage, WorkspaceView, InviteView, MemberRole, NotificationItem, NotificationSetting, AdminAnalytics, BillingView,
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
export const folderFileUrl = (id: string, sha: string) => signed(`${BASE}/projects/${id}/files/${sha}`)
export const shareVoice = (id: string, voiceId: string) => post<ProjectDetailFolder['voices']>(`/projects/${id}/voices`, { voice_id: voiceId })
export const unshareVoice = (id: string, voiceId: string) => del(`/projects/${id}/voices/${voiceId}`)
export const answerSuggestion = (id: string, sid: string, answer: 'accept' | 'dismiss') => post<ProjectDetailFolder>(`/projects/${id}/suggestions/${sid}/${answer}`, {})
/** F2/A1: the brief's versions, newest first, and the word diff between two (0 = no brief). */
export const listBriefVersions = (id: string) => get<{ current: number | null; versions: BriefVersion[] }>(`/projects/${id}/briefs`)
export const diffBriefVersions = (id: string, a: number, b: number) => get<{ a: number; b: number; changes: BriefChange[] }>(`/projects/${id}/briefs/diff?a=${a}&b=${b}`)
/** A1: the latest "Bring up to date" run (null before the first), and starting one. */
export const getBriefUpdate = (id: string) => get<{ run: BriefUpdateRun | null }>(`/projects/${id}/brief-update`)
export const startBriefUpdate = (id: string) => post<{ run: BriefUpdateRun }>(`/projects/${id}/brief-update`, {})
/** F3/A3: the project's words (how to say a term, banned words, required lines). */
export const listRules = async (id: string) => (await get<{ rules: ProjectRule[]; rules_version: number }>(`/projects/${id}/rules`)).rules
/** `source: 'transcript'`: a word learned from the editor's transcript (A3), counted for G7. */
export const addRule = (id: string, kind: RuleKind, data: RuleData, source?: 'transcript') => post<ProjectRule>(`/projects/${id}/rules${source ? `?source=${source}` : ''}`, { kind, data })
export const updateRule = (id: string, ruleId: number, data: RuleData) => patch<ProjectRule>(`/projects/${id}/rules/${ruleId}`, { data })
export const deleteRule = (id: string, ruleId: number) => del(`/projects/${id}/rules/${ruleId}`)
export async function uploadRuleAudio(id: string, ruleId: number, file: File): Promise<ProjectRule> {
  const body = new FormData()
  body.append('file', file)
  return request<ProjectRule>(`/projects/${id}/rules/${ruleId}/audio`, { method: 'POST', body })
}
export const deleteRuleAudio = (id: string, ruleId: number) => request<ProjectRule>(`/projects/${id}/rules/${ruleId}/audio`, { method: 'DELETE' })
/** The clip's address; `v` (the clip's hash) makes a new clip a new address. */
export const ruleAudioUrl = (id: string, ruleId: number, v = '') => signed(`${BASE}/projects/${id}/rules/${ruleId}/audio${v ? `?v=${v.slice(0, 12)}` : ''}`)

/** A2: the project check: the latest run and its issues, running one (full adds the priced text pass), and an issue's verbs. */
export const getProjectCheck = (id: string) => get<CheckPage>(`/projects/${id}/check`)
export const startProjectCheck = (id: string, mode: 'full' | 'rules') => post<CheckPage>(`/projects/${id}/check`, { mode })
export const ignoreCheckIssue = (id: string, issueId: number) => post<CheckPage>(`/projects/${id}/check/issues/${issueId}/ignore`, {})
export const fixCheckIssue = (id: string, issueId: number, videoId: string) => post<{ video_id: string; job_id: string; t: number | null }>(`/projects/${id}/check/issues/${issueId}/fix`, { video_id: videoId })
export const fixCheckIssueEverywhere = (id: string, issueId: number) => post<CheckPage>(`/projects/${id}/check/issues/${issueId}/fix-all`, {})
// F4/B1 (projects.batch): one goal across the project's videos, one gate, a board.
export const listBatches = (id: string) => get<{ batches: Batch[] }>(`/projects/${id}/batches`)
export const planBatch = (id: string, body: { source: 'ask' | 'fix'; goal?: string; issue_id?: number; video_ids?: string[] }) => post<Batch>(`/projects/${id}/batches`, body)
export const goBatch = (id: string, batchId: string) => post<Batch>(`/projects/${id}/batches/${batchId}/go`)
export const cancelBatch = (id: string, batchId: string) => post<Batch>(`/projects/${id}/batches/${batchId}/cancel`)
export const answerBatchVideo = (id: string, batchId: string, videoId: string, text: string) => post<Batch>(`/projects/${id}/batches/${batchId}/videos/${videoId}/answer`, { text })
export const addAllBatch = (id: string, batchId: string, confirmStage = false) => post<Batch>(`/projects/${id}/batches/${batchId}/add-all`, confirmStage ? { confirm_stage: true } : undefined)
export const undoBatchAdd = (id: string, batchId: string, videoId: string) => post<Batch>(`/projects/${id}/batches/${batchId}/videos/${videoId}/undo-add`)
// C1 (projects.review): a video's stage, moved by hand; the project's activity feed (F7).
export const moveStage = (videoId: string, to: Stage) => post<StageMoved>(`/videos/${videoId}/stage`, { to })
export const getProjectEvents = (id: string, before?: number | null, limit = 30) =>
  get<EventPage>(`/projects/${id}/events?limit=${limit}${before ? `&before=${before}` : ''}`)
/** C1: the 409 an add answers on an Approved video (the user says Add anyway or Cancel), if that is what it was. */
export interface StageHold { code: 'stage_approved'; message: string; videos: string[]; options: string[] }
export const stageHold = (e: unknown): StageHold | null => {
  const detail = e instanceof ApiError && e.status === 409 ? (e.body as { detail?: unknown } | null)?.detail : null
  return detail && typeof detail === 'object' && (detail as { code?: unknown }).code === 'stage_approved' ? detail as StageHold : null
}
// B3 (projects.batch): export presets, batch export, its zip and share link (F6).
export const listExportPresets = (id: string) => get<ExportPresetPage>(`/projects/${id}/export-presets`)
export const addExportPreset = (id: string, body: ExportPresetChange) => post<ExportPreset>(`/projects/${id}/export-presets`, body)
export const changeExportPreset = (id: string, presetId: number, body: ExportPresetChange) => patch<ExportPreset>(`/projects/${id}/export-presets/${presetId}`, body)
export const removeExportPreset = (id: string, presetId: number) => del(`/projects/${id}/export-presets/${presetId}`)
export const getExportPreflight = (id: string) => get<Preflight>(`/projects/${id}/exports/preflight`)
export const startBatchExport = (id: string, body: { video_ids: string[]; preset_ids: number[] }) => post<BatchExport>(`/projects/${id}/exports`, body)
export const listBatchExports = (id: string) => get<{ exports: BatchExport[] }>(`/projects/${id}/exports`)
export const shareBatchExport = (id: string, exportId: string) => post<ShareLink>(`/projects/${id}/exports/${exportId}/share`, {})
export const revokeShare = (id: string, shareId: string) => del(`/projects/${id}/shares/${shareId}`)
export const exportZipUrl = (id: string, exportId: string) => signed(`${BASE}/projects/${id}/exports/${exportId}/zip`)
export const exportFileUrl = (id: string, exportId: string, index: number, download = false) => signed(`${BASE}/projects/${id}/exports/${exportId}/files/${index}${download ? '?download=true' : ''}`)
// F6: a share link opened with no account.
export const openShare = (token: string) => get<PublicShare>(`/share/${encodeURIComponent(token)}`)
export const sharedFileUrl = (token: string, fileId: string, download = false) => `${BASE}/share/${encodeURIComponent(token)}/files/${encodeURIComponent(fileId)}${download ? '?download=true' : ''}`
export const sharedZipUrl = (token: string) => `${BASE}/share/${encodeURIComponent(token)}/zip`
// C2 (projects.review): review links, the reviewer's page (no account) and the owner's comments.
export const createProjectReviewLink = (id: string, body: ReviewLinkRequest & { videos: string[] }) =>
  post<ShareLink>(`/projects/${id}/shares`, { scope: 'project', role: 'reviewer', ...body })
export const listProjectShares = (id: string) => get<{ shares: ShareLink[] }>(`/projects/${id}/shares`)
export const listReviewLinks = (videoId: string) => get<{ links: ShareLink[] }>(`/videos/${videoId}/review-links`)
export const createReviewLink = (videoId: string, body: ReviewLinkRequest) => post<ShareLink>(`/videos/${videoId}/review-links`, body)
export const revokeReviewLink = (videoId: string, shareId: string) => del(`/videos/${videoId}/review-links/${shareId}`)
const shareBase = (token: string) => `/share/${encodeURIComponent(token)}`
export const reviewComment = (token: string, body: { video_id: string; at_s: number; text: string; version: number | null; name?: string }) =>
  post<PublicComment>(`${shareBase(token)}/comments`, body)
export const reviewAnswer = (token: string, answer: 'approve' | 'changes', body: { video_id: string; version: number | null; note?: string; name?: string }) =>
  post<{ video_id: string; answer: ReviewAnswer }>(`${shareBase(token)}/${answer}`, body)
export const listReviewComments = (videoId: string) => get<{ comments: ReviewComment[]; open: number }>(`/videos/${videoId}/comments`)
export const replyReviewComment = (videoId: string, commentId: number, text: string) => post<ReviewComment>(`/videos/${videoId}/comments/${commentId}/replies`, { text })
export const resolveReviewComment = (videoId: string, commentId: number, resolved: boolean) => post<ReviewComment>(`/videos/${videoId}/comments/${commentId}/resolve`, { resolved })

/** Help and onboarding (2026-10-19). */
export const listHelp = async () => (await get<{ articles: HelpArticle[] }>('/help')).articles
export interface KnownIssues { title: string; updated: string | null; summary: string; sections: { heading: string; body: string }[] }
export const getKnownIssues = () => get<KnownIssues>('/help/known-issues')
export const searchHelp = async (q: string) => (await get<{ articles: HelpArticle[] }>(`/help/search?q=${encodeURIComponent(q)}`)).articles
export const getOnboarding = () => get<Onboarding>('/me/onboarding')
export const updateOnboarding = (change: Partial<Onboarding>) => put<Onboarding>('/me/onboarding', change)
/** The guided run: the sample ad as a tutorial video whose turns replay a recording; nothing is spent. */
export const startTutorial = () => post<Project>('/tutorial', {})

export const listVoices = () => get<{ default: string; voices: Voice[]; mine?: MyVoice[]; project?: ProjectVoice[]; slots?: { used: number; limit: number } | null; cloning?: boolean }>('/voices')

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
  signed(`${BASE}/videos/${projectId}/artifacts/${sha256}`)

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
export async function exportProject(id: string, withProposals = false, requestId?: number, purpose: 'preview' | 'export' = 'preview',
  onJob?: (job: ActivityJob) => void): Promise<ExportManifest> {
  const body = { ...(withProposals ? { with_proposals: true } : {}), ...(requestId !== undefined ? { request_id: requestId } : {}), ...(purpose === 'export' ? { purpose } : {}) }
  // Run 4, item 3d: the request never renders. A render not made yet comes back as its job;
  // once the job is done, the same request answers with the render (the edits may have moved
  // on meanwhile: then it is their render's job, followed the same way).
  for (let round = 0; round < 10; round++) {
    const out = await post<ExportManifest | { render_job: ActivityJob; request_id: number | null }>(`/videos/${id}/export`, body)
    if (!('render_job' in out) || !out.render_job) return out as ExportManifest
    onJob?.(out.render_job)
    await jobSettled(id, out.render_job.job_id)
  }
  throw new ApiError(503, 'The render kept changing. Try again.')
}

const JOB_POLL_MS = 1000

/** Waits for a job of the video to finish; a failed or cancelled one throws its reason. */
async function jobSettled(id: string, jobId: string): Promise<ActivityJob> {
  for (;;) {
    const job = (await getJobs(id)).jobs.find((j) => j.job_id === jobId)
    if (job && job.status === 'done') return job
    if (job && (job.status === 'failed' || job.status === 'cancelled')) throw new ApiError(500, job.error_text ?? 'The render failed.')
    await new Promise((r) => setTimeout(r, JOB_POLL_MS))
  }
}

/** 2026-10-20: a line's role in the mix and its fine-tune, nothing voiced again. The only
 *  speech in its span answers 409 with a question (RoleQuestion) unless `confirm`. */
export interface RoleChange { role: Role; offset_db?: number; confirm?: boolean; confirm_stage?: boolean }
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
export const dismissItem = (id: string, planId: string, itemId: string, reason?: string) =>
  post<Plan & { decision_id?: number | null }>(`/videos/${id}/plans/${planId}/items/${itemId}/dismiss`, reason ? { reason } : undefined)

/** p61: a line that ran long takes the take already voiced, the picture easing so it fits. Nothing is paid. */
export const easeItem = (id: string, planId: string, itemId: string) =>
  post<Plan>(`/videos/${id}/plans/${planId}/items/${itemId}/ease`)

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
export const moveEdit = (id: string, editId: string, req: { start: number; mix?: Mix; confirm_stage?: boolean }) =>
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
export const frameUrl = (projectId: string, index: number) => signed(`${BASE}/videos/${projectId}/frames/${index}`)

export interface PlanApproval {
  approved: { item_id: string; edit_id: string; overridden: boolean }[]
  skipped: { item_id: string; reason: string }[]
  export: ExportManifest | null
  /** Run 4, item 3: the render the Add started, as a job (the answer never waits for it); null when nothing was added. */
  render_job?: ActivityJob | null
  plan: Plan
}

/** Approves the ready items named (every one, by default) and starts their
 *  render as a job: Ship, and Keep on one line. */
export const approvePlan = (id: string, planId: string, req: { items?: string[]; override?: boolean; confirm_stage?: boolean } = {}) =>
  post<PlanApproval>(`/videos/${id}/plans/${planId}/approve`, req)

/** Voltage's first look at the clip (UX-2): an opening line and each speaker's
 *  role. Saved with the project; read once unless `again`. */
export const readProject = (id: string, again = false) =>
  post<Reading>(`/videos/${id}/reading`, again ? { again } : {})

/** Phase 20: one turn of Voltage with tools. Returns the job; its result is
 *  `{plan, reply, question}`. `approve` is the user's yes to what it asked. */
export const postTurn = (id: string, text: string, approve = false) =>
  post<Job>(`/videos/${id}/turns`, approve ? { text, approve } : { text })

/** The way through a question the turn's cap caused: this turn's cap rises by
 *  exactly what the step needs and the same turn carries on. Refused (409),
 *  naming the scope, past the video's or the project's ceiling. */
export const postAllowMore = (id: string) => post<Job>(`/videos/${id}/turns/allow-more`, {})

/** The thread after a message (by seq): what Voltage said and did. */
export const getMessages = (id: string, after = 0) => get<ChatMessage[]>(`/videos/${id}/messages?after=${after}`)

/** Confirms the rights for a project uploaded without them — asked once, the
 *  first time a voice is about to be made (UX-3). */
export const grantConsent = (id: string, livenessId?: string | null) =>
  post<{ video_id: string; consent_granted_at: string | null }>(`/videos/${id}/consent`, livenessId ? { liveness_id: livenessId } : undefined)

/** A variant: the same clip as a new project, with the plan as a draft. */
export const createVariant = (id: string) => post<Project>(`/videos/${id}/variants`)

/** B2: a video's language set (its master's, for a version). */
export const getLanguages = (videoId: string) => get<LanguageSet>(`/videos/${videoId}/languages`)
/** B2: Make language versions; `dry_run` gives the gate's numbers and makes nothing. */
export const makeLanguages = (videoId: string, body: { languages: string[]; voice: 'same' | 'designed'; dry_run?: boolean }) =>
  post<LanguagesMade>(`/videos/${videoId}/languages`, body)
/** B2: Sync this change: one turn on the version for only the master's changed lines. */
export const syncLanguage = (videoId: string, confirmStage = false) => post<SyncStarted>(`/videos/${videoId}/sync`, confirmStage ? { confirm_stage: true } : undefined)

/** Phase 9c: whether sign-in is on, and who is signed in. */
export interface Me { mode: 'off' | 'google' | 'accounts'; user: { sub: string; email: string | null; name: string | null; picture: string | null; provider?: 'google' | 'email' | 'acct' } | null }
/** Launch item 5: what sign-in this Voltage offers. */
export interface AuthOptions { mode: Me['mode']; google: boolean; password: boolean; email_link: boolean; invite_only: boolean; terms_version: string }
export const getAuthOptions = () => get<AuthOptions>('/auth/options')
export const signUp = (email: string, password: string, inviteCode?: string) =>
  post<{ sent: boolean; message: string }>('/auth/signup', { email, password, accept_terms: true, ...(inviteCode ? { invite_code: inviteCode } : {}) })
export const passwordLogin = (email: string, password: string) => post<{ signed_in: boolean; email: string }>('/auth/password/login', { email, password })
export const resendVerify = (email: string) => post<{ sent: boolean; message: string }>('/auth/verify/resend', { email })
export const forgotPassword = (email: string) => post<{ sent: boolean; message: string }>('/auth/password/forgot', { email })
export const resetPassword = (token: string, password: string) => post<{ signed_in: boolean; email: string }>('/auth/password/reset', { token, password })
export const changeEmail = (newEmail: string, password: string) => post<{ sent: boolean; message: string }>('/auth/change-email', { new_email: newEmail, password })
export const getMe = () => get<Me>('/auth/me')
/** Where the browser goes to sign in (a redirect to Google). */
/** `terms=1`: the button beside it says continuing accepts the Terms (a new Google account records it). */
export const loginUrl = `${BASE}/auth/login?terms=1`
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
export const putArrangement = (id: string, arrangement: Arrangement, confirmStage = false) =>
  put<ArrangementView>(`/videos/${id}/arrangement`, confirmStage ? { ...arrangement, confirm_stage: true } : arrangement)
export const undoArrangement = (id: string) => post<ArrangementView>(`/videos/${id}/arrangement/undo`)

// ── Volt (2026-10-18): the account pages ─────────────────────────────────────

/** Your defaults for new projects, and what still asks under Just do it. */
export const getUserSettings = () => get<UserSettings>('/me/settings')
export const updateUserSettings = (change: Partial<UserSettings>) => put<UserSettings>('/me/settings', change)
/** Step 0 (FLAGS): the feature flags that are on for you (phase flags such as `projects.batch`). */
// D3: the Bin.
export const getBin = () => get<{ items: BinItem[]; days: number }>('/bin')
export const restoreFromBin = (kind: BinKind, id: string) => post<BinRestored>(`/bin/${kind}/${id}/restore`)
// D4: pins, archive, search.
export const getPins = async () => (await get<{ pins?: Pin[] }>('/pins')).pins ?? []
export async function setPin(kind: Pin['kind'], id: string, pinned: boolean): Promise<void> {
  const res = await fetch(`${BASE}/pins/${kind}/${id}`, { method: pinned ? 'PUT' : 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
}
export const listArchivedFolders = async () => (await get<{ projects?: ProjectFolder[] }>('/projects?archived=true')).projects ?? []
export const archiveFolder = (id: string) => post<ProjectFolder>(`/projects/${id}/archive`)
export async function unarchiveFolder(id: string): Promise<ProjectFolder> {
  const res = await fetch(`${BASE}/projects/${id}/archive`, { method: 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
  return (await res.json()) as ProjectFolder
}
export const searchEverything = (q: string) => get<SearchResult>(`/search?q=${encodeURIComponent(q)}`)
// G1: the sample project (once per new owner) and import from a link.
export const ensureSample = () => post<{ created: boolean; project_id: string | null }>('/me/sample')
export const getImportSources = () => get<{ sources: ImportSource[]; max_bytes: number }>('/imports/sources')
export const startImport = (url: string, projectId: string | null) => post<ActivityJob>('/imports', { url, project_id: projectId })
export const getImport = (jobId: string) => get<ActivityJob>(`/imports/${encodeURIComponent(jobId)}`)
// G2: the workspace, members and invites, email sign-in.
export const getWorkspace = () => get<WorkspaceView>('/workspace')
export const listMembers = () => get<MembersPage>('/workspace/members')
export const sendInvite = (email: string, role: MemberRole, spendLimit: number | null, projectIds: string[] = []) =>
  post<MembersPage>('/workspace/invites', { email, role, spend_limit_usd: spendLimit, ...(role === 'reviewer' ? { project_ids: projectIds } : {}) })
/** Launch item 1: the projects a Reviewer sees (replaces what was shared). */
export const setMemberShares = (member: string, projectIds: string[]) =>
  put<MembersPage>(`/workspace/members/${encodeURIComponent(member)}/shares`, { project_ids: projectIds })
export const revokeInvite = (id: string) => request<MembersPage>(`/workspace/invites/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const changeMember = (member: string, change: { role?: MemberRole; spend_limit_usd?: number | null }) => patch<MembersPage>(`/workspace/members/${encodeURIComponent(member)}`, change)
export const removeMember = (member: string) => request<MembersPage>(`/workspace/members/${encodeURIComponent(member)}`, { method: 'DELETE' })
export const switchWorkspace = (workspaceId: string | null) => post<{ workspace_id: string | null }>('/workspace/switch', { workspace_id: workspaceId })
export const openInvite = (token: string) => get<InviteView>(`/invites/${encodeURIComponent(token)}`)
export const acceptInvite = (token: string) => post<{ workspace_id: string; workspace_name: string; role: MemberRole; role_word: string }>(`/invites/${encodeURIComponent(token)}/accept`)
export const emailSignInAvailable = () => get<{ available: boolean }>('/auth/email')
export const sendSignInLink = (email: string) => post<{ sent: boolean; email: string }>('/auth/email', { email })
// G4: the bell and its settings.
export const listNotifications = () => get<{ items: NotificationItem[]; unread: number }>('/me/notifications')
export const getNotificationCount = () => get<{ unread: number }>('/me/notifications/count')
export const markNotificationsRead = (which: { ids?: number[]; all?: boolean }) => post<{ unread: number }>('/me/notifications/read', which)
export const getNotificationSettings = () => get<{ kinds: NotificationSetting[] }>('/me/notifications/settings')
export const putNotificationSettings = (changes: Record<string, { in_app?: boolean; email?: boolean }>) => put<{ kinds: NotificationSetting[] }>('/me/notifications/settings', changes)
/** G7: whether the internal admin page is yours, and its numbers (admins only). */
export const getMeAdmin = async () => (await get<{ admin: boolean }>('/me/admin')).admin
export const getAdminAnalytics = () => get<AdminAnalytics>('/admin/analytics')
/** Launch item 3: today's spend across everyone, the cap, and the kill switch. */
export interface AdminSpend { paused: boolean; reason: 'switch' | 'daily_cap' | null; switch: boolean; today_usd: number; cap_usd: number | null; resumes_at: string | null; by_vendor: Record<string, number> }
export const getAdminSpend = () => get<AdminSpend>('/admin/spend')
/** Launch item 9: every email Voltage sends, with sample data (admins only; nothing is sent). */
export interface EmailKind { kind: string; label: string }
export interface EmailPreview extends EmailKind { subject: string; html: string; text: string }
export const getEmailKinds = () => get<{ kinds: EmailKind[] }>('/admin/emails/preview')
export const getEmailPreview = (kind: string) => get<EmailPreview>(`/admin/emails/preview/${encodeURIComponent(kind)}`)
export const setPaidPause = (paused: boolean) => put<AdminSpend>('/admin/paid-pause', { paused })
/** Launch item 10: one person's feature flags, and turning one on or off (null: back to the default). */
export interface AdminFlags { owner: string; profile: string | null; flags: { flag: string; on: boolean; source: 'owner' | 'everyone' | 'profile' | 'default_owner' | 'default' | 'off' }[] }
export const getAdminFlags = (owner: string) => get<AdminFlags>(`/admin/flags?owner=${encodeURIComponent(owner)}`)
export const setAdminFlag = (owner: string, flag: string, enabled: boolean | null) => put<AdminFlags>('/admin/flags', { owner, flag, enabled })
/** Rehearsal item 10: find a person, read their account, act on it; every action lands in the audit trail. */
export interface AdminUserHit { owner: string; emails: string[]; kind: string; seen_as: string[]; suspended: boolean }
export interface AdminAuditEntry { id: number; at: string; actor: string; action: string; target: string | null; reason: string; details: Record<string, unknown> }
export interface AdminUser {
  owner: string; emails: string[]; kind: string; is_admin: boolean
  account: { created_at: string; verified_at: string | null; deleted_at: string | null } | null
  suspended: { reason: string; suspended_by: string; suspended_at: string } | null
  workspace: { workspace_id: string; name: string | null; members: { member: string; email: string | null; name: string | null; role: string; joined_at: string; spend_limit_usd: number | null }[] }
  member_of: { workspace_id: string; name: string; role: string; owner?: string }[]
  spend: { today_usd: number; month_usd: number; all_time_usd: number; by_vendor: Record<string, number>; by_vendor_month: Record<string, number> }
  credits: { granted: number; used: number; left: number; lapsed: number; grants: { kind: string; credits: number; reference: string; at: string; expires_at: string | null; left: number }[] } | null
  invoices: { id: number; number: string; description: string; total: number; currency: string; provider: string; test_mode: boolean; issued_at: string; refunded: boolean }[]
  jobs: { job_id: string; video_id: string; kind: string; status: string; error_code: string | null; error_text: string | null; created_at: string; finished_at: string | null; cost_usd: number | null }[]
  errors: { id: number; owner: string | null; source: string; message: string; location: string; at: string }[]
  audit: AdminAuditEntry[]
}
const ownerPath = (owner: string) => `/admin/users/${encodeURIComponent(owner)}`
export const findAdminUsers = async (q: string) => (await get<{ users: AdminUserHit[] }>(`/admin/users?q=${encodeURIComponent(q)}`)).users
export const getAdminUser = (owner: string) => get<AdminUser>(ownerPath(owner))
export const grantAdminCredits = (owner: string, credits: number, reason: string) => post<AdminUser>(`${ownerPath(owner)}/grant`, { credits, reason })
export const refundAdmin = (owner: string, reason: string, target: { invoice_id: number } | { credits: number }) => post<AdminUser>(`${ownerPath(owner)}/refund`, { reason, ...target })
export const suspendAdminUser = (owner: string, reason: string) => post<AdminUser>(`${ownerPath(owner)}/suspend`, { reason })
export const unsuspendAdminUser = (owner: string, reason: string) => post<AdminUser>(`${ownerPath(owner)}/unsuspend`, { reason })
export const revokeAdminShare = (link: string, reason: string) => {
  const id = link.trim().split('#s/').pop()?.split('.')[0] ?? ''
  return post<{ share_id: string; owner: string; state: string }>(`/admin/shares/${encodeURIComponent(id)}/revoke`, { reason })
}
/** Rehearsal item 11: "Send feedback" from the help menu, and the admins' list of it. */
export interface BetaFeedbackSend { message: string; route: string; video_id: string | null; job_id: string | null; app_version: string; screenshot: File | null }
export async function sendBetaFeedback(f: BetaFeedbackSend): Promise<{ id: number; said: string }> {
  const body = new FormData()
  body.append('message', f.message)
  body.append('route', f.route)
  if (f.video_id) body.append('video_id', f.video_id)
  if (f.job_id) body.append('job_id', f.job_id)
  body.append('app_version', f.app_version)
  if (f.screenshot) body.append('screenshot', f.screenshot)
  const res = await fetch(`${BASE}/beta-feedback`, { method: 'POST', headers: FROM_VOLTAGE, body })
  if (!res.ok) return failure(res)
  return (await res.json()) as { id: number; said: string }
}
export type BetaStatus = 'new' | 'seen' | 'done'
export interface BetaFeedbackItem { id: number; owner: string; message: string; route: string; video_id: string | null; job_id: string | null; app_version: string; user_agent: string; screenshot: boolean; screenshot_type: string | null; status: BetaStatus; status_by: string | null; status_at: string | null; created_at: string }
export const listBetaFeedback = (status?: BetaStatus) => get<{ items: BetaFeedbackItem[]; counts: Record<BetaStatus, number> }>(`/admin/beta-feedback${status ? `?status=${status}` : ''}`)
export const setBetaFeedbackStatus = (id: number, status: BetaStatus) => put<BetaFeedbackItem>(`/admin/beta-feedback/${id}`, { status })
export const betaScreenshotUrl = (id: number) => `${BASE}/admin/beta-feedback/${id}/screenshot`
/** Run 4 item 2: consent checks waiting for a person (admins). */
export interface ConsentReview {
  id: string; owner: string; video_id: string; speaker: string | null; sentence: string; status: ConsentStatus | 'withdrawn' | 'expired'
  reason: string; heard: string | null; wer: number | null; similarity: number | null; seconds: number | null; rule: string
  asr_model: string; speaker_model: string; pass_at: number | null; review_from: number | null; created_at: string; checked_at: string | null
  reviewed_by: string | null; review_reason: string; reviewed_at: string | null; has_recording: boolean
}
export const listConsentReviews = (status: 'review' | 'decided' = 'review') => get<{ items: ConsentReview[]; waiting: number }>(`/admin/consent-reviews?status=${status}`)
export const decideConsentReview = (id: string, decision: 'approve' | 'reject', reason: string) => post<ConsentReview>(`/admin/consent-reviews/${id}`, { decision, reason })
export const consentRecordingUrl = (id: string) => `${BASE}/admin/consent-reviews/${id}/recording`
export const consentSourceUrl = (id: string) => `${BASE}/admin/consent-reviews/${id}/source`
export const getAdminAudit = async (limit = 50) => (await get<{ entries: AdminAuditEntry[] }>(`/admin/audit?limit=${limit}`)).entries
/** Beta kit: the three questions after a first export. */
export interface BetaQuestion { id: 'useful' | 'almost_stopped' | 'would_pay'; text: string; choices?: [string, string][]; optional?: boolean }
export const getBetaSurvey = () => get<{ due: boolean; questions: BetaQuestion[] }>('/me/beta-survey')
export const markBetaSurveyShown = (videoId: string | null) => post<{ due: boolean }>('/me/beta-survey/shown', { video_id: videoId })
export const answerBetaSurvey = (a: { useful: string; almost_stopped: string; would_pay: string; video_id: string | null }) => post<{ said: string }>('/me/beta-survey', a)
export interface BetaPerson {
  owner: string; emails: string[]; since: string; last_active: string | null; exports: number; spend_usd: number; credits_given: number
  feedback: { messages: number; latest: string | null }
  survey: { useful: string | null; almost_stopped: string | null; would_pay: string | null; shown_at: string; answered_at: string | null } | null
  errors: { count: number; latest: string | null }
}
export interface BetaView { people: BetaPerson[]; survey: { shown: number; answered: number; useful: Record<string, number>; would_pay: Record<string, number> }; credits_each: number }
export const getAdminBeta = () => get<BetaView>('/admin/beta')
export const joinBeta = (who: string, email = true) => post<{ owner: string; joined: boolean; granted: boolean; credits: number; emailed: boolean }>('/admin/beta/join', { who, email })
export const getMyFlags = async () => (await get<{ flags: string[] }>('/me/flags')).flags
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
export const voiceSampleUrl = (sha256: string) => signed(`${BASE}/voices/sample/${sha256}`)

// ── 2026-10-20: chips from this video, and what Voltage sees in it ───────────
export const getSuggestions = (id: string) => get<{ suggestions: Suggestion[]; source: 'turn' | 'reading' | 'generic' }>(`/videos/${id}/suggestions`)
/** What people do with the chips, by kind; never in the way of the editor. */
export const chipEvent = (id: string, event: 'shown' | 'clicked' | 'sent', kind: SuggestionKind, label: string, edited = false) => {
  void post(`/videos/${id}/suggestions/events`, { event, kind, label, edited }).catch(() => {})
}
export const getUnderstanding = (id: string) => get<Understanding>(`/videos/${id}/understanding`)
export const correctUnderstanding = (id: string, change: { text: string; beat_at?: number; label?: string; remove?: boolean }) =>
  post<Understanding>(`/videos/${id}/understanding/corrections`, change)
export const setStyle = (id: string, line: string, accepted = true) => put<Understanding>(`/videos/${id}/style`, { line, accepted })

// ── One processing model (2026-10-20) ─────────────────────────────────────────

/** The video's jobs, newest first: `active` for what is queued or running (and the turn's own), else the last 50. */
export const getJobs = (id: string, active = false) =>
  get<{ jobs: ActivityJob[]; turn: TurnView | null }>(`/videos/${id}/jobs${active ? '?active=1' : ''}`)
/** Try a failed job again through the same flow. */
export const retryJob = (id: string, jobId: string) => post<ActivityJob>(`/videos/${id}/jobs/${jobId}/retry`)
/** Stop: queued jobs are cancelled, running ones finish, the turn ends after its current step. */
export const stopJobs = (id: string) => post<{ cancelled: number }>(`/videos/${id}/jobs/stop`)
/** The latest ready render of a mode and any render in progress. */
export const getLatestRender = (id: string, mode: 'final' | 'proposals') =>
  get<RenderState>(`/videos/${id}/renders/latest?mode=${mode}`)
/** Render now, in the background: a render_preview job. */
export const startRender = (id: string, mode: 'final' | 'proposals') => post<ActivityJob>(`/videos/${id}/renders`, { mode })
/** The live channel: job.updated, turn.updated, render.updated. */
export const eventsUrl = (id: string) => `${BASE}/videos/${id}/events`
// D1: project templates.
export const listTemplates = async () => (await get<{ templates?: ProjectTemplate[] }>('/templates')).templates ?? []
export const saveTemplate = (projectId: string, name: string, voice?: 'copy' | 'keep') =>
  post<ProjectTemplate>(`/projects/${projectId}/template`, voice ? { name, voice } : { name })
export const renameTemplate = (id: string, name: string) => patch<ProjectTemplate>(`/templates/${id}`, { name })
export const deleteTemplate = (id: string) => del(`/templates/${id}`)
export const createFolderFrom = (name: string, templateId: string) => post<ProjectFolder>('/projects', { name, template_id: templateId })
// D2: learned style.
export const getLearned = (id: string) => get<LearnedPage>(`/projects/${id}/learned`)
export const answerLearned = (id: string, itemId: number, answer: 'accept' | 'dismiss') => post<LearnedPage>(`/projects/${id}/learned/${itemId}/${answer}`)
export async function removeLearned(id: string, itemId: number): Promise<LearnedPage> {
  const res = await fetch(`${BASE}/projects/${id}/learned/${itemId}`, { method: 'DELETE', headers: FROM_VOLTAGE })
  if (!res.ok) return failure(res)
  return (await res.json()) as LearnedPage
}
export const giveDecisionReason = (videoId: string, decisionId: number, reason: string) =>
  post<{ decision_id: number; reason: string }>(`/videos/${videoId}/decisions/${decisionId}/reason`, { reason })

/** G8: your thumbs on this video's takes and replies, and one vote (null clears it). */
export type FeedbackTarget = 'take' | 'turn'
export type FeedbackVote = 'up' | 'down'
export interface FeedbackMark { vote: FeedbackVote; reason: string }
export const getFeedback = (videoId: string) => get<Record<FeedbackTarget, Record<string, FeedbackMark>>>(`/videos/${videoId}/feedback`)
export const putFeedback = (videoId: string, body: { target: FeedbackTarget; target_id: string; vote: FeedbackVote | null; reason?: string }) =>
  put<{ target: FeedbackTarget; target_id: string; vote: FeedbackVote | null; reason: string }>(`/videos/${videoId}/feedback`, body)


/** G3: billing (fake providers, test mode). */
export const getBilling = () => get<BillingView>('/billing')
export const putBillingDetails = (d: { country: string | null; legal_name: string; gstin: string; state_code: string | null }) => put<BillingView>('/billing/details', d)
export const changePlan = (plan: string) => post<BillingView>('/billing/plan', { plan })
export const topUp = (credits: number) => post<BillingView>('/billing/topup', { credits })
export const invoiceUrl = (id: number) => `/api/billing/invoices/${id}`
export const verifyRazorpay = (paid: { order_id: string; payment_id: string; signature: string }) => post<BillingView>('/billing/razorpay/verify', paid)

/** G6: trust and safety (fake providers, test mode). Run 4 item 2: with `voices.cloning_verified`
 *  the read-aloud step is the real gate, `verified`; a check can also be with a reviewer. */
export type ConsentStatus = 'waiting' | 'passed' | 'review' | 'failed'
export interface ConsentAttempt { attempt_id: string; sentence: string; status: ConsentStatus; reason: string; tip: string; test_mode: boolean; verified: boolean; min_seconds?: number }
export const startLiveness = (videoId: string, speaker?: string | null, fresh = false) =>
  post<ConsentAttempt>(`/videos/${videoId}/liveness`, { speaker: speaker ?? null, ...(fresh ? { fresh: true } : {}) })
export async function sendLiveness(videoId: string, attemptId: string, audio: Blob, name = 'liveness.webm'): Promise<Omit<ConsentAttempt, 'sentence'>> {
  const body = new FormData()
  body.append('file', audio, name)
  const res = await fetch(`${BASE}/videos/${videoId}/liveness/${attemptId}`, { method: 'POST', headers: FROM_VOLTAGE, body })
  if (!res.ok) return failure(res)
  return res.json()
}
export const withdrawConsent = (videoId: string) => post<{ withdrawn: boolean; deleted: number; failed: string[]; said: string }>(`/videos/${videoId}/consent/withdraw`)
export const abuseFormOpen = async () => (await get<{ open: boolean }>('/abuse-reports/open')).open
export const reportAbuse = (r: { location: string; kind: string; details: string; contact: string }) => post<{ report_id: number; said: string }>('/abuse-reports', r)
export interface DataRequest { id: number; kind: 'export' | 'deletion'; status: string; job_id: string | null; created_at: string; done_at: string | null; job: ActivityJob | null }
export const startDataExport = () => post<{ request: DataRequest }>('/me/data-export')
export const listDataRequests = () => get<{ requests: DataRequest[] }>('/me/data-export')
export const dataExportUrl = (jobId: string) => signed(`${BASE}/me/data-export/${jobId}/download`)

// Launch item 8: the landing page's prices (public, from app/billing/prices.py), Request access, the admin's waitlist.
export interface PublicPricing {
  trial_credits: number; credit_usd: number; topup_months: number; test_mode: boolean; languages: boolean; invite_only: boolean
  plans: { plan_id: string; name: string; credits: number; blurb: string; usd: number; inr: number }[]
  topups: { credits: number; usd: number; inr: number }[]
}
export const getPricing = () => get<PublicPricing>('/pricing')
export const joinWaitlist = (r: { email: string; name?: string; use_case?: string }) => post<{ ok: boolean; message: string }>('/waitlist', r)
export interface WaitlistRow { id: number; email: string; name: string | null; use_case: string | null; created_at: string; invited_at: string | null; invited_by: string | null; status: 'waiting' | 'invited'; beta?: boolean }
export const getAdminWaitlist = () => get<{ rows: WaitlistRow[]; invite_only: boolean }>('/admin/waitlist')
export const sendWaitlistInvite = (id: number, beta = false) => post<{ row: WaitlistRow }>(`/admin/waitlist/${id}/invite`, beta ? { beta: true } : undefined)
