import type {
  Project, ApprovedResult, ExportManifest, EditRequest, Job, ProjectSummary, ProjectDetail, Usage, Voice, Speaker,
} from './types'

const BASE = '/api'

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
    headers: { 'Content-Type': 'application/json' },
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
export async function createProject(file: File, consent: boolean): Promise<Project> {
  const body = new FormData()
  body.append('file', file)
  body.append('consent', String(consent))
  const res = await fetch(`${BASE}/projects`, { method: 'POST', body })
  if (!res.ok) return failure(res)
  return (await res.json()) as Project
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

export const listVoices = () => get<{ default: string; voices: Voice[] }>('/voices')

/** Rename a speaker or set their voice; `voice_id: null` with `clear_voice`
 *  returns them to the chat's voice. */
export async function updateSpeaker(
  id: string, label: string, change: { name?: string; voice_id?: string; clear_voice?: boolean },
): Promise<Speaker[]> {
  const res = await fetch(`${BASE}/projects/${id}/speakers/${label}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
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
  const res = await fetch(`${BASE}/projects/${id}`, { method: 'DELETE' })
  if (!res.ok) return failure(res)
}

/** URL the browser can play a stored artifact from; supports range requests. */
export const artifactUrl = (projectId: string, sha256: string) =>
  `${BASE}/projects/${projectId}/artifacts/${sha256}`

/** Starts generation. Returns the accepted job; poll it for the candidate. */
export const previewEdit = (id: string, req: EditRequest) =>
  post<Job>(`/projects/${id}/edits/preview`, req)

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

/**
 * Approves one previously previewed candidate by id. The backend commits the
 * exact media that preview produced rather than regenerating it — which real
 * vendors would not reproduce byte-for-byte.
 */
export const approveEdit = (id: string, candidateId: string, override = false) =>
  post<ApprovedResult>(
    `/projects/${id}/edits`,
    // `override` approves a candidate that failed continuity, for trials.
    override ? { candidate_id: candidateId, override: true } : { candidate_id: candidateId },
  )

export const exportProject = (id: string) =>
  post<ExportManifest>(`/projects/${id}/export`)
