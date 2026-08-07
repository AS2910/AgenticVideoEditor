import type {
  Project, Candidate, ApprovedResult, ExportManifest, EditRequest,
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

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    throw new ApiError(res.status, await res.text())
  }
  return (await res.json()) as T
}

export const createProject = (filename: string, duration: number) =>
  post<Project>('/projects', { filename, duration })

export const previewEdit = (id: string, req: EditRequest) =>
  post<Candidate>(`/projects/${id}/edits/preview`, req)

export const approveEdit = (id: string, req: EditRequest) =>
  post<ApprovedResult>(`/projects/${id}/edits`, req)

export const exportProject = (id: string) =>
  post<ExportManifest>(`/projects/${id}/export`)
